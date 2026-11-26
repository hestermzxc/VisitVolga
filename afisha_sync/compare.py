"""Сопоставление афиши сайта (выгрузка CSV из Битрикса) с событиями из источников."""
import re, random, datetime as dt, collections
from difflib import SequenceMatcher
from parsers import year_for

TODAY = dt.date.today()
MON = {'январ': 1, 'феврал': 2, 'март': 3, 'апрел': 4, 'ма': 5, 'июн': 6, 'июл': 7, 'август': 8, 'сентябр': 9, 'октябр': 10, 'ноябр': 11, 'нобр': 11, 'декабр': 12}
MON_RE = r'(январ[ья]|феврал[ья]|марта?|апрел[ья]|ма[яй]|июн[ья]|июл[ья]|августа?|сентябр[ья]|октябр[ья]|ноябр[ья]|нобря|декабр[ья])'
MON_GEN = ['', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
GENRE_OK = {'комедия', 'драма', 'мелодрама', 'сказка', 'опера', 'балет', 'трагедия', 'мюзикл', 'трагикомедия', 'оперетта', 'концерт'}
MATCH = 0.72


def mon(w):
    for k, v in sorted(MON.items(), key=lambda x: -len(x[0])):
        if w.startswith(k): return v


def mkdate(d, m):
    return year_for(d, m, TODAY)


def parse_dates(s):
    s = s.replace('–', '-').replace('—', '-')
    r = re.search(r'[Сс]\s+(\d{1,2})\s*' + MON_RE + r'?\s+по\s+(\d{1,2})\s+' + MON_RE, s)
    if r:
        m2 = mon(r.group(4)); m1 = mon(r.group(2)) if r.group(2) else m2
        a, b = mkdate(r.group(1), m1), mkdate(r.group(3), m2)
        if a and b and a > b: a = a.replace(year=a.year - 1)  # «с 30 сентября по 14 декабря»
        return [], a, b
    r = re.search(r'(\d{1,2})\s*-\s*(\d{1,2})\s+' + MON_RE, s)
    if r:
        m = mon(r.group(3)); return [], mkdate(r.group(1), m), mkdate(r.group(2), m)
    dates = []
    for g in re.finditer(r'((?:\d{1,2}\s*(?:,|и)\s*)*\d{1,2})\s+' + MON_RE, s):
        m = mon(g.group(2))
        for d in re.findall(r'\d{1,2}', g.group(1)):
            x = mkdate(d, m)
            if x: dates.append(x)
    return sorted(set(dates)), None, None


def times_of(s):
    return [f'{int(h)}.{m}' for h, m in re.findall(r'\b(\d{1,2})[:.](\d{2})\b', s)]


def price_of(s):
    if re.search(r'[Вв]ход свободный|[Вв]ход бесплатный|бесплатно', s): return 'Вход свободный'
    r = re.search(r'((?:от\s*)?\d[\d\s]*(?:-\d[\d\s]*)?)\s*(?:руб|₽)', s)
    return r.group(1).strip().replace('-', '–') + ' руб.' if r else ''


def nums(p):
    return [int(x.replace(' ', '')) for x in re.findall(r'\d[\d ]*', p or '')]


def fix_price(p):
    """«4000–1200 руб.» (опечатка в источнике) -> «1200–4000 руб.»"""
    n = nums(p)
    if len(n) == 2 and n[0] > n[1] and not p.startswith('от'):
        return f'{n[1]}–{n[0]} руб.', True
    return p, False


CHUV = str.maketrans({'ӑ': 'а', 'ă': 'а', 'ӗ': 'е', 'ĕ': 'е', 'ҫ': 'с', 'ç': 'с', 'ӳ': 'у', 'ÿ': 'у', 'Ӑ': 'А', 'Ă': 'А',
                      'Ӗ': 'Е', 'Ĕ': 'Е', 'Ҫ': 'С', 'Ç': 'С', 'Ӳ': 'У', 'Ÿ': 'У', '‑': '-'})


def norm(s):
    s = s.translate(CHUV).lower().replace('ё', 'е')
    s = re.sub(r'\(\d+\+\)|\d+\+', ' ', s)
    s = re.sub(r'[«»"“”„\'`.,:;!?()\-–—/]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def core(s):
    q = re.findall(r'[«"“]([^»"”]+)[»"”]?', s)
    return norm(' '.join(q)) if q else norm(s)


STOP = {'выступление', 'стендап', 'сольный', 'концерт', 'спектакль', 'премьера', 'спектакля', 'сказка', 'комедия', 'драма',
        'шоу', 'вечер', 'группа', 'группы', 'программа', 'в', 'и', 'на', 'с', 'для', 'по'}


def sim(a, b):
    ca, cb = core(a), core(b)
    if not ca or not cb: return 0
    if len(ca) >= 5 and len(cb) >= 5 and (ca in norm(b) or cb in norm(a)): return 1.0
    if min(len(ca), len(cb)) >= 3 and (norm(a).endswith(' ' + cb) or norm(b).endswith(' ' + ca)): return 0.95
    r = SequenceMatcher(None, ca, cb).ratio()
    ta = [w for w in norm(a).split() if w not in STOP and len(w) > 2]
    tb = [w for w in norm(b).split() if w not in STOP and len(w) > 2]
    if ta and tb:
        small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
        hit = sum(1 for w in small if any(w == x or (min(len(w), len(x)) >= 4 and SequenceMatcher(None, w, x).ratio() >= 0.75) for x in big))
        if hit == len(small) and (len(small) >= 2 or len(small[0]) >= 6): r = max(r, 0.9)
    return r


TR = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя', ['a', 'b', 'v', 'g', 'd', 'e', 'e', 'zh', 'z', 'i', 'y', 'k', 'l', 'm', 'n', 'o', 'p',
                                                      'r', 's', 't', 'u', 'f', 'kh', 'ts', 'ch', 'sh', 'shch', '', 'y', '', 'e', 'yu', 'ya']))


