"""
导入导出：
- 从 Excel 另存的 CSV 文件导入凭证、车辆、客户/供应商等；
- 把任意表格导出成 .xlsx（不依赖第三方库）。
"""
import csv
import datetime
import io
import re
import zipfile
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape

from .db import AppError
from . import vouchers as V
from . import vehicles as VH

# ---------------------------------------------------------------- CSV 读取


def decode_csv(raw: bytes):
    for enc in ('utf-8-sig', 'gb18030'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise AppError('无法识别文件编码，请在 Excel 中“另存为 → CSV UTF-8”')
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise AppError('文件中没有数据')
    header = [h.strip() for h in rows[0]]
    return header, [[c.strip() for c in r] + [''] * (len(header) - len(r)) for r in rows[1:]]


def parse_money(s):
    s = (s or '').replace(',', '').replace('，', '').replace('¥', '').strip()
    if not s:
        return 0
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise AppError('金额格式不正确：%s' % s)
    return int((d * 100).quantize(Decimal('1'), rounding='ROUND_HALF_UP'))


def parse_date(s):
    s = (s or '').strip()
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y%m%d', '%Y.%m.%d', '%Y年%m月%d日'):
        try:
            return datetime.datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    raise AppError('日期格式不正确：%s（应为 2026-01-05 这样的格式）' % s)


def _col(header, *names):
    for n in names:
        if n in header:
            return header.index(n)
    return None


VOUCHER_COLUMNS = ['日期', '凭证号', '摘要', '科目编码', '辅助核算编码', '借方金额', '贷方金额', '现金流量项目编码', '附件数']
VEHICLE_COLUMNS = ['车牌号', '车型', '购置日期', '原值', '残值率%', '折旧月数', '期初累计折旧', '备注']
AUX_COLUMNS = ['类型', '编码', '名称']


def template_csv(kind):
    samples = {
        'vouchers': (VOUCHER_COLUMNS, [
            ['2026-01-05', '1', '收到租金', '1002', '01', '1130.00', '', 'CF01', '1'],
            ['2026-01-05', '1', '收到租金', '600101', '', '', '1000.00', '', ''],
            ['2026-01-05', '1', '收到租金', '22210102', '', '', '130.00', '', ''],
        ]),
        'vehicles': (VEHICLE_COLUMNS, [
            ['粤A12345', '大众朗逸', '2025-06-10', '98000.00', '5', '48', '0', ''],
        ]),
        'aux': (AUX_COLUMNS, [
            ['客户', 'C001', '某某科技有限公司'],
            ['供应商', 'S001', '某某汽车销售服务有限公司'],
            ['员工', 'E001', '张三'],
        ]),
    }
    header, rows = samples[kind]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return ('﻿' + buf.getvalue()).encode('utf-8')


def import_vouchers(conn, raw):
    header, rows = decode_csv(raw)
    idx = {n: _col(header, n) for n in VOUCHER_COLUMNS}
    for need in ('日期', '凭证号', '摘要', '科目编码', '借方金额', '贷方金额'):
        if idx[need] is None:
            raise AppError('缺少列“%s”。请下载导入模板对照格式。' % need)
    aux_by_code = {}
    accts = {r['code']: r for r in conn.execute('SELECT code, aux_type FROM accounts')}
    for r in conn.execute('SELECT id, type, code FROM aux_items'):
        aux_by_code[(r['type'], r['code'])] = r['id']

    def g(row, name):
        i = idx[name]
        return row[i] if i is not None and i < len(row) else ''

    groups = {}
    order = []
    errors = []
    for n, row in enumerate(rows, 2):
        try:
            date = parse_date(g(row, '日期'))
            key = (date[:7], g(row, '凭证号'))
            code = g(row, '科目编码')
            aux_code = g(row, '辅助核算编码')
            aux_id = 0
            if aux_code:
                a = accts.get(code)
                if not a or not a['aux_type']:
                    raise AppError('科目 %s 没有设置辅助核算，但填写了辅助核算编码' % code)
                aux_id = aux_by_code.get((a['aux_type'], aux_code))
                if not aux_id:
                    raise AppError('找不到%s“%s”，请先在辅助核算中建立' % (a['aux_type'], aux_code))
            line = {'summary': g(row, '摘要'), 'account': code, 'aux_id': aux_id,
                    'debit': parse_money(g(row, '借方金额')), 'credit': parse_money(g(row, '贷方金额')),
                    'cf_item': g(row, '现金流量项目编码')}
        except AppError as e:
            errors.append('第 %d 行：%s' % (n, e))
            continue
        if key not in groups:
            groups[key] = {'date': date, 'attachments': int(g(row, '附件数') or 0) if g(row, '附件数').isdigit() else 0,
                           'lines': [], 'first_row': n}
            order.append(key)
        groups[key]['lines'].append(line)
    if errors:
        raise AppError('导入失败，没有导入任何数据：\n' + '\n'.join(errors[:30]))
    saved = 0
    for key in order:
        grp = groups[key]
        try:
            V.fill_cf_suggestions(conn, grp['lines'])
            V.save_voucher(conn, {'date': grp['date'], 'attachments': grp['attachments'], 'lines': grp['lines']})
            saved += 1
        except AppError as e:
            errors.append('凭证 %s 号（文件第 %d 行起）：%s' % (key[1], grp['first_row'], e))
    if errors:
        raise AppError('导入失败，没有导入任何数据：\n' + '\n'.join(errors[:30]))
    return {'count': saved}


def import_vehicles(conn, raw):
    header, rows = decode_csv(raw)
    idx = {n: _col(header, n, n.replace('%', '')) for n in VEHICLE_COLUMNS}
    for need in ('车牌号', '购置日期', '原值'):
        if idx[need] is None:
            raise AppError('缺少列“%s”' % need)

    def g(row, name):
        i = idx[name]
        return row[i] if i is not None and i < len(row) else ''

    errors, n_ok = [], 0
    existing = {r[0]: r[1] for r in conn.execute('SELECT plate, id FROM vehicles')}
    for n, row in enumerate(rows, 2):
        try:
            plate = g(row, '车牌号').upper()
            data = {'id': existing.get(plate), 'plate': plate, 'model': g(row, '车型'),
                    'purchase_date': parse_date(g(row, '购置日期')), 'original': parse_money(g(row, '原值')),
                    'salvage_rate': g(row, '残值率%') or 5, 'life_months': g(row, '折旧月数') or 48,
                    'opening_accum': parse_money(g(row, '期初累计折旧')), 'note': g(row, '备注')}
            VH.save_vehicle(conn, data)
            n_ok += 1
        except AppError as e:
            errors.append('第 %d 行：%s' % (n, e))
    if errors:
        raise AppError('导入失败，没有导入任何数据：\n' + '\n'.join(errors[:30]))
    return {'count': n_ok}


def import_aux(conn, raw):
    header, rows = decode_csv(raw)
    idx = {n: _col(header, n) for n in AUX_COLUMNS}
    if None in idx.values():
        raise AppError('需要“类型、编码、名称”三列')
    errors, n_ok = [], 0
    for n, row in enumerate(rows, 2):
        t, code, name = row[idx['类型']], row[idx['编码']], row[idx['名称']]
        try:
            ex = conn.execute('SELECT id FROM aux_items WHERE type = ? AND code = ?', (t, code)).fetchone()
            V.save_aux(conn, {'id': ex[0] if ex else None, 'type': t, 'code': code, 'name': name})
            n_ok += 1
        except AppError as e:
            errors.append('第 %d 行：%s' % (n, e))
    if errors:
        raise AppError('导入失败，没有导入任何数据：\n' + '\n'.join(errors[:30]))
    return {'count': n_ok}


# ---------------------------------------------------------------- xlsx 导出


def _col_letter(i):
    s = ''
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def build_xlsx(title, columns, rows, subtitle=''):
    """
    columns: [{'name': '科目编码', 'type': 'text' | 'money' | 'number', 'width': 12}]
    rows: [[...], ...]，money 列的值以“分”为单位；也可以是 {'cells': [...], 'bold': True}
    """
    def cell(ref, value, style=0, ctype='text'):
        if value is None or value == '':
            return '<c r="%s" s="%d"/>' % (ref, style)
        if ctype in ('money', 'number') and isinstance(value, (int, float)):
            v = value / 100 if ctype == 'money' else value
            return '<c r="%s" s="%d"><v>%s</v></c>' % (ref, style, repr(v) if isinstance(v, float) else v)
        return '<c r="%s" s="%d" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (
            ref, style, escape(str(value)))

    out_rows = []
    r = 1
    ncol = len(columns)
    out_rows.append('<row r="1">%s</row>' % cell('A1', title, 3))
    r = 2
    if subtitle:
        out_rows.append('<row r="2">%s</row>' % cell('A2', subtitle, 0))
        r = 3
    out_rows.append('<row r="%d">%s</row>' % (r, ''.join(
        cell('%s%d' % (_col_letter(i), r), c['name'], 1) for i, c in enumerate(columns))))
    header_row = r
    for row in rows:
        r += 1
        bold = False
        if isinstance(row, dict):
            bold = row.get('bold', False)
            row = row['cells']
        cells = []
        for i, c in enumerate(columns):
            v = row[i] if i < len(row) else ''
            t = c.get('type', 'text')
            style = (4 if bold else 2) if t == 'money' else (5 if bold else 0)
            cells.append(cell('%s%d' % (_col_letter(i), r), v, style, t))
        out_rows.append('<row r="%d">%s</row>' % (r, ''.join(cells)))
    cols_xml = ''.join('<col min="%d" max="%d" width="%d" customWidth="1"/>' % (
        i + 1, i + 1, c.get('width') or (16 if c.get('type') == 'money' else 14)) for i, c in enumerate(columns))
    merge = '<mergeCells count="1"><mergeCell ref="A1:%s1"/></mergeCells>' % _col_letter(max(ncol - 1, 0))
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetViews><sheetView workbookViewId="0"><pane ySplit="%d" topLeftCell="A%d" activePane="bottomLeft" '
             'state="frozen"/></sheetView></sheetViews>'
             '<cols>%s</cols><sheetData>%s</sheetData>%s</worksheet>') % (
        header_row, header_row + 1, cols_xml, ''.join(out_rows), merge)
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00;-#,##0.00;&quot;&quot;"/></numFmts>'
              '<fonts count="3"><font><sz val="11"/><name val="等线"/></font>'
              '<font><b/><sz val="11"/><name val="等线"/></font>'
              '<font><b/><sz val="14"/><name val="等线"/></font></fonts>'
              '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FFEFF2F5"/></patternFill></fill></fills>'
              '<borders count="2"><border/><border><left style="thin"><color rgb="FFC8CDD3"/></left>'
              '<right style="thin"><color rgb="FFC8CDD3"/></right><top style="thin"><color rgb="FFC8CDD3"/></top>'
              '<bottom style="thin"><color rgb="FFC8CDD3"/></bottom></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="6">'
              '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"/>'
              '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center"/></xf>'
              '<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>'
              '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment horizontal="center"/></xf>'
              '<xf numFmtId="164" fontId="1" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyBorder="1"/>'
              '<xf numFmtId="0" fontId="1" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1"/>'
              '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    sheet_name = escape(re.sub(r'[\\/*?:\[\]]', '', title)[:31] or 'Sheet1')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   '</Types>')
        z.writestr('_rels/.rels',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        z.writestr('xl/workbook.xml',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   '<sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets></workbook>' % sheet_name)
        z.writestr('xl/_rels/workbook.xml.rels',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                   '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   '</Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', sheet)
        z.writestr('xl/styles.xml', styles)
    return buf.getvalue()
