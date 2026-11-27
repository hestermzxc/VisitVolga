"""Цены, опубликованные билетными системами для отдельных сеансов."""
from __future__ import annotations

import datetime as dt
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from compare import format_price, norm
from parsers import UA, _walk, fetch, offers_sold_out

TICKETLAND_FEED = 'https://csvdata.ticketland.ru/yandex/foraffiliates_all.xml'
CHUVDRAM_VENUE_ID = '4827051'
CHEBOKSARY_TIME = dt.timezone(dt.timedelta(hours=3))
QUICKTICKETS_PATH = re.compile(r'/cheboksary-teatr-kukol/s\d+/?')
TICKETLAND_SESSION_PATH = re.compile(
    r'/teatry/chuvash-teatr-im-ivanova/[^/]+/t_\d{8}_\d{4}_p_\d+/?'
)


@dataclass(frozen=True)
class SessionPrice:
    minimum: Decimal | None
    maximum: Decimal | None
    url: str
    sold_out: bool = False

    @property
    def text(self):
        return format_price(self.minimum, self.maximum) if self.minimum is not None else ''


def amount(value):
    try:
        number = Decimal(str(value).replace(',', '.'))
    except (InvalidOperation, ValueError):
        return None
    if (not number.is_finite() or not 0 <= number <= 10_000_000
            or number != number.quantize(Decimal('0.01'))):
        return None
    return number


def title_keys(*titles):
    keys = set()
    for title in titles:
        plain = re.sub(r'^\s*(?:премьера[!\s]+|(?:спектакль|концерт|мастер-класс|квест)\s+)+', '', title, flags=re.I)
        aliases = [plain, *plain.split('/')]
        parenthetical = re.fullmatch(r'(.+?)\s*\(([^()]+)\)\s*[»"]?', plain)
        if parenthetical:
            aliases.append(parenthetical[1])
        keys.update(key for alias in aliases if (key := norm(alias)))
    return keys


def session_minute(value):
    """Принимает локальное время источника или ISO с часовым поясом."""
    try:
        stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (AttributeError, ValueError):
        return None
    if 'T' not in value and ' ' not in value:
        return None
    if stamp.tzinfo:
        stamp = stamp.astimezone(CHEBOKSARY_TIME).replace(tzinfo=None)
    return stamp.replace(second=0, microsecond=0)


def scheduled_minute(day, time):
    hour, minute = map(int, time.split('.'))
    return dt.datetime.combine(day, dt.time(hour, minute))


def read_ticketland_feed(stream, requested):
    """Читает опубликованный XML потоком и хранит только интересующие сеансы."""
    result = {}
    nodes = ET.iterparse(stream, events=('start', 'end'))
    _, root = next(nodes)
    if root.tag != 'events':
        raise ValueError('неожиданный формат фида Ticketland')
    for action, node in nodes:
        if action != 'end' or node.tag != 'event':
            continue
        if node.findtext('venue_id') == CHUVDRAM_VENUE_ID:
            stamp = session_minute(node.findtext('first_date'))
            if stamp in requested and stamp == session_minute(node.findtext('last_date')):
                link = node.findtext('url', '')
                parsed = urlsplit(link)
                # Дата в адресе может сохраняться после переноса сеанса.
                if (parsed.scheme == 'https' and parsed.netloc == 'csy.ticketland.ru'
                        and TICKETLAND_SESSION_PATH.fullmatch(parsed.path)):
                    titles = title_keys(node.findtext('title', ''), node.findtext('full_title', ''))
                    minimum = amount(node.findtext('min_price'))
                    maximum = amount(node.findtext('max_price'))
                    count = amount(node.findtext('tickets_count'))
                    if titles and count == 0:
                        result.setdefault(stamp, []).append((titles, SessionPrice(None, None, link, sold_out=True)))
                    elif titles and minimum is not None and maximum is not None and minimum <= maximum and count:
                        result.setdefault(stamp, []).append((titles, SessionPrice(minimum, maximum, link)))
        root.clear()
    return result


