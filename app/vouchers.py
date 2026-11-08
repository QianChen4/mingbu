"""
记账凭证：保存（含校验）、读取、列表、删除、审核、整理凭证号；以及科目、辅助项、期初、模板的维护。
"""
import json

from .db import AppError, log, now_str, get_meta, company_profile, set_meta
from .ledger import (account_map, check_open, closed_periods, period_of_date, plabel, start_period,
                     level_of, parent_of)
from . import presets


def to_cents(v):
    """把前端传来的金额（分，整数）做一次校验。"""
    if v in (None, ''):
        return 0
    if isinstance(v, bool):
        raise AppError('金额格式不正确')
    if isinstance(v, float):
        if abs(v - round(v)) > 1e-6:
            raise AppError('金额格式不正确')
        v = int(round(v))
    if not isinstance(v, int):
        try:
            v = int(v)
        except Exception:
            raise AppError('金额格式不正确：%s' % v)
    if abs(v) > 10 ** 15:
        raise AppError('金额过大')
    return v


def aux_map(conn):
    return {r['id']: dict(r) for r in conn.execute('SELECT * FROM aux_items')}


def validate_lines(conn, lines, kind='普通'):
    accts = account_map(conn)
    auxes = aux_map(conn)
    cf_codes = {r[0] for r in conn.execute('SELECT code FROM cf_items')}
    clean = []
    for i, ln in enumerate(lines, 1):
        code = (ln.get('account') or '').strip()
        debit = to_cents(ln.get('debit'))
        credit = to_cents(ln.get('credit'))
        summary = (ln.get('summary') or '').strip()
        if not code and not debit and not credit:
            continue  # 空行跳过
        tag = '第 %d 行' % i
        if not code:
            raise AppError(tag + '没有选择会计科目')
        a = accts.get(code)
        if not a:
            raise AppError(tag + '科目 %s 不存在' % code)
        if not a['is_leaf']:
            raise AppError(tag + '科目 %s %s 不是末级科目，请选择它的下级科目' % (code, a['name']))
        if not a['enabled']:
            raise AppError(tag + '科目 %s %s 已停用' % (code, a['name']))
        if debit and credit:
            raise AppError(tag + '借方和贷方不能同时有金额')
        if not debit and not credit:
            raise AppError(tag + '没有填写金额')
        if not summary:
            raise AppError(tag + '没有填写摘要')
        aux_id = int(ln.get('aux_id') or 0)
        if a['aux_type']:
            if aux_id:
                ai = auxes.get(aux_id)
                if not ai or ai['type'] != a['aux_type']:
                    raise AppError(tag + '辅助核算项目不正确，应选择“%s”' % a['aux_type'])
            elif a['aux_required']:
                raise AppError(tag + '科目 %s %s 必须选择“%s”' % (code, a['name'], a['aux_type']))
        else:
            aux_id = 0
        cf = (ln.get('cf_item') or '').strip()
        if not a['is_cash']:
            cf = ''
        elif cf and cf not in cf_codes:
            raise AppError(tag + '现金流量项目不正确')
        clean.append({'summary': summary, 'account': code, 'aux_id': aux_id,
                      'debit': debit, 'credit': credit, 'cf_item': cf, 'is_cash': a['is_cash']})
    if len(clean) < 2:
        raise AppError('凭证至少需要两行分录')
    td = sum(x['debit'] for x in clean)
    tc = sum(x['credit'] for x in clean)
    if td != tc:
        raise AppError('借贷不平衡：借方合计 %.2f，贷方合计 %.2f，相差 %.2f' % (td / 100, tc / 100, (td - tc) / 100))
    has_non_cash = any(not x['is_cash'] for x in clean)
    for i, x in enumerate(clean, 1):
        if x['is_cash'] and has_non_cash and not x['cf_item'] and kind == '普通':
            raise AppError('第 %d 行是现金类科目，请选择现金流量项目' % i)
        if x['is_cash'] and not has_non_cash and not x['cf_item']:
            x['cf_item'] = 'CF99'
    return clean


