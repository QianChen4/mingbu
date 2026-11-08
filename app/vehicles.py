"""
车辆台账：车辆卡片、月折旧额计算、购车/处置凭证草稿、与账面核对。

折旧规则（平均年限法）：
- 月折旧额 = 原值 ×（1 − 残值率）÷ 折旧月数，四舍五入到分；
- 当月购入的车辆，下月开始计提；当月处置的车辆，当月照提、下月停止；
- 累计折旧达到“原值 − 残值”后停止计提，最后一个月自动补足尾差。
"""
from .db import AppError, log, acct_key, company_profile
from .ledger import (account_map, check_open, current_period, leaf_end_balances, period_of_date, plabel,
                     start_period, last_day)
from .vouchers import to_cents


def monthly_amount(v):
    return round(v['original'] * (10000 - v['salvage_bp']) / 10000 / max(v['life_months'], 1))


def depreciable_limit(v):
    return v['original'] - round(v['original'] * v['salvage_bp'] / 10000)


def recorded_accum(conn, vid, through=None):
    q = 'SELECT COALESCE(SUM(amount), 0) FROM depr_records WHERE vehicle_id = ?'
    args = [vid]
    if through:
        q += ' AND period <= ?'
        args.append(through)
    return conn.execute(q, args).fetchone()[0]


def plan_depreciation(conn, p):
    """计算 p 期每辆车应计提的折旧。返回 [(vehicle_dict, amount)]。"""
    sp = start_period(conn)
    if p < sp:
        return []
    acc_before = {r[0]: r[1] for r in conn.execute(
        'SELECT vehicle_id, SUM(amount) FROM depr_records WHERE period < ? GROUP BY vehicle_id', (p,))}
    plan = []
    for r in conn.execute('SELECT * FROM vehicles ORDER BY plate'):
        v = dict(r)
        if period_of_date(v['purchase_date']) >= p:
            continue
        if v['status'] != '在用' and v['dispose_period'] != p:
            continue
        accum = v['opening_accum'] + acc_before.get(v['id'], 0)
        remain = depreciable_limit(v) - accum
        if remain <= 0:
            continue
        amt = min(monthly_amount(v), remain)
        if amt > 0:
            plan.append((v, amt))
    return plan


def list_vehicles(conn):
    cur = current_period(conn)
    acc = {r[0]: r[1] for r in conn.execute('SELECT vehicle_id, SUM(amount) FROM depr_records GROUP BY vehicle_id')}
    out = []
    for r in conn.execute('SELECT * FROM vehicles ORDER BY plate'):
        v = dict(r)
        v['monthly'] = monthly_amount(v)
        v['accum'] = v['opening_accum'] + acc.get(v['id'], 0)
        v['net'] = v['original'] - v['accum']
        v['fully'] = v['accum'] >= depreciable_limit(v)
        out.append(v)
    return {'vehicles': out, 'current_period': cur}


def save_vehicle(conn, data):
    plate = (data.get('plate') or '').strip().upper()
    if not plate:
        raise AppError('请填写车牌号')
    model = (data.get('model') or '').strip()
    pdate = (data.get('purchase_date') or '').strip()
    period_of_date(pdate)
    original = to_cents(data.get('original'))
    if original <= 0:
        raise AppError('请填写车辆原值（不含税购置成本）')
    try:
        salvage_bp = int(round(float(data.get('salvage_rate', 5)) * 100))
        life = int(data.get('life_months') or 48)
    except Exception:
        raise AppError('残值率或折旧月数格式不正确')
    if not (0 <= salvage_bp < 10000) or life <= 0:
        raise AppError('残值率应在 0~100% 之间，折旧月数应大于 0')
    opening_accum = to_cents(data.get('opening_accum'))
    if opening_accum < 0 or opening_accum > original:
        raise AppError('期初累计折旧不正确')
    note = (data.get('note') or '').strip()
    vid = data.get('id')
    dup = conn.execute('SELECT id FROM vehicles WHERE plate = ? AND id != ?', (plate, vid or 0)).fetchone()
    if dup:
        raise AppError('车牌号 %s 已存在' % plate)
    if vid:
        old = conn.execute('SELECT * FROM vehicles WHERE id = ?', (vid,)).fetchone()
        if not old:
            raise AppError('车辆不存在')
        conn.execute('UPDATE vehicles SET plate=?, model=?, purchase_date=?, original=?, salvage_bp=?, life_months=?, '
                     'opening_accum=?, note=? WHERE id=?',
                     (plate, model, pdate, original, salvage_bp, life, opening_accum, note, vid))
        conn.execute('UPDATE aux_items SET code=?, name=? WHERE id=?', (plate, model or plate, old['aux_id']))
        return int(vid)
    dup_aux = conn.execute("SELECT id FROM aux_items WHERE type='车辆' AND code=?", (plate,)).fetchone()
    if dup_aux:
        aux_id = dup_aux[0]
    else:
        aux_id = conn.execute("INSERT INTO aux_items(type, code, name) VALUES ('车辆', ?, ?)",
                              (plate, model or plate)).lastrowid
    cur = conn.execute('INSERT INTO vehicles(aux_id, plate, model, purchase_date, original, salvage_bp, life_months, '
                       'opening_accum, note) VALUES (?,?,?,?,?,?,?,?,?)',
                       (aux_id, plate, model, pdate, original, salvage_bp, life, opening_accum, note))
    return cur.lastrowid


