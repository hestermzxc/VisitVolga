"""Сверка афиши сайта с сайтами-источниками.

Запуск:  python afisha_sync.py [config.xml]
Все настройки (ссылки на сайты с афишей, путь к выгрузке, площадки, ручные решения) — в config.xml.
"""
import csv, os, re, sys, shutil, datetime as dt
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parsers, compare, report
from theatre_sources import THEATRE_PARSERS

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def log(msg):
    print(msg, flush=True)


def load_config(path):
    root = ET.parse(path).getroot()
    base = os.path.dirname(os.path.abspath(path))
    rel = lambda p: os.path.normpath(os.path.join(base, p.strip()))
    cfg = dict(export=rel(root.findtext('export')), output=rel(root.findtext('output') or 'sverka'),
               sources=[], venues=[], theatres={}, vname={}, reject={}, force={})
    for s in root.iter('source'):
        url = (s.get('url') or '').strip()
        if not url or s.get('enabled', 'true').lower() == 'false': continue
        cfg['sources'].append(dict(url=url, type=s.get('type') or parsers.detect_type(url), months=int(s.get('months', 4)),
                                   name=s.get('name') or url, code=s.get('venue', ''), place=s.get('place', ''),
                                   official=s.get('official', 'false').lower() == 'true', kind=s.get('kind', 'Спектакль')))
    for v in root.iter('venue'):
        code, place, name = v.get('code', ''), v.get('place', ''), v.get('name', '')
        if code and name: cfg['vname'][code] = name
        for p in v.findall('pattern'):
            cfg['venues'].append((p.text.strip(), code, '' if code else place))
        for t in v.findall('theatre'):
            cfg['theatres'][t.text.strip()] = (code, '' if code else place)
    for r in root.iter('reject'):
        cfg['reject'][(r.get('id'), r.get('field'))] = (r.text or '').strip()
    for f in root.iter('force'):
        cfg['force'][f.get('id')] = ({x.get('name'): (x.text or '').strip() for x in f.findall('field')}, f.get('reason', ''))
    return cfg


def main():
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.xml')
    cfg = load_config(cfg_path)
    today = dt.date.today()
    log(f'Конфиг: {cfg_path}\nВыгрузка сайта: {cfg["export"]}')
    with open(cfg['export'], encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, delimiter=';')
        rows, header = list(reader), reader.fieldnames

    a21, generic, sources_log = None, [], []
    for s in cfg['sources']:
        log(f'\n[{s["type"]}] {s["url"]}')
        try:
            if s['type'] == 'afisha21':
                a21 = parsers.parse_afisha21(s['url'], s['months'], today, log)
                info = f"анонсов {len(a21['ann'])}, театральных показов {len(a21['theatre'])}"
            else:
                fn = (parsers.parse_rusdram if s['type'] == 'rusdram21'
                      else THEATRE_PARSERS.get(s['type'], parsers.parse_jsonld))
                ev = fn(s['url'], today, log)
                if not ev:
                    info = ('событий не найдено — вероятно, афиша подгружается скриптом/виджетом (например, Radario) '
                            'или для этого сайта нужен отдельный парсер')
                    log('  ! ' + info)
                else:
                    generic.append(dict(s, events=ev))
                    last = max(e['d'] for e in ev)
                    info = f"событий {len(ev)}, до {last.strftime('%d.%m.%Y')}" + (' (официальный — приоритет для совпавших показов)' if s['official'] else '')
                    priced_sessions = [e for e in ev if e.get('session_priced')]
                    if priced_sessions:
                        confirmed = sum(bool(e['price']) for e in priced_sessions)
                        info += f'; цены получены для {confirmed} из {len(priced_sessions)} сеансов'
        except Exception as e:
            info = f'ошибка: {e}'
            log('  ! ' + info)
        sources_log.append((s['name'], info))

    log('\nСверка...')
    res = compare.run(rows, a21, generic, cfg['venues'], cfg['theatres'], cfg['vname'], today)
    out_dir = os.path.join(cfg['output'], f'sverka_{today.isoformat()}')
    summary = report.write(res, rows, header, cfg['reject'], cfg['force'], out_dir, sources_log)
    if summary['dup_xml']:
        shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fix_xml_id.php'), out_dir)

    log(f"\nГотово: {out_dir}\n"
        f"  совпадают без изменений: {summary['same']}\n"
        f"  обновить сейчас:         {summary['updates_now']}  (import_updates_now.csv)\n"
        f"  обновить после fix:      {summary['updates_fix']}  (import_updates_after_fix.csv)\n"
        f"  новые события:           {summary['new']}  (import_new_events.csv)\n"
        f"  нет в источниках:        {summary['missing']}\n"
        f"  отчёт:                   {summary['xlsx']}")


if __name__ == '__main__':
    main()