def suggest_cf_item(cash_is_debit, counterpart_code, suggest):
    """根据对方科目建议现金流量项目（取最长匹配前缀）。suggest 为账套的 {编码前缀: [收, 付]}。"""
    best = ''
    for pre in suggest:
        if counterpart_code.startswith(pre) and len(pre) > len(best):
            best = pre
    pair = suggest.get(best) or ['CF03', 'CF07']
    return pair[0] if cash_is_debit else pair[1]


def fill_cf_suggestions(conn, lines):
    """给没有填写现金流量项目的现金类分录自动补上建议值（用于导入）。"""
    accts = account_map(conn)
    suggest = company_profile(conn)['cf_suggest']
    is_cash = lambda ln: accts.get(ln.get('account'), {}).get('is_cash')
    others = [ln for ln in lines if ln.get('account') in accts and not is_cash(ln)]
    if not others:
        return lines
    for ln in lines:
        if is_cash(ln) and not ln.get('cf_item'):
            debit_side = bool(to_cents(ln.get('debit')))
            opp = [o for o in others if bool(to_cents(o.get('credit'))) == debit_side] or others
            opp.sort(key=lambda o: -abs(to_cents(o.get('debit')) or to_cents(o.get('credit'))))
            ln['cf_item'] = suggest_cf_item(debit_side, opp[0]['account'], suggest)
    return lines


def next_number(conn, period):
    r = conn.execute('SELECT COALESCE(MAX(number), 0) FROM vouchers WHERE period = ?', (period,)).fetchone()
    return r[0] + 1


def save_voucher(conn, data, kind=None):
    """新增或修改凭证。data: {id?, date, attachments, lines:[...]}。返回凭证 id。"""
    vid = data.get('id')
    date = (data.get('date') or '').strip()
    period = period_of_date(date)
    check_open(conn, period)
    old = None
    if vid:
        old = conn.execute('SELECT * FROM vouchers WHERE id = ?', (vid,)).fetchone()
        if not old:
            raise AppError('凭证不存在')
        check_open(conn, old['period'])
        if old['audited']:
            raise AppError('凭证已审核，请先取消审核再修改')
        if old['kind'] != '普通':
            raise AppError('“%s”凭证由系统生成，不能修改；如有错误请删除后重新生成' % old['kind'])
        kind = old['kind']
    kind = kind or '普通'
    lines = validate_lines(conn, data.get('lines') or [], kind)
    attachments = int(data.get('attachments') or 0)
    maker = (data.get('maker') or get_meta(conn).get('maker') or '').strip()
    ts = now_str()
    if old:
        number = old['number'] if old['period'] == period else next_number(conn, period)
        conn.execute('UPDATE vouchers SET period=?, number=?, date=?, attachments=?, updated_at=? WHERE id=?',
                     (period, number, date, attachments, ts, vid))
        conn.execute('DELETE FROM lines WHERE voucher_id = ?', (vid,))
        log(conn, '修改凭证', '%s 记-%04d' % (plabel(period), number))
    else:
        number = next_number(conn, period)
        cur = conn.execute('INSERT INTO vouchers(period, number, date, attachments, kind, maker, created_at, updated_at)'
                           ' VALUES (?,?,?,?,?,?,?,?)', (period, number, date, attachments, kind, maker, ts, ts))
        vid = cur.lastrowid
        log(conn, '新增凭证', '%s 记-%04d' % (plabel(period), number))
    for seq, ln in enumerate(lines, 1):
        conn.execute('INSERT INTO lines(voucher_id, period, seq, summary, account_code, aux_id, debit, credit, cf_item)'
                     ' VALUES (?,?,?,?,?,?,?,?,?)',
                     (vid, period, seq, ln['summary'], ln['account'], ln['aux_id'], ln['debit'], ln['credit'],
                      ln['cf_item']))
    return vid