def slug(s):
    s = ''.join(TR.get(ch, ch) for ch in s.translate(CHUV).lower())
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', s)).strip('-')[:100]


# ---------------------------------------------------------------- названия
MALE_FIRST = {'Павел': 'Павла', 'Лев': 'Льва'}


def gen_first(w):
    if w in MALE_FIRST: return MALE_FIRST[w]
    if w.endswith('я'): return w[:-1] + 'и'
    if w.endswith('а'): return w[:-1] + ('и' if w[-2] in 'гкхжшчщ' else 'ы')
    if w.endswith('й'): return w[:-1] + 'я'
    return w + 'а'


def gen_last(w, fem):
    if fem:
        return w[:-1] + 'ой' if re.search(r'(ова|ева|ёва|ина|ына|ская)$', w) else w
    if w.endswith('ский'): return w[:-2] + 'ого'
    return w + 'а' if re.search(r'[бвгджзклмнпрстфхцчшщ]$', w) else w


def person_title(what):
    """'Сергей Трофимов' -> 'Выступление Сергея Трофимова'; другие «голые» имена -> 'Выступление: X'."""
    m = re.match(r'^([А-ЯЁ][а-яё]+) ([А-ЯЁ][а-яё]+)$', what)
    if m:
        f, l = m.groups()
        return f'Выступление {gen_first(f)} {gen_last(l, f[-1] in "ая")}', 'название собрано из имени артиста — проверить склонение'
    if re.search(r'(?i)halloween|party', what): return what, None
    if (re.match(r"^[A-Za-z][A-Za-z`' ]*$", what) or re.match(r'^[А-ЯЁ][а-яё]+$', what)
            or re.match(r'^[А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+ (?:и )?[А-ЯЁ][а-яё]+(?: [А-ЯЁ][а-яё]+)?$', what)):
        return f'Выступление: {what.rstrip("`")}', 'название собрано из имени артиста — проверить'
    return what, None