def delete_vehicle(conn, vid):
    v = conn.execute('SELECT * FROM vehicles WHERE id = ?', (vid,)).fetchone()
    if not v:
        raise AppError('车辆不存在')
    if conn.execute('SELECT COUNT(*) FROM depr_records WHERE vehicle_id = ?', (vid,)).fetchone()[0]:
        raise AppError('该车辆已经计提过折旧，不能删除；如车辆已卖出或报废，请使用“处置”')
    used = conn.execute('SELECT COUNT(*) FROM lines WHERE aux_id = ?', (v['aux_id'],)).fetchone()[0]
    used += conn.execute('SELECT COUNT(*) FROM opening WHERE aux_id = ?', (v['aux_id'],)).fetchone()[0]
    if used:
        raise AppError('该车辆已在凭证或期初余额中使用，不能删除')
    conn.execute('DELETE FROM vehicles WHERE id = ?', (vid,))
    conn.execute('DELETE FROM aux_items WHERE id = ?', (v['aux_id'],))
    log(conn, '删除车辆', v['plate'])


def purchase_draft(conn, vid, tax_rate=13):
    v = conn.execute('SELECT * FROM vehicles WHERE id = ?', (vid,)).fetchone()
    if not v:
        raise AppError('车辆不存在')
    tax = round(v['original'] * tax_rate / 100)
    s = '购入车辆 %s %s' % (v['plate'], v['model'])
    fa_code = acct_key(conn, 'vehicle_fa')
    notes = ['已按 %g%% 进项税生成购车凭证草稿，请选择供应商（或把贷方改为银行存款）后保存。' % tax_rate]
    p = period_of_date(v['purchase_date'])
    if p < start_period(conn):
        notes.append('注意：这辆车的购置日期早于账套启用期间，属于启用前已有的车辆，'
                     '一般不用再录购车凭证，而是在“期初余额”中点“从车辆台账带入”。')
    booked = conn.execute('SELECT COUNT(*), COALESCE(SUM(l.debit - l.credit), 0) FROM lines l '
                          'WHERE l.account_code = ? AND l.aux_id = ?', (fa_code, v['aux_id'])).fetchone()
    if booked[0]:
        notes.append('注意：账上已经有这辆车的固定资产记录（%.2f 元），请先到“凭证查询”确认是否已录过购车凭证，避免重复入账。'
                     % (booked[1] / 100))
    return {'date': v['purchase_date'], 'note': ''.join(notes), 'lines': [
        {'summary': s, 'account': acct_key(conn, 'vehicle_fa'), 'aux_id': v['aux_id'], 'debit': v['original'], 'credit': 0},
        {'summary': s, 'account': acct_key(conn, 'vat_in'), 'aux_id': 0, 'debit': tax, 'credit': 0},
        {'summary': s, 'account': acct_key(conn, 'ap'), 'aux_id': 0, 'debit': 0, 'credit': v['original'] + tax},
    ]}


