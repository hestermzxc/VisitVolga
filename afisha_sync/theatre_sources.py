"""Разбор расписаний театров и виджета Radario."""
import datetime as dt
import html
import json
import re
from http.cookiejar import CookieJar
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, build_opener

from parsers import MONTHS_GEN, MONTHS_NOM, fetch, sp, year_for

TIME = re.compile(r'\b([01]?\d|2[0-3])[:.]([0-5]\d)\b')
PRICE = re.compile(r'((?:от\s+)?\d[\d ]*(?:\s*[-–—]\s*\d[\d ]*)?)\s*(?:руб|₽)', re.I)


def document(html):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, 'html.parser')


def text(node):
    return sp(node.get_text(' ', strip=True)) if node else ''


def event(day, title, clock, price_text, url, kind=''):
    price = PRICE.search(price_text)
    price = re.sub(r'\s*[-–—]\s*', '–', price[1].strip()) + ' руб.' if price else ''
    times = [f'{int(h)}.{m}' for h, m in TIME.findall(clock)]
    return dict(d=day, title=title.strip(), times=times, price=price,
                url=url, place='', kind=kind, raw=' | '.join(x for x in (title, clock, price) if x))


def parse_teatr21(url, today, log):
    soup = document(fetch(url))
    events = []
    for card in soup.select('article.event'):
        heading = card.find_previous('h2', class_='section-title')
        month = text(card.select_one('.event__month')).lower()
        day = text(card.select_one('.event__day'))
        link = card.select_one('.event__title a[href]')
        year = re.search(r'\b20\d{2}\b', text(heading))
        if month not in MONTHS_GEN or not day.isdigit() or not link or not year:
            continue
        date = dt.date(int(year[0]), MONTHS_GEN.index(month) + 1, int(day))
        if date >= today:
            meta = text(card.select_one('.event__meta'))
            kind = meta.partition('·')[0].strip() if '·' in meta else ''
            events.append(event(date, text(link), text(card.select_one('.event__time')),
                                text(card.select_one('.event__price')), urljoin(url, link['href']), kind))
    return events


def parse_puppet21(url, today, log):
    events = []
    for script in document(fetch(url)).select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text())
            if data.get('@type') != 'Event' or data.get('eventStatus', '').endswith('EventCancelled'):
                continue
            day = dt.date.fromisoformat(data['startDate'][:10])
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        title = sp(html.unescape(data.get('name') or ''))
        title = re.sub(r'^(?:Премьера!\s*)?Спектакль\s+', '', title, flags=re.I)
        if day < today or not title:
            continue
        title = re.sub(r'\s+(?:0|3|6|12|16|18)\+(?=\s|$)', '', title)
        kind, value = ('Мастер-класс', title[len('Мастер-класс '):]) if title.startswith('Мастер-класс ') else ('', title)
        details = (data.get('location') or {}).get('name', '')
        clock, _, price = details.partition('/')
        events.append(event(day, value, clock, price, data.get('url') or url, kind))
    return events


def parse_maiteatr(url, today, log):
    events = []
    dates = []
    local = False
    months = '|'.join(MONTHS_GEN)
    for record in document(fetch(url)).select('[data-record-type="106"], [data-record-type="772"]'):
        if record['data-record-type'] == '106':
            label = text(record).lower()
            if 'репертуар на' in label or label == 'гастроли':
                local = 'репертуар на' in label
            match = re.fullmatch(rf'([\d /,]+)\s+({months})', label)
            dates = ([year_for(day, MONTHS_GEN.index(match[2]) + 1, today)
                      for day in re.findall(r'\d+', match[1])] if match and local else [])
            continue
        if not dates:
            continue
        for card in record.select('.t-card__col'):
            title = text(card.select_one('.t-card__title'))
            link = card.select_one('a.t-card__link[href]')
            if not title:
                continue
            description = text(card.select_one('.t-card__descr'))
            kind = next((name for name in ('Комедия', 'Сказка', 'Концерт', 'Моноспектакль')
                         if description.lower().startswith(name.lower())), '')
            clock = text(card.select_one('.t-card__uptitle'))
            # Общий список нескольких часов для нескольких дат не задаёт соответствия.
            if len(dates) > 1 and len(TIME.findall(clock)) > 1:
                clock = ''
            for day in dates:
                if day and day >= today:
                    events.append(event(day, title, clock, '', urljoin(url, link['href']) if link else url, kind))
    return events


