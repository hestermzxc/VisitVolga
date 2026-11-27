"""Отчёт Excel и CSV-файлы для импорта в Битрикс."""
import csv, re, collections, os
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

HEAD_FILL = PatternFill('solid', fgColor='305496')
WARN_FILL = PatternFill('solid', fgColor='FFF2CC')
FIELD_RU = {'IE_NAME': 'Название', 'IP_PROP17': 'Площадка (код)', 'IP_PROP19': 'Цена', 'IE_ACTIVE_FROM': 'Начало активности',
            'IE_ACTIVE_TO': 'Окончание активности', 'IP_PROP28': 'Дата/время (текст)', 'IP_PROP43': 'Где (текст)'}


def sheet(wb, title, cols, rows, widths, warn=None):
    ws = wb.create_sheet(title)
    ws.append(cols)
    for c in ws[1]:
        c.font = Font(bold=True, color='FFFFFF'); c.fill = HEAD_FILL
        c.alignment = Alignment(wrap_text=True, vertical='center')
    for r in rows: ws.append(r)
    for i, w in enumerate(widths, 1): ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row: c.alignment = Alignment(wrap_text=True, vertical='top')
        if warn and warn([c.value for c in row]):
            for c in row: c.fill = WARN_FILL
    ws.freeze_panes = 'B2'; ws.auto_filter.ref = ws.dimensions
    return ws


def build_updates(res, site, reject, force):
    """Изменения существующих элементов: правки из источников + ручные решения из config.xml."""
    by_id = collections.OrderedDict()
    for c in res['changes']: by_id.setdefault(c['id'], []).append(c)
    for eid in force:
        if eid in site and eid not in by_id:
            by_id[eid] = [dict(id=eid, name=site[eid]['IE_NAME'], date=site[eid]['IE_ACTIVE_FROM'][:10], notes=[], src='', raw='')]
    ch_rows, upd = [], []
    for eid, lst in by_id.items():
        if eid not in site: continue
        fields = collections.defaultdict(set)
        for c in lst:
            for f, old, new in c['notes']: fields[f].add(new)
        conflict = [f for f, v in fields.items() if len(v) > 1]
        forced, why = force.get(eid, ({}, ''))
        for c in lst:
            for f, old, new in c['notes']:
                if f == 'Проверка цены': dec = 'цена не меняется — проверить сеанс'
                elif (eid, f) in reject: dec = 'не применяется: ' + reject[(eid, f)]
                elif forced and (f == 'Площадка' or f in conflict or (f == 'Цена' and 'IP_PROP19' in forced)):
                    dec = 'заменено ручным решением (см. строку «проверено вручную»)'
                elif f == 'Площадка': dec = 'площадка отличается — проверить и добавить решение в config.xml'
                elif f in conflict: dec = 'источники расходятся — не применяется (добавьте решение в config.xml)'
                else: dec = 'будет обновлено'
                ch_rows.append([int(eid), c['name'], c['date'], f, old, new, dec, c['src'], c['raw']])
        for k, v in forced.items():
            ch_rows.append([int(eid), site[eid]['IE_NAME'], site[eid]['IE_ACTIVE_FROM'][:10], FIELD_RU.get(k, k), site[eid].get(k, ''), v,
                            'проверено вручную: ' + why, '', ''])
        r = dict(site[eid]); changed = False
        for f, vals in fields.items():
            if f in conflict or f in ('Площадка', 'Проверка цены') or (eid, f) in reject: continue
            new = next(iter(vals))
            if f == 'Цена':
                r['IP_PROP19'] = new; changed = True
            if f == 'Время':
                times = [t.strip() for t in new.split(',')]
                r['IP_PROP28'] = re.sub(r'\d{1,2}\.\d{2}(?:\s*и\s*\d{1,2}\.\d{2})*', ' и '.join(times), r['IP_PROP28'], count=1)
                h, m = times[0].split('.')
                r['IE_ACTIVE_FROM'] = f"{r['IE_ACTIVE_FROM'].split()[0]} {int(h):02d}:{m}:00"
                if r['IE_ACTIVE_TO']:
                    h, m = times[-1].split('.')
                    r['IE_ACTIVE_TO'] = f"{r['IE_ACTIVE_TO'].split()[0]} {int(h):02d}:{m}:00"
                changed = True
        if forced:
            r.update(forced); changed = True
        if changed: upd.append(r)
    return ch_rows, upd