def site_name(what):
    what = what.strip(' .,-–')
    what = re.sub(r'^группа («[^»]+»)', r'Концерт группы \1', what)
    return what[:1].upper() + what[1:]


def official_name(title, kind):
    """Название события с официального сайта -> в стиле сайта («Премьера спектакля «X»», «Спектакль «X» (гастроли)»)."""
    prem = re.search(r'\(премьера\)', title, re.I)
    tour = re.search(r'\(гастроли\)', title, re.I)
    t = re.sub(r'\s*\((премьера|гастроли)\)', '', title, flags=re.I).strip().strip('«»"')
    if re.search(r'(?i)закулисье|экскурси', t): return f'Экскурсия «{t}»'
    if prem: return f'Премьера спектакля «{t}»'
    return f'{kind} «{t}»' + (' (гастроли)' if tour else '')


# ---------------------------------------------------------------- основной расчёт
def run(rows, a21, generic, venues, theatres, vname, today):
    """
    rows     — строки выгрузки сайта (csv.DictReader)
    a21      — dict(ann, theatre) от afisha21 или None
    generic  — [dict(name, url, code, place, official, kind, events=[...])]
    venues   — [(regex, code, place)] для анонсов afisha21
    theatres — {название в театральной таблице afisha21: (code, place)}
    vname    — {код площадки: название}
    """
    global TODAY
    TODAY = today
    codes_used = {r['IE_CODE'] for r in rows}

    def pdt(s):
        for f in ('%d.%m.%Y %H:%M:%S', '%d.%m.%Y'):
            try: return dt.datetime.strptime(s.strip(), f)
            except ValueError: pass

    site = []
    for r in rows:
        a, b = pdt(r['IE_ACTIVE_FROM']), pdt(r['IE_ACTIVE_TO'])
        if not a: continue
        last = (b or a).date()
        if last < TODAY: continue
        rec = bool(re.search(r'постоянная|виртуальная|каждую|каждое', r['IP_PROP28']))
        site.append(dict(r=r, d=TODAY if rec else a.date(), d2=dt.date(2099, 1, 1) if rec else last, name=r['IE_NAME'], rec=rec))

    cand, skipped = [], []
    official = {g['code']: g['name'] for g in generic if g['official'] and g['code']}

    # официальные сайты и прочие «структурные» источники
    for g in generic:
        by_day = collections.OrderedDict()
        for e in g['events']:
            if e['d'] < TODAY or not e['title']: continue
            by_day.setdefault((e['d'], e['title']), dict(e=e, times=[]))['times'] += e['times']
        for (d, title), x in by_day.items():
            e = x['e']
            price, swapped = fix_price(e['price'])
            cand.append(dict(src=g['name'], srcid=e['url'], dates=[d], d1=d, d2=d, times=sorted(set(x['times'])),
                             title=re.sub(r'\s*\((премьера|гастроли)\)', '', title, flags=re.I), sitename=official_name(title, g['kind']),
                             place=g['place'] or e['place'], code=g['code'], p43='' if g['code'] else (g['place'] or e['place']),
                             price=price, tags='театр', flags=['цена в источнике была перевёрнута — исправлено'] if swapped else [],
                             raw=f"{d.strftime('%d.%m.%Y')} {', '.join(x['times'])} | {e['raw']}"))

    if a21:
        seen_th = set()
        for t in a21['theatre']:
            d = t['date']
            code, p43 = theatres.get(t['place'], ('', t['place']))
            if code in official or d < TODAY or (d, t['title'], t['place']) in seen_th: continue
            seen_th.add((d, t['title'], t['place']))
            name = re.sub(r'\s*\(\d+\+\)', '', t['title']).strip()
            parts = re.findall(r'"([^"]+)"', name)
            name = ' / '.join(parts) if parts else name.strip('"')
            g = t['genre'].lower().split(' #')[0].strip()
            kind = g.capitalize() if g in GENRE_OK else 'Спектакль'
            if norm(name).split()[:1] == [kind.lower()]: kind = 'Спектакль'
            price, swapped = fix_price(t['price'].replace('-', '–'))
            cand.append(dict(src='afisha21: театры', srcid=t['url'], dates=[d], d1=d, d2=d,
                             times=[x.strip().replace(':', '.') for x in t['times'].split(',') if x.strip()],
                             title=name, sitename=f'{kind} «{name}»', place=t['place'], code=code, p43=p43, price=price,
                             tags='театр', flags=['цена в источнике была перевёрнута — исправлено'] if swapped else [],
                             raw=f"{d.strftime('%d.%m.%Y')} {t['times']} | {t['title']} | {t['genre']} | {t['place']} | {t['price']}"))

        date_prefix = r'^(?:(?:[Сс]\s+|по\s+|,\s*|и\s+|-\s*|–\s*)*\d{1,2}(?:\s*(?:,|и|-|–)\s*\d{1,2})*\s*(?:' + MON_RE + r')?\s*)+(?:[-–]\s*)?'

        def find_venue(text):
            for pat, code, p43 in venues:
                m = re.match(pat, text)
                if m: return m.group(0), code, p43, text[m.end():].strip()

        for a in a21['ann']:
            full = a['title'] + ' ' + a['intro']
            if re.match(r'^(Расписание|Каждое|Каждую)', a['title']):
                skipped.append((full, 'расписание/регулярное событие без конкретной даты')); continue
            dates, r1, r2 = parse_dates(a['title'])
            if not dates and not r1:
                dates, r1, r2 = parse_dates(a['intro'])
                if dates and re.search(r'[Оо]ткрыти[ея]', a['intro']):
                    skipped.append((full, 'выставка: в анонсе только дата открытия, нет срока работы')); continue
            d1 = r1 or (dates[0] if dates else None); d2 = r2 or (dates[-1] if dates else None)
            if not d1 or not d2:
                skipped.append((full, 'нет даты')); continue
            if d2 < TODAY: continue
            title = re.sub(r'\s*\(\d+\+\)|\s+\d+\+$', '', a['title']).strip()
            rest = re.sub(date_prefix, '', title).strip()
            flags, v = [], None
            m = re.match(r'^(?:[Вв]о?|[Нн]а|[Вв]озле)\s+(.*)$', rest)
            if m:
                v = find_venue(m.group(1)); what = v[3] if v else m.group(1)
            elif find_venue(rest):
                v = find_venue(rest); what = v[3]
            else:
                what = rest
                for mm in re.finditer(r'\s(?:в|во|на)\s+', rest):
                    v2 = find_venue(rest[mm.end():])
                    if v2:
                        v = v2; what = (rest[:mm.start()] + ' ' + v2[3]).strip(); break
            if v and v[1] in official: continue
            if v and v[1] == 'qjlO9uTs' and what.startswith('«'): what = 'Концерт ' + what
            if not v: flags.append('площадка не распознана — добавьте её в config.xml')
            what, name_flag = person_title(what.strip())
            if name_flag: flags.append(name_flag)
            elif what.startswith('«'): flags.append('проверить название: в источнике нет типа события (концерт, акция…)')
            times = times_of(a['intro'])
            rng = re.search(r'[Сс]\s*(\d{1,2})[:.](\d{2})\s*до', a['intro'])
            if rng: times = [f'{int(rng.group(1))}.{rng.group(2)}']
            price, swapped = fix_price(price_of(a['intro']))
            if swapped: flags.append('цена в источнике была перевёрнута — исправлено')
            cand.append(dict(src='afisha21: анонсы', srcid='https://afisha21.ru/go/' + a['id'], dates=dates, d1=d1, d2=d2,
                             times=times, title=what, sitename=site_name(what), place=v[0] if v else '',
                             code=v[1] if v else '', p43=v[2] if v else '', price=price, tags=a['tags'], flags=flags, raw=full))

    # ---- сопоставление
    def overlaps(c, s):
        if c['dates']: return any(s['d'] <= d <= s['d2'] for d in c['dates'])
        return c['d1'] <= s['d2'] and s['d'] <= c['d2']

    def best_match(c, venue_strict=True):
        best, bs = None, 0
        for s in site:
            if not overlaps(c, s): continue
            sc = s['r']['IP_PROP17']
            if venue_strict and c['code'] and sc and sc != c['code']: continue
            v = sim(c['sitename'], s['name'])
            if v > bs: best, bs = s, v
        return (best, bs) if bs >= MATCH else (None, bs)

    for c in cand:
        c['match'], _ = best_match(c)
        c['venue_conflict'] = None
        if not c['match']:
            s, v = best_match(c, venue_strict=False)
            if s and v >= 0.9: c['venue_conflict'] = s

    structured = [c for c in cand if not c['src'].endswith('анонсы')]
    for c in cand:
        c['dup'] = c['src'].endswith('анонсы') and any(
            t['d1'] in (c['dates'] or [c['d1']]) and sim(c['title'], t['title']) >= MATCH for t in structured)

    # до какой даты источник покрывает площадку
    coverage = collections.defaultdict(lambda: dt.date(1900, 1, 1))
    for c in structured:
        if c['code']: coverage[c['code']] = max(coverage[c['code']], c['d1'])

    def site_times(s): return sorted(set(times_of(s['r']['IP_PROP28'])))

    changes, new, same, seen = [], [], 0, set()
    for c in cand:
        s = c['match']
        if c['venue_conflict']:
            s = c['venue_conflict']
            if (s['r']['IE_ID'], 'venue') not in seen:
                seen.add((s['r']['IE_ID'], 'venue'))
                sc = s['r']['IP_PROP17']
                changes.append((c, [('Площадка', vname.get(sc, sc) + f' (код {sc})', c['place'] + (f" (код {c['code']})" if c['code'] else ''))], s))
            continue
        if not s:
            if not c['dup']: new.append(c)
            continue
        if s['rec']: same += 1; continue
        notes = []
        st, ct = site_times(s), sorted(set(c['times']))
        if ct and st and ct != st: notes.append(('Время', ', '.join(st), ', '.join(ct)))
        sp_, cp = nums(s['r']['IP_PROP19']), nums(c['price'])
        if cp and sp_ and sorted(sp_) != sorted(cp): notes.append(('Цена', s['r']['IP_PROP19'], c['price']))
        if not notes: same += 1; continue
        key = (s['r']['IE_ID'], tuple(notes))
        if key in seen: continue
        seen.add(key)
        changes.append((c, notes, s))

    matched = {c['match']['r']['IE_ID'] for c in cand if c['match']} | {c['venue_conflict']['r']['IE_ID'] for c in cand if c['venue_conflict']}
    missing = []
    for s in site:
        if s['r']['IE_ID'] in matched or s['rec']: continue
        sc = s['r']['IP_PROP17']
        other = sorted((c for c in cand if sim(c['sitename'], s['name']) >= 0.85 and (not sc or not c['code'] or c['code'] == sc)),
                       key=lambda c: abs((c['d1'] - s['d']).days))
        late = sc and sc in coverage and s['d'] > coverage[sc]
        if other:
            o = other[0]
            ds = ', '.join(x.strftime('%d.%m') for x in (o['dates'] or [o['d1']]))
            reason = f"В источнике на эту дату нет; ближайший показ — {ds}: {o['raw'][:110]}"
            if late: reason += f" (источник публикует афишу этой площадки только до {coverage[sc].strftime('%d.%m')})"
        elif late:
            reason = f"Источник публикует афишу этой площадки только до {coverage[sc].strftime('%d.%m')} — перепроверить позже"
        else:
            reason = 'Не найдено в источниках — проверить вручную (возможно, отменено или источник его не публикует)'
        missing.append((s, reason))

    # ---- строки импорта для новых событий
    def prop28(c):
        t = ' и '.join(c['times'])
        if c['dates']:
            by_m = collections.OrderedDict()
            for d in c['dates']: by_m.setdefault((d.year, d.month), []).append(str(d.day))
            ds = ' и '.join((' и '.join(v) if len(v) <= 2 else ', '.join(v[:-1]) + ' и ' + v[-1]) + ' ' + MON_GEN[m] for (_, m), v in by_m.items())
        else:
            ds = f"с {c['d1'].day} {MON_GEN[c['d1'].month]} по {c['d2'].day} {MON_GEN[c['d2'].month]}"
        return (ds + (' ' + t if t else '')).strip()

    def fmt(d, t):
        if not t: return d.strftime('%d.%m.%Y')
        h, mi = t.split('.')
        return f"{d.strftime('%d.%m.%Y')} {int(h):02d}:{mi}:00"

    imp = []
    for c in new:
        t0 = c['times'][0] if c['times'] else ''
        t1 = c['times'][-1] if c['times'] else ''
        afrom = fmt(c['d1'], t0)
        ato = fmt(c['d2'], t1) if c['d2'] != c['d1'] else (fmt(c['d1'], t1) if len(c['times']) > 1 else '')
        code = slug(c['sitename'])
        if code in codes_used: code = code + str(random.Random(code + afrom).randint(1000, 9999))
        codes_used.add(code)
        flags = list(c['flags'])
        if c['p43'] and '(' not in c['p43'] and not c['code']: flags.append('добавить адрес площадки')
        if not c['price']: flags.append('цена не указана в источнике')
        if not c['times']: flags.append('время не указано в источнике')
        xml = 'a21-' + c['srcid'].rsplit('/', 1)[-1] if '/go/' in c['srcid'] else 'src-' + afrom[:10].replace('.', '') + '-' + code[:40]
        imp.append(dict(c=c, flags=flags, row={
            'IE_XML_ID': xml, 'IE_NAME': c['sitename'], 'IE_ID': '', 'IE_ACTIVE': 'Y',
            'IE_ACTIVE_FROM': afrom, 'IE_ACTIVE_TO': ato, 'IE_CODE': code, 'IP_PROP20': 'Нет',
            'IP_PROP28': prop28(c), 'IP_PROP27': '', 'IP_PROP18': '', 'IP_PROP17': c['code'],
            'IP_PROP43': ('[HTML]' + c['p43']) if (c['p43'] and not c['code']) else '', 'IP_PROP53': '', 'IP_PROP19': c['price'],
            'IP_PROP44': '', 'IP_PROP47': '', 'IP_PROP46': ''}))
    # одинаковые внешние коды у новых (одно событие из разных анонсов) — делаем уникальными
    cnt = collections.Counter(i['row']['IE_XML_ID'] for i in imp)
    for i in imp:
        if cnt[i['row']['IE_XML_ID']] > 1: i['row']['IE_XML_ID'] += '-' + i['row']['IE_CODE'][-6:]

    return dict(
        same=same, skipped=skipped, site_count=len(site), cand_count=len(cand),
        changes=[dict(id=s['r']['IE_ID'], name=s['r']['IE_NAME'], date=s['d'].strftime('%d.%m.%Y'), notes=n, src=c['srcid'], raw=c['raw'])
                 for c, n, s in changes],
        new=[dict(row=i['row'], src=i['c']['src'], url=i['c']['srcid'], raw=i['c']['raw'], tags=i['c']['tags'],
                  venue=vname.get(i['c']['code']) or i['c']['p43'] or i['c']['place'], flags=i['flags']) for i in imp],
        missing=[dict(id=s['r']['IE_ID'], name=s['name'], date=s['d'].strftime('%d.%m.%Y'), when=s['r']['IP_PROP28'],
                      venue=vname.get(s['r']['IP_PROP17']) or s['r']['IP_PROP43'].replace('[HTML]', ''), reason=r) for s, r in missing],
    )