def get_voucher(conn, vid):
    v = conn.execute('SELECT * FROM vouchers WHERE id = ?', (vid,)).fetchone()
    if not v:
        raise AppError('凭证不存在')
    v = dict(v)
    v['lines'] = [dict(r) for r in conn.execute('SELECT * FROM lines WHERE voucher_id = ? ORDER BY seq', (vid,))]
    v['closed'] = v['period'] in closed_periods(conn)
    # 前后凭证，方便翻页
    prev = conn.execute('SELECT id FROM vouchers WHERE (period < ?) OR (period = ? AND number < ?) '
                        'ORDER BY period DESC, number DESC LIMIT 1', (v['period'], v['period'], v['number'])).fetchone()
    nxt = conn.execute('SELECT id FROM vouchers WHERE (period > ?) OR (period = ? AND number > ?) '
                       'ORDER BY period, number LIMIT 1', (v['period'], v['period'], v['number'])).fetchone()
    v['prev_id'] = prev[0] if prev else None
    v['next_id'] = nxt[0] if nxt else None
    return v


def list_vouchers(conn, pf, pt, keyword='', account='', status=''):
    q = ('SELECT v.*, (SELECT SUM(debit) FROM lines WHERE voucher_id = v.id) AS total, '
         '(SELECT summary FROM lines WHERE voucher_id = v.id ORDER BY seq LIMIT 1) AS first_summary, '
         '(SELECT COUNT(*) FROM lines WHERE voucher_id = v.id) AS line_count '
         'FROM vouchers v WHERE v.period BETWEEN ? AND ?')
    params = [int(pf), int(pt)]
    if keyword:
        q += ' AND EXISTS (SELECT 1 FROM lines WHERE voucher_id = v.id AND summary LIKE ?)'
        params.append('%' + keyword + '%')
    if account:
        q += ' AND EXISTS (SELECT 1 FROM lines WHERE voucher_id = v.id AND account_code LIKE ?)'
        params.append(account + '%')
    if status == 'unaudited':
        q += ' AND v.audited = 0'
    elif status == 'audited':
        q += ' AND v.audited = 1'
    q += ' ORDER BY v.period, v.number'
    return [dict(r) for r in conn.execute(q, params)]


def vouchers_with_lines(conn, ids):
    return [get_voucher(conn, int(i)) for i in ids]


def delete_voucher(conn, vid):
    v = conn.execute('SELECT * FROM vouchers WHERE id = ?', (vid,)).fetchone()
    if not v:
        raise AppError('凭证不存在')
    check_open(conn, v['period'])
    if v['audited']:
        raise AppError('凭证已审核，请先取消审核再删除')
    conn.execute('DELETE FROM lines WHERE voucher_id = ?', (vid,))
    conn.execute('DELETE FROM vouchers WHERE id = ?', (vid,))
    conn.execute('DELETE FROM depr_records WHERE voucher_id = ?', (vid,))
    log(conn, '删除凭证', '%s 记-%04d（%s）' % (plabel(v['period']), v['number'], v['kind']))


def audit_vouchers(conn, ids, flag, auditor=''):
    n = 0
    for vid in ids:
        v = conn.execute('SELECT * FROM vouchers WHERE id = ?', (int(vid),)).fetchone()
        if not v:
            continue
        check_open(conn, v['period'])
        conn.execute('UPDATE vouchers SET audited = ?, auditor = ? WHERE id = ?',
                     (1 if flag else 0, auditor if flag else '', v['id']))
        n += 1
    log(conn, '审核凭证' if flag else '取消审核', '%d 张' % n)
    return n