def write(res, rows, header, reject, force, out_dir, sources_log):
    os.makedirs(out_dir, exist_ok=True)
    site = {r['IE_ID']: r for r in rows}
    xc = collections.Counter(r['IE_XML_ID'] for r in rows)
    dup_xml = sum(1 for r in rows if xc[r['IE_XML_ID']] > 1)

    ch_rows, upd = build_updates(res, site, reject, force)
    upd_now = [r for r in upd if xc[r['IE_XML_ID']] == 1]
    upd_fix = [dict(r, IE_XML_ID=r['IE_ID']) for r in upd if xc[r['IE_XML_ID']] > 1]
    now_ids, fix_ids = {r['IE_ID'] for r in upd_now}, {r['IE_ID'] for r in upd_fix}
    for row in ch_rows:
        eid = str(row[0])
        row.append('import_updates_now.csv' if eid in now_ids else ('import_updates_after_fix.csv' if eid in fix_ids else '—'))

    imp, new_rows = [], []
    for n in res['new']:
        r = n['row']; imp.append(r)
        cat = 'Театр' if n['tags'] == 'театр' else (n['tags'].split(',')[0].strip().capitalize() if n['tags'] else '')
        new_rows.append([r['IE_NAME'], r['IP_PROP28'], r['IE_ACTIVE_FROM'], r['IE_ACTIVE_TO'], n['venue'], r['IP_PROP17'],
                         r['IP_PROP19'], cat, '; '.join(n['flags']), r['IE_CODE'], r['IE_XML_ID'], n['src'], n['url'], n['raw']])

    wb = Workbook(); ws0 = wb.active; ws0.title = 'Сводка'
    summary = [
        ('Сверка афиши', ''),
        ('', ''),
        ('Совпадают, без изменений', res['same']),
        ('Существующие события к обновлению', f'{len(upd)} ({len(upd_now)} — сразу, {len(upd_fix)} — после fix_xml_id.php)'),
        ('Новые — есть в источниках, нет на сайте', len(new_rows)),
        ('Есть на сайте, нет в источниках', len(res['missing'])),
        ('Пропущено при разборе', len(res['skipped'])),
        ('', ''),
        ('Порядок загрузки', ''),
        ('1. import_updates_now.csv', f'{len(upd_now)} элементов с уникальным внешним кодом — можно импортировать сразу'),
        ('2. fix_xml_id.php', f'на сайте {dup_xml} элементов делят внешний код (IE_XML_ID) с другими (копии наследуют код оригинала). '
                              'Импорт ищет элементы по этому коду, поэтому сначала скрипт ставит XML_ID = ID. '
                              'После одного запуска шаг больше не нужен.' if dup_xml else 'не нужен — все внешние коды уникальны'),
        ('3. import_updates_after_fix.csv', f'{len(upd_fix)} элементов — только после шага 2'),
        ('4. import_new_events.csv', f'{len(imp)} новых событий, активны (IE_ACTIVE = Y)'),
        ('Настройка импорта', 'Контент → Инфоблоки → Импорт CSV; разделитель «;», UTF-8. '
                              '«Что делать с элементами, отсутствующими в файле» — обязательно «ничего не делать».'),
        ('', ''),
        ('Источники', ''),
    ] + [(name, info) for name, info in sources_log]
    for k, v in summary: ws0.append([k, v])
    ws0.column_dimensions['A'].width = 48; ws0.column_dimensions['B'].width = 110
    ws0['A1'].font = Font(bold=True, size=14)
    for row in ws0.iter_rows(min_row=2):
        for c in row: c.alignment = Alignment(wrap_text=True, vertical='top')
        row[0].font = Font(bold=True)

    sheet(wb, 'Изменения', ['ID на сайте', 'Событие на сайте', 'Дата', 'Что', 'Сейчас на сайте', 'Новое значение', 'Решение', 'Источник', 'Текст источника', 'Файл'],
          ch_rows, [10, 45, 11, 14, 22, 24, 42, 30, 60, 26], warn=lambda v: v[6] and not v[6].startswith('будет'))
    sheet(wb, 'Новые', ['Название (как на сайте)', 'Дата/время (текст)', 'Начало', 'Окончание', 'Площадка', 'Код площадки', 'Цена',
                        'Категория', 'Проверить', 'Символьный код', 'Внешний код', 'Источник', 'Ссылка', 'Текст источника'],
          new_rows, [45, 24, 19, 19, 34, 12, 16, 14, 40, 30, 22, 22, 30, 70], warn=lambda v: v[8])
    sheet(wb, 'Нет в источниках', ['ID на сайте', 'Событие', 'Дата', 'Дата/время на сайте', 'Площадка', 'Комментарий'],
          [[int(m['id']), m['name'], m['date'], m['when'], m['venue'], m['reason']] for m in res['missing']], [10, 50, 11, 22, 34, 90])
    sheet(wb, 'Пропущено', ['Текст анонса', 'Почему пропущено'], [list(x) for x in res['skipped']], [110, 50])

    xlsx = os.path.join(out_dir, 'afisha_sverka.xlsx')
    try:
        wb.save(xlsx)
    except PermissionError:  # файл открыт в Excel
        xlsx = os.path.join(out_dir, f'afisha_sverka_{os.getpid()}.xlsx'); wb.save(xlsx)

    def write_csv(name, data):
        with open(os.path.join(out_dir, name), 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=header, delimiter=';', lineterminator='\n', extrasaction='ignore')
            w.writeheader(); w.writerows(data)
    write_csv('import_updates_now.csv', upd_now)
    write_csv('import_updates_after_fix.csv', upd_fix)
    write_csv('import_new_events.csv', imp)
    return dict(xlsx=xlsx, updates_now=len(upd_now), updates_fix=len(upd_fix), new=len(imp), missing=len(res['missing']),
                same=res['same'], skipped=len(res['skipped']), dup_xml=dup_xml)