def parse_chuvdram(url, today, log):
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    index = document(fetch(url, opener=opener))
    pages = {}
    for link in index.select('main a[href]'):
        month = text(link).rsplit('/', 1)[-1].strip().lower()
        page_url = urljoin(url, link['href'])
        if month in MONTHS_NOM and urlsplit(page_url).hostname == urlsplit(url).hostname:
            pages.setdefault(month, page_url)
    events = []
    for month, page_url in pages.items():
        try:
            page = document(fetch(page_url, opener=opener))
        except Exception as exc:
            log(f'  ! не загрузилось {page_url}: {exc}')
            continue
        current = None
        for row in page.select('main .e-parent'):
            headings = [text(h) for h in row.select('.elementor-heading-title')]
            if month in (h.lower() for h in headings):
                day = next((h for h in headings if re.fullmatch(r'\d{1,2}', h)), '')
                clock = next((h for h in headings if TIME.fullmatch(h)), '')
                current = (year_for(day, MONTHS_NOM.index(month) + 1, today), clock) if day else None
                continue
            title_node = row.select_one('h2.elementor-heading-title')
            if not current or not title_node or 'Купить билет' not in text(row):
                continue
            day, clock = current
            current = None
            if not day or day < today:
                continue
            title = text(title_node)
            subtitle = next((h for h in headings if re.search(r'[«"]([^»"]+)[»"]', h)), '')
            russian = re.search(r'[«"]([^»"]+)[»"]', subtitle)
            link = title_node.select_one('a[href]') or row.select_one('.elementor-widget-image a[href]')
            kind = subtitle.split(maxsplit=1)[0].capitalize() if russian else ''
            if russian:
                title = russian[1]
            events.append(event(day, title, clock, '', urljoin(page_url, link['href']) if link else page_url, kind))
    return events


def parse_radario(url, today, log):
    html = fetch(url)
    keys = dict.fromkeys(re.findall(r'radario\.Widgets\.Afisha\(\{[^\n]*?"key"\s*:\s*"([0-9a-f]+)"', html))
    if not keys:
        raise ValueError('на странице не найден виджет афиши Radario')
    events = {}
    for key in keys:
        page = 0
        while True:
            query = urlencode(dict(key=key, page=page))
            data = json.loads(fetch(f'https://radario.ru/json/widgets/afisha/events?{query}'))
            if data['page'] != page:
                raise ValueError('Radario вернул неожиданную страницу афиши')
            for item in data['events']:
                # Виджет публикует местное время показа в полях даты с суффиксом +00:00.
                start = dt.datetime.fromisoformat(item['beginDate'].replace('Z', '+00:00'))
                if item['ended'] or start.date() < today:
                    continue
                lo, hi = item.get('minPrice'), item.get('maxPrice')
                price = f'{lo:g}–{hi:g} руб.' if lo and hi and hi != lo else f'{lo:g} руб.' if lo else ''
                link = f"https://radario.ru/customer/event/{item['id']}/info"
                events[item['id']] = event(start.date(), item['title'], start.strftime('%H:%M'), price, link)
            if data['lastPage']:
                break
            page += 1
    return list(events.values())


THEATRE_PARSERS = {
    'teatr21': parse_teatr21,
    'chuvdram': parse_chuvdram,
    'puppet21': parse_puppet21,
    'maiteatr': parse_maiteatr,
    'radario': parse_radario,
}