def dispose(conn, data):
    """把车辆标记为已处置，并返回处置凭证草稿（在凭证界面确认后保存）。"""
    vid = int(data.get('id'))
    v = conn.execute('SELECT * FROM vehicles WHERE id = ?', (vid,)).fetchone()
    if not v:
        raise AppError('车辆不存在')
    if v['status'] != '在用':
        raise AppError('该车辆已经处置过了')
    date = data.get('date') or ''
    p = period_of_date(date)
    check_open(conn, p)
    if period_of_date(v['purchase_date']) > p:
        raise AppError('处置日期早于购置日期')
    price = to_cents(data.get('price'))
    cash_acct = data.get('cash_account') or acct_key(conn, 'bank')
    cash_aux = int(data.get('cash_aux') or 0)
    vat_mode = data.get('vat_mode') or '简易3%减按2%'
    accts = account_map(conn)
    if cash_acct not in accts or not accts[cash_acct]['is_leaf']:
        raise AppError('收款科目不正确')

    # 处置当月照提折旧：如果本月还没有计提，先把本月应提的金额算进去
    accum = v['opening_accum'] + recorded_accum(conn, vid, p)
    done_this_month = conn.execute('SELECT COUNT(*) FROM depr_records WHERE period = ?', (p,)).fetchone()[0] > 0
    if not done_this_month:
        conn.execute('UPDATE vehicles SET status = ?, dispose_period = ? WHERE id = ?', ('已处置', p, vid))
        for pv, amt in plan_depreciation(conn, p):
            if pv['id'] == vid:
                accum += amt
    net = v['original'] - accum

    if vat_mode == '13%':
        tax = price - round(price * 100 / 113)
        tax_acct = acct_key(conn, 'vat_out')
    elif vat_mode == '不计税':
        tax, tax_acct = 0, ''
    else:  # 小规模/简易计税：3% 征收率减按 2%
        tax = round(price / 1.03 * 0.02)
        tax_acct = acct_key(conn, 'vat_simple')
    gain = price - tax - net
    gain_acct, loss_acct = acct_key(conn, 'disposal_gain'), acct_key(conn, 'disposal_loss')

    def aux_of(code):  # 处置损益科目设了“车辆”辅助核算时，记到这辆车上
        return v['aux_id'] if accts.get(code, {}).get('aux_type') == '车辆' else 0
    s = '处置车辆 %s %s' % (v['plate'], v['model'])
    lines = []
    if price:
        lines.append({'summary': s, 'account': cash_acct, 'aux_id': cash_aux, 'debit': price, 'credit': 0,
                      'cf_item': 'CF13'})
    if accum:
        depr_code = acct_key(conn, 'vehicle_depr')
        lines.append({'summary': s, 'account': depr_code, 'aux_id': aux_of(depr_code), 'debit': accum, 'credit': 0})
    if gain < 0:
        lines.append({'summary': s + ' 处置损失', 'account': loss_acct, 'aux_id': aux_of(loss_acct), 'debit': -gain, 'credit': 0})
    lines.append({'summary': s, 'account': acct_key(conn, 'vehicle_fa'), 'aux_id': v['aux_id'], 'debit': 0, 'credit': v['original']})
    if tax:
        lines.append({'summary': s + ' 增值税', 'account': tax_acct, 'aux_id': 0, 'debit': 0, 'credit': tax})
    if gain > 0:
        lines.append({'summary': s + ' 处置收益', 'account': gain_acct, 'aux_id': aux_of(gain_acct), 'debit': 0, 'credit': gain})

    conn.execute('UPDATE vehicles SET status = ?, dispose_period = ? WHERE id = ?', ('已处置', p, vid))
    log(conn, '处置车辆', '%s %s' % (v['plate'], plabel(p)))
    return {'date': date, 'lines': lines,
            'note': '本凭证已按处置当月照提折旧计算累计折旧 %.2f 元。请核对后保存。' % (accum / 100)}


def undo_dispose(conn, vid):
    v = conn.execute('SELECT * FROM vehicles WHERE id = ?', (vid,)).fetchone()
    if not v or v['status'] == '在用':
        raise AppError('该车辆不是已处置状态')
    check_open(conn, v['dispose_period'])
    later = conn.execute('SELECT COUNT(*) FROM depr_records WHERE vehicle_id = ? AND period > ?',
                         (vid, v['dispose_period'])).fetchone()[0]
    if later:
        raise AppError('数据异常：处置后仍有折旧记录')
    conn.execute("UPDATE vehicles SET status = '在用', dispose_period = NULL WHERE id = ?", (vid,))
    log(conn, '撤销处置', v['plate'])