def renumber(conn, period):
    """整理凭证号：按日期重新从 1 开始连续编号。"""
    check_open(conn, period)
    rows = conn.execute('SELECT id FROM vouchers WHERE period = ? ORDER BY date, number', (period,)).fetchall()
    conn.execute('UPDATE vouchers SET number = -number WHERE period = ?', (period,))
    for i, r in enumerate(rows, 1):
        conn.execute('UPDATE vouchers SET number = ? WHERE id = ?', (i, r['id']))
    log(conn, '整理凭证号', plabel(period))
    return len(rows)


# ---------------------------------------------------------------- 会计科目维护


def account_used(conn, code):
    a = conn.execute('SELECT COUNT(*) FROM lines WHERE account_code = ?', (code,)).fetchone()[0]
    b = conn.execute('SELECT COUNT(*) FROM opening WHERE account_code = ? AND (year_begin != 0 OR ytd_debit != 0 OR '
                     'ytd_credit != 0)', (code,)).fetchone()[0]
    return a + b > 0


def save_account(conn, data, is_new):
    code = (data.get('code') or '').strip()
    name = (data.get('name') or '').strip()
    if not code.isdigit() or len(code) not in (4, 6, 8, 10):
        raise AppError('科目编码必须是 4、6、8 或 10 位数字（4-2-2-2 结构）')
    if not name:
        raise AppError('请填写科目名称')
    aux_type = data.get('aux_type') or ''
    if aux_type and aux_type not in company_profile(conn)['aux_types']:
        raise AppError('辅助核算类型不正确')
    exists = conn.execute('SELECT * FROM accounts WHERE code = ?', (code,)).fetchone()
    if is_new:
        if exists:
            raise AppError('科目编码 %s 已存在' % code)
        parent = parent_of(code)
        if parent:
            p = conn.execute('SELECT * FROM accounts WHERE code = ?', (parent,)).fetchone()
            if not p:
                raise AppError('上级科目 %s 不存在，请先建立上级科目' % parent)
            category, direction = p['category'], data.get('direction') or p['direction']
            is_cash = p['is_cash']
        else:
            category = data.get('category')
            direction = data.get('direction')
            is_cash = 1 if data.get('is_cash') else 0
            if category not in ('资产', '负债', '权益', '损益'):
                raise AppError('请选择科目类别')
        if direction not in ('借', '贷'):
            raise AppError('请选择余额方向')
        conn.execute('INSERT INTO accounts(code, name, category, direction, aux_type, aux_required, is_cash, enabled,'
                     ' report_line) VALUES (?,?,?,?,?,?,?,1,?)',
                     (code, name, category, direction, aux_type, 1 if data.get('aux_required') else 0, is_cash,
                      (data.get('report_line') or '') if not parent else ''))
        # 上级科目原来是末级且已经使用过：把数据自动转到这个新建的下级科目
        if parent:
            siblings = conn.execute('SELECT COUNT(*) FROM accounts WHERE code LIKE ? AND code != ?',
                                    (parent + '%', parent)).fetchone()[0]
            if siblings == 1 and account_used(conn, parent):
                if closed_periods(conn):
                    pass  # 已有结账期间也允许迁移，历史数字合计不变
                conn.execute('UPDATE lines SET account_code = ? WHERE account_code = ?', (code, parent))
                conn.execute('UPDATE opening SET account_code = ? WHERE account_code = ?', (code, parent))
                p = conn.execute('SELECT * FROM accounts WHERE code = ?', (parent,)).fetchone()
                conn.execute('UPDATE accounts SET aux_type = ?, aux_required = ? WHERE code = ?',
                             (p['aux_type'], p['aux_required'], code))
        log(conn, '新增科目', code + ' ' + name)
    else:
        if not exists:
            raise AppError('科目不存在')
        if aux_type != exists['aux_type'] and account_used(conn, code):
            used_aux = conn.execute('SELECT COUNT(*) FROM lines WHERE account_code = ? AND aux_id != 0',
                                    (code,)).fetchone()[0]
            if used_aux:
                raise AppError('该科目已经按“%s”记过账，不能修改辅助核算类型' % exists['aux_type'])
        direction = data.get('direction') or exists['direction']
        conn.execute('UPDATE accounts SET name=?, direction=?, aux_type=?, aux_required=?, enabled=? WHERE code=?',
                     (name, direction, aux_type, 1 if data.get('aux_required') else 0,
                      0 if data.get('enabled') in (0, False, '0') else 1, code))
        if level_of(code) == 1:
            if 'is_cash' in data:
                conn.execute('UPDATE accounts SET is_cash = ? WHERE code LIKE ?',
                             (1 if data.get('is_cash') else 0, code + '%'))
            if 'report_line' in data:
                conn.execute('UPDATE accounts SET report_line = ? WHERE code = ?', (data.get('report_line') or '', code))
        log(conn, '修改科目', code + ' ' + name)


