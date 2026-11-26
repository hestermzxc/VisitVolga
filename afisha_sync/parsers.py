"""Загрузка и разбор сайтов с афишей.

Каждый парсер возвращает список событий в общем виде:
    dict(d=date, times=['18.00'], title='...', price='400–1200 руб.', raw='...', url='...', place='', kind='')
Исключение — afisha21: его анонсы написаны свободным текстом и разбираются в compare.py.
"""
import re, html, json, time, datetime as dt, urllib.request
from urllib.parse import urljoin, urlparse

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) afisha-sync'
MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
MONTHS_NOM = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']


def fetch(url, timeout=30, retries=2):
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw, ct = r.read(), r.headers.get('Content-Type', '')
            m = re.search(r'charset=([\w-]+)', ct) or re.search(r'charset=["\']?([\w-]+)', raw[:4000].decode('ascii', 'ignore'))
            return raw.decode(m.group(1) if m else 'utf-8', 'replace')
        except Exception as e:  # сеть/таймаут — повторяем
            last = e
            time.sleep(2)
    raise last


def txt(s):
    return html.unescape(re.sub(r'<[^>]+>', ' ', s)).replace('\xa0', ' ').strip()


def sp(s):
    return re.sub(r'\s+', ' ', s).strip()


def text_lines(h):
    h = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', h)
    return [l for l in (html.unescape(x).replace('\xa0', ' ').strip() for x in re.sub(r'<[^>]+>', '\n', h).split('\n')) if l]


def year_for(d, m, today):
    """Год для даты без года: если дата «в прошлом» больше чем на 4 месяца — значит, следующий год."""
    try:
        x = dt.date(today.year, m, int(d))
    except ValueError:
        return None
    return x.replace(year=today.year + 1) if (today - x).days > 120 else x


def month_list(today, n):
    y, m = today.year, today.month
    for _ in range(n):
        yield y, m
        m += 1
        if m == 13: y, m = y + 1, 1


# ---------------------------------------------------------------- afisha21.ru
def parse_afisha21(url, months, today, log):
    """Анонсы (главная + /go/?date=YYYY-MM) и театральная таблица (/teatr/?date=YYYY-MM)."""
    base = '{0.scheme}://{0.netloc}'.format(urlparse(url))
    ann, th = {}, []
    pages = [url] + [f'{base}/go/?date={y}-{m:02d}' for y, m in month_list(today, months)]
    for p in pages:
        try:
            h = fetch(p)
        except Exception as e:
            log(f'  ! не загрузилось {p}: {e}'); continue
        n0 = len(ann)
        for body in h.split("<div class='newsoneline'")[1:]:
            tg = re.match(r"\s*data-tags='([^']*)'", body)
            idm = re.search(r"class='titlehref' href='[^']*/go/(\d+)'>(.*?)</a>", body, re.S)
            if not idm: continue
            intro = re.search(r"<div class='intros'>(.*?)</div>", body, re.S)
            ann[idm.group(1)] = dict(id=idm.group(1), title=sp(txt(idm.group(2))),
                                     intro=sp(txt(intro.group(1))) if intro else '', tags=tg.group(1) if tg else '')
        log(f'  {p}: анонсов +{len(ann) - n0}')
    for y, m in month_list(today, months):
        p = f'{base}/teatr/?date={y}-{m:02d}'
        try:
            h = fetch(p)
        except Exception as e:
            log(f'  ! не загрузилось {p}: {e}'); continue
        h1 = re.search(r'<h1>([^<]*)', h)
        if not h1 or MONTHS_NOM[m - 1] not in h1.group(1).lower() or str(y) not in h1.group(1):
            log(f'  {p}: месяц ещё не опубликован'); continue
        day, n0 = None, len(th)
        for mm in re.finditer(r"<div class='oneteatr'>(.*?)(?=<div class='oneteatr'>|<div class='dateoneteatr'>|</main>)", h, re.S):
            b = mm.group(1)
            dd = re.search(r"dayteatr day(\d{2})-(\d{2})", b)
            if dd: day = (int(dd.group(1)), int(dd.group(2)))
            t = re.search(r"<h2>(?:<a href='([^']*)'[^>]*>)?(.*?)(?:</a>)?</h2>", b, re.S)
            if not t or not day: continue
            times = re.search(r"<div class='teatrrow1_[^']*'>(.*?)</div>", b, re.S)
            genre = re.search(r"<div style='clear:both'>(.*?)</div>", b, re.S)
            place = re.search(r"teatrrow2_[^']*'>(.*?)</div>", b, re.S)
            price = re.search(r"teatrrow4[^']*'>(.*?)</div></div>", b, re.S)
            th.append(dict(date=dt.date(y, day[1], day[0]),
                           times=sp(txt(times.group(1).replace('<br>', ','))) if times else '',
                           title=sp(txt(t.group(2))), url=t.group(1) or '',
                           genre=sp(txt(genre.group(1))) if genre else '',
                           place=sp(txt(place.group(1))) if place else '',
                           price=sp(txt(price.group(1))) if price else ''))
        log(f'  {p}: показов {len(th) - n0}')
    return dict(ann=list(ann.values()), theatre=th)