def find_ticketland_price(entries, titles):
    matches = {price for names, price in entries if names & titles}
    if not matches:
        # В длинном названии допускается пропущенная удвоенная буква.
        def key(name):
            return re.sub(r'([а-я])\1', r'\1', name)

        aliases = {key(title) for title in titles if len(title) >= 12}
        matches = {price for names, price in entries if not price.sold_out and any(key(name) in aliases for name in names)}
    if len(matches) == 1:
        return next(iter(matches))
    return None


def add_ticketland_prices(records, log):
    sessions = [record for record in records if record.get('ticketland')
                and not record.get('sold_out') and len(record['times']) == 1]
    requested = {scheduled_minute(record['d'], record['times'][0]) for record in sessions}
    if not requested:
        return
    try:
        request = Request(TICKETLAND_FEED, headers={'User-Agent': UA})
        with urlopen(request, timeout=30) as stream:
            prices = read_ticketland_feed(stream, requested)
    except (OSError, ValueError, ET.ParseError) as error:
        log(f'  ! не удалось получить фид цен Ticketland: {error}')
        for record in sessions:
            record['price_issue'] = 'цена не проверена: фид Ticketland недоступен'
        return

    confirmed = sold_out = 0
    for record in sessions:
        start = scheduled_minute(record['d'], record['times'][0])
        names = title_keys(record['title'], record['original_title'])
        price = find_ticketland_price(prices.get(start, ()), names)
        if price and price.sold_out:
            record['sold_out'] = True
            sold_out += 1
        elif price:
            record.update(price=price.text, price_url=price.url)
            confirmed += 1
        else:
            record['price_issue'] = 'цена не проверена: в Ticketland нет однозначного совпадения по сеансу'
    log(f'  Ticketland: цены подтверждены для {confirmed} из {len(sessions)} сеансов с виджетом, '
        f'распродано сеансов: {sold_out}')


def quicktickets_url(link):
    if not isinstance(link, str):
        return ''
    parsed = urlsplit(link)
    if parsed.scheme == 'https' and parsed.netloc == 'quicktickets.ru' and QUICKTICKETS_PATH.fullmatch(parsed.path):
        return f'https://quicktickets.ru{parsed.path.rstrip("/")}'
    return ''


def read_quicktickets_price(soup, url, start, names):
    prices = set()
    session_offers = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(), parse_float=Decimal)
        except ValueError:
            continue
        for entry in _walk(data):
            if (entry.get('@type') != 'Event'
                    or quicktickets_url(entry.get('url') or '') != url
                    or session_minute(entry.get('startDate')) != start
                    or not str(entry.get('eventStatus', '')).endswith('EventScheduled')
                    or not (title_keys(entry.get('name') or '') & names)):
                continue
            offers = entry.get('offers') or []
            offers = offers if isinstance(offers, list) else [offers]
            session_offers.extend(offers or [{}])
            for offer in offers:
                if not isinstance(offer, dict) or offer.get('priceCurrency') != 'RUB' or not str(offer.get('availability', '')).endswith(
                    ('/InStock', '/LimitedAvailability')
                ):
                    continue
                if offer.get('@type') == 'AggregateOffer':
                    lo, hi = amount(offer.get('lowPrice')), amount(offer.get('highPrice'))
                    if lo is not None and hi is not None and lo <= hi:
                        prices.add(SessionPrice(lo, hi, url))
                elif offer.get('@type') == 'Offer':
                    value = amount(offer.get('price'))
                    if value is not None:
                        # Публичная карточка может указывать только минимальную цену.
                        prices.add(SessionPrice(value, None if value else value, url))
    if offers_sold_out(session_offers):
        return SessionPrice(None, None, url, sold_out=True)
    if len(prices) == 1:
        return next(iter(prices))
    return None


def add_quicktickets_price(record, url, document, log):
    if len(record['times']) != 1 or not url:
        return
    try:
        page = document(fetch(url, timeout=12, retries=0))
        start = scheduled_minute(record['d'], record['times'][0])
        price = read_quicktickets_price(page, url, start, title_keys(record['title']))
    except OSError as error:
        log(f'  ! не удалось прочитать цену Quick Tickets: {error}')
        price = None
    if price and price.sold_out:
        record['sold_out'] = True
    elif price:
        record.update(price=price.text, price_url=price.url)
    else:
        record['price_issue'] = 'цена не проверена: Quick Tickets не подтвердил цену этого сеанса'