def delete_account(conn, code):
    if conn.execute('SELECT COUNT(*) FROM accounts WHERE code LIKE ? AND code != ?', (code + '%', code)).fetchone()[0]:
        raise AppError('该科目有下级科目，请先删除下级科目')
    if account_used(conn, code) or conn.execute('SELECT COUNT(*) FROM lines WHERE account_code = ?', (code,)).fetchone()[0]:
        raise AppError('该科目已有凭证或期初数据，不能删除，可以改为“停用”')
    conn.execute('DELETE FROM accounts WHERE code = ?', (code,))
    conn.execute('DELETE FROM opening WHERE account_code = ?', (code,))
    log(conn, '删除科目', code)


# ---------------------------------------------------------------- 辅助核算项目


def save_aux(conn, data):
    t = data.get('type')
    code = (data.get('code') or '').strip()
    name = (data.get('name') or '').strip()
    if t not in company_profile(conn)['aux_types']:
        raise AppError('辅助核算类型不正确')
    if t == '车辆' and not data.get('_from_vehicle'):
        raise AppError('车辆请在“车辆台账”中维护')
    if not code or not name:
        raise AppError('请填写编码和名称')
    aid = data.get('id')
    dup = conn.execute('SELECT id FROM aux_items WHERE type = ? AND code = ? AND id != ?', (t, code, aid or 0)).fetchone()
    if dup:
        raise AppError('%s编码 %s 已存在' % (t, code))
    enabled = 0 if data.get('enabled') in (0, False, '0') else 1
    if aid:
        conn.execute('UPDATE aux_items SET code=?, name=?, enabled=? WHERE id=?', (code, name, enabled, aid))
        return int(aid)
    cur = conn.execute('INSERT INTO aux_items(type, code, name, enabled) VALUES (?,?,?,?)', (t, code, name, enabled))
    return cur.lastrowid


def delete_aux(conn, aid):
    used = conn.execute('SELECT COUNT(*) FROM lines WHERE aux_id = ?', (aid,)).fetchone()[0]
    used += conn.execute('SELECT COUNT(*) FROM opening WHERE aux_id = ?', (aid,)).fetchone()[0]
    if used:
        raise AppError('该项目已经在凭证或期初中使用，不能删除，可以改为停用')
    r = conn.execute('SELECT type FROM aux_items WHERE id = ?', (aid,)).fetchone()
    if r and r['type'] == '车辆':
        raise AppError('车辆请在“车辆台账”中删除')
    conn.execute('DELETE FROM aux_items WHERE id = ?', (aid,))


def add_aux_type(conn, name):
    """新增一种辅助核算类型（如“部门”“项目”“门店”）。"""
    name = (name or '').strip()
    if not name or len(name) > 10:
        raise AppError('请填写辅助核算类型名称（不超过 10 个字）')
    types = company_profile(conn)['aux_types']
    if name in types:
        raise AppError('已经有“%s”这个类型了' % name)
    types.append(name)
    set_meta(conn, 'aux_types', json.dumps(types, ensure_ascii=False))
    log(conn, '新增辅助核算类型', name)