# ---------------------------------------------------------------- rusdram21.ru
def parse_rusdram(url, today, log):
    """Официальная афиша Русского драмтеатра: «31 | октября | суббота | Название | ... | Начало в 18:00 | Купить билет | 400-1200»."""
    L = text_lines(fetch(url))
    ev, i = [], 0
    while i < len(L) - 2:
        if re.fullmatch(r'\d{1,2}', L[i]) and L[i + 1] in MONTHS_GEN:
            d = year_for(L[i], MONTHS_GEN.index(L[i + 1]) + 1, today)
            j = i + 2
            if re.match(r'^(понедельник|вторник|среда|четверг|пятница|суббота|воскресенье)$', L[j]): j += 1
            block = []
            while j < len(L) and not (re.fullmatch(r'\d{1,2}', L[j]) and j + 1 < len(L) and L[j + 1] in MONTHS_GEN):
                block.append(L[j]); j += 1
            start = next((x for x in block if x.startswith('Начало')), '')
            tm = re.search(r'(\d{1,2}):(\d{2})', start)
            pi = [k for k, x in enumerate(block) if x == 'Купить билет']
            price = block[pi[0] + 1].strip() if pi and pi[0] + 1 < len(block) else ''
            title = block[0] if block and not re.fullmatch(r'\d+\+', block[0]) else ''
            if d and title:
                ev.append(dict(d=d, times=[f'{int(tm.group(1))}.{tm.group(2)}'] if tm else [], title=title,
                               price=(price.replace('-', '–') + ' руб.') if re.search(r'\d', price) else '',
                               raw='|'.join(block[:8]), url=url, place='', kind=''))
            i = j
        else:
            i += 1
    log(f'  {url}: событий {len(ev)}')
    return ev


# ---------------------------------------------------------------- schema.org Event (JSON-LD)
EVENT_TYPES = re.compile(r'Event$')


def _walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values(): yield from _walk(v)
    elif isinstance(o, list):
        for v in o: yield from _walk(v)


def parse_jsonld(url, today, log):
    """Любая страница с разметкой schema.org Event (многие билетные сервисы и сайты театров)."""
    h = fetch(url)
    ev = []
    for block in re.findall(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', h):
        try:
            data = json.loads(html.unescape(block.strip()))
        except ValueError:
            continue
        for o in _walk(data):
            t = o.get('@type')
            t = t[0] if isinstance(t, list) and t else t
            if not isinstance(t, str) or not EVENT_TYPES.search(t) or not o.get('startDate'): continue
            m = re.match(r'(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?', o['startDate'])
            if not m: continue
            d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            offers = o.get('offers') or {}
            offers = offers[0] if isinstance(offers, list) and offers else offers
            lo = offers.get('lowPrice') or offers.get('price') if isinstance(offers, dict) else None
            hi = offers.get('highPrice') if isinstance(offers, dict) else None
            price = ''
            if lo and hi and str(lo) != str(hi): price = f'{int(float(lo))}–{int(float(hi))} руб.'
            elif lo: price = f'{int(float(lo))} руб.'
            loc = o.get('location') or {}
            loc = loc[0] if isinstance(loc, list) and loc else loc
            ev.append(dict(d=d, times=[f'{int(m.group(4))}.{m.group(5)}'] if m.group(4) else [],
                           title=sp(html.unescape(str(o.get('name', '')))), price=price,
                           raw=f"{o.get('name')} | {o['startDate']} | {price}", url=o.get('url') or url,
                           place=loc.get('name', '') if isinstance(loc, dict) else '', kind=''))
    log(f'  {url}: событий (schema.org) {len(ev)}')
    return ev


def detect_type(url):
    host = urlparse(url).netloc.lower()
    if 'afisha21.ru' in host: return 'afisha21'
    if 'rusdram21.ru' in host: return 'rusdram21'
    return 'jsonld'