def reconcile(conn, p=None):
    """车辆台账与账面核对（截至 p 期末）。"""
    p = p or current_period(conn)
    bal = leaf_end_balances(conn, p)
    rows = []
    total_orig = total_accum = 0
    fa_code, depr_code = acct_key(conn, 'vehicle_fa', False), acct_key(conn, 'vehicle_depr', False)
    if not fa_code or not depr_code:  # 本账套的行业没有车辆功能
        return {'period': p, 'card_original': 0, 'book_original': 0, 'card_accum': 0, 'book_accum': 0, 'mismatches': []}
    book_orig = sum(v for (c, a), v in bal.items() if c == fa_code)
    book_accum = -sum(v for (c, a), v in bal.items() if c == depr_code)
    for r in conn.execute('SELECT * FROM vehicles ORDER BY plate'):
        v = dict(r)
        in_use = v['status'] == '在用' or (v['dispose_period'] and v['dispose_period'] > p)
        if period_of_date(v['purchase_date']) > p:
            in_use = False
        accum = v['opening_accum'] + recorded_accum(conn, v['id'], p)
        if in_use:
            total_orig += v['original']
            total_accum += accum
        book = bal.get((fa_code, v['aux_id']), 0)
        expect = v['original'] if in_use else 0
        if book != expect:
            if not in_use and period_of_date(v['purchase_date']) > p:
                reason = ('台账上的购置日期是 %s，晚于 %s，所以台账还没把它算进来，但账上已经有这辆车；'
                          '如果购置日期填错了，请点“修改”改正' % (v['purchase_date'], plabel(p)))
            elif book == 0:
                reason = '账上还没有这辆车的原值，可能还没录购车凭证（或期初余额没有带入）'
            else:
                reason = '台账原值 %.2f，账上 %.2f' % (expect / 100, book / 100)
            rows.append({'plate': v['plate'], 'card': expect, 'book': book, 'diff': book - expect, 'reason': reason})
    return {'period': p, 'card_original': total_orig, 'book_original': book_orig,
            'card_accum': total_accum, 'book_accum': book_accum, 'mismatches': rows}


def vehicle_profit(conn, pf, pt):
    """单车盈利：按车辆汇总收入、折旧和其他直接成本（不含结转损益凭证）。"""
    pf, pt = int(pf), int(pt)
    rows = {}
    names = {r['aux_id']: dict(r) for r in conn.execute('SELECT * FROM vehicles')}

    def get(aux):
        if aux not in rows:
            v = names.get(aux)
            rows[aux] = {'aux_id': aux, 'plate': v['plate'] if v else '（未归属到具体车辆）',
                         'model': v['model'] if v else '', 'status': v['status'] if v else '',
                         'revenue': 0, 'depr': 0, 'insurance': 0, 'repair': 0, 'other': 0}
        return rows[aux]

    km = company_profile(conn)['keymap']
    rev_pre = [km[k] for k in ('main_rev', 'other_rev') if km.get(k)]
    cost_pre = [km[k] for k in ('main_cost',) if km.get(k)]
    depr_code, ins_code, rep_code = km.get('depr_exp', '-'), km.get('veh_ins', '-'), km.get('veh_repair', '-')
    pres = rev_pre + cost_pre
    if pres:
        q = ('SELECT l.account_code, l.aux_id, SUM(l.credit - l.debit) AS amt FROM lines l '
             'JOIN vouchers v ON v.id = l.voucher_id WHERE v.kind != ? AND l.period BETWEEN ? AND ? AND ('
             + ' OR '.join(['l.account_code LIKE ?'] * len(pres)) + ') GROUP BY l.account_code, l.aux_id')
        for r in conn.execute(q, ['结转损益', pf, pt] + [p + '%' for p in pres]):
            code, aux, amt = r['account_code'], r['aux_id'], r['amt']
            if code.startswith(depr_code):
                continue  # 折旧从折旧明细取，按车辆分摊
            valid_aux = aux if aux in names else 0
            d = get(valid_aux)
            if any(code.startswith(p) for p in rev_pre):
                d['revenue'] += amt
            elif code.startswith(ins_code):
                d['insurance'] -= amt
            elif code.startswith(rep_code):
                d['repair'] -= amt
            else:
                d['other'] -= amt
    for r in conn.execute('SELECT v.aux_id, SUM(d.amount) FROM depr_records d JOIN vehicles v ON v.id = d.vehicle_id '
                          'WHERE d.period BETWEEN ? AND ? GROUP BY v.aux_id', (pf, pt)):
        get(r[0])['depr'] += r[1]
    out = []
    for d in rows.values():
        d['cost'] = d['depr'] + d['insurance'] + d['repair'] + d['other']
        d['profit'] = d['revenue'] - d['cost']
        if any(d[k] for k in ('revenue', 'cost')):
            out.append(d)
    out.sort(key=lambda d: (d['aux_id'] == 0, -d['profit']))
    total = {k: sum(d[k] for d in out) for k in ('revenue', 'depr', 'insurance', 'repair', 'other', 'cost', 'profit')}
    return {'from': pf, 'to': pt, 'rows': out, 'total': total}