def delete_aux_type(conn, name):
    if name in ('客户', '供应商', '员工', '银行账户', '车辆'):
        raise AppError('系统内置的辅助核算类型不能删除')
    if conn.execute('SELECT COUNT(*) FROM accounts WHERE aux_type = ?', (name,)).fetchone()[0]:
        raise AppError('有会计科目在使用“%s”辅助核算，不能删除' % name)
    if conn.execute('SELECT COUNT(*) FROM aux_items WHERE type = ?', (name,)).fetchone()[0]:
        raise AppError('“%s”下面还有项目，请先删除这些项目' % name)
    types = [t for t in company_profile(conn)['aux_types'] if t != name]
    set_meta(conn, 'aux_types', json.dumps(types, ensure_ascii=False))


# ---------------------------------------------------------------- 期初余额


def get_opening(conn):
    return [dict(r) for r in conn.execute('SELECT * FROM opening')]


def save_opening(conn, rows):
    if closed_periods(conn):
        raise AppError('已经有结账的期间，不能再修改期初余额')
    accts = account_map(conn)
    conn.execute('DELETE FROM opening')
    for r in rows:
        code = r.get('account_code')
        a = accts.get(code)
        if not a:
            raise AppError('科目 %s 不存在' % code)
        if not a['is_leaf']:
            raise AppError('期初余额只能录入到末级科目：%s' % code)
        yb, yd, yc = to_cents(r.get('year_begin')), to_cents(r.get('ytd_debit')), to_cents(r.get('ytd_credit'))
        if not (yb or yd or yc):
            continue
        aux = int(r.get('aux_id') or 0)
        if aux and not a['aux_type']:
            aux = 0
        conn.execute('INSERT OR REPLACE INTO opening(account_code, aux_id, year_begin, ytd_debit, ytd_credit) '
                     'VALUES (?,?,?,?,?)', (code, aux, yb, yd, yc))
    log(conn, '保存期初余额', '%d 行' % len(rows))


def opening_check(conn):
    """期初试算平衡：启用时点的余额借贷必须相等；年初余额也必须平衡。"""
    accts = account_map(conn)
    total_start = 0
    total_begin = 0
    for r in conn.execute('SELECT * FROM opening'):
        a = accts.get(r['account_code'])
        if not a:
            continue
        total_begin += r['year_begin']
        if a['category'] != '损益':
            total_start += r['year_begin'] + r['ytd_debit'] - r['ytd_credit']
    return {'year_begin_diff': total_begin, 'start_diff': total_start,
            'balanced': total_begin == 0 and total_start == 0}


# ---------------------------------------------------------------- 凭证模板


def list_templates(conn):
    out = []
    for r in conn.execute('SELECT * FROM templates ORDER BY sort, id'):
        d = dict(r)
        d['lines'] = json.loads(d.pop('lines_json'))
        out.append(d)
    return out


def save_template(conn, data):
    name = (data.get('name') or '').strip()
    if not name:
        raise AppError('请填写模板名称')
    lines = []
    for ln in data.get('lines') or []:
        if not ln.get('account'):
            continue
        lines.append({'summary': ln.get('summary', ''), 'account': ln['account'], 'dir': ln.get('dir', '借'),
                      'expr': ln.get('expr', ''), 'aux_id': int(ln.get('aux_id') or 0)})
    if len(lines) < 2:
        raise AppError('模板至少要有两行')
    js = json.dumps(lines, ensure_ascii=False)
    if data.get('id'):
        conn.execute('UPDATE templates SET name = ?, lines_json = ? WHERE id = ?', (name, js, data['id']))
    else:
        mx = conn.execute('SELECT COALESCE(MAX(sort), 0) FROM templates').fetchone()[0]
        conn.execute('INSERT INTO templates(name, lines_json, sort) VALUES (?,?,?)', (name, js, mx + 1))


def delete_template(conn, tid):
    conn.execute('DELETE FROM templates WHERE id = ?', (tid,))
