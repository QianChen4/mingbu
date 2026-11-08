"""
账簿计算：会计期间、科目、科目余额表、总账、明细账、辅助核算余额表。

约定：
- 期间用整数 YYYYMM 表示，如 202602。
- 金额单位为“分”，余额借方为正、贷方为负。
- 只有末级科目可以记账；上级科目的数字由下级汇总得到。
"""
from .db import AppError, get_meta

# ---------------------------------------------------------------- 期间


def next_period(p):
    y, m = divmod(p, 100)
    return (y + 1) * 100 + 1 if m == 12 else p + 1


def prev_period(p):
    y, m = divmod(p, 100)
    return (y - 1) * 100 + 12 if m == 1 else p - 1


def period_of_date(date_str):
    try:
        y, m, d = (int(x) for x in date_str.split('-'))
        assert 1 <= m <= 12 and 1 <= d <= 31
    except Exception:
        raise AppError('日期格式不正确：%s' % date_str)
    return y * 100 + m


def last_day(p):
    import calendar
    y, m = divmod(p, 100)
    return '%04d-%02d-%02d' % (y, m, calendar.monthrange(y, m)[1])


def plabel(p):
    return '%d年%d月' % divmod(p, 100)


def start_period(conn):
    return int(get_meta(conn)['start_period'])


def closed_periods(conn):
    return {r[0] for r in conn.execute('SELECT period FROM closed_periods')}


def current_period(conn):
    """当前会计期间 = 第一个未结账的期间。"""
    p = start_period(conn)
    closed = closed_periods(conn)
    while p in closed:
        p = next_period(p)
    return p


def check_open(conn, p):
    if p < start_period(conn):
        raise AppError('%s 早于账套启用期间 %s' % (plabel(p), plabel(start_period(conn))))
    if p in closed_periods(conn):
        raise AppError('%s 已结账，不能修改。如需修改请先反结账。' % plabel(p))


def check_period(p):
    p = int(p)
    if not (190001 <= p <= 299912 and 1 <= p % 100 <= 12):
        raise AppError('期间不正确：%s' % p)
    return p


def normalize_range(conn, pf, pt):
    """查询区间：可以跨年度（如 2026年9月 至 2027年2月），但起始期间不能晚于结束期间。"""
    pf, pt = check_period(pf), check_period(pt)
    if pf > pt:
        raise AppError('起始期间（%s）不能晚于结束期间（%s）' % (plabel(pf), plabel(pt)))
    sp = start_period(conn)
    if pt < sp:
        raise AppError('查询期间早于账套启用期间 %s' % plabel(sp))
    return max(pf, sp), pt


def range_label(pf, pt):
    return plabel(pf) if pf == pt else '%s 至 %s' % (plabel(pf), plabel(pt))


# ---------------------------------------------------------------- 科目


def level_of(code):
    return 1 if len(code) <= 4 else (len(code) - 4) // 2 + 1


def parent_of(code):
    return code[:-2] if len(code) > 4 else ''


def load_accounts(conn):
    """返回按编码排序的科目列表，并补充 level / parent / is_leaf / full_name。"""
    rows = [dict(r) for r in conn.execute('SELECT * FROM accounts ORDER BY code')]
    by_code = {r['code']: r for r in rows}
    codes = set(by_code)
    for r in rows:
        r['level'] = level_of(r['code'])
        r['parent'] = parent_of(r['code'])
        r['is_leaf'] = not any(c != r['code'] and c.startswith(r['code']) for c in codes)
    for r in rows:
        names, c = [], r['code']
        while c:
            if c in by_code:
                names.append(by_code[c]['name'])
            c = parent_of(c)
        r['full_name'] = '—'.join(reversed(names))
    return rows


def account_map(conn):
    return {a['code']: a for a in load_accounts(conn)}


# ---------------------------------------------------------------- 余额核心


def _z():
    return {'begin': 0, 'pd': 0, 'pc': 0, 'yd': 0, 'yc': 0, 'end': 0}


def opening_rows(conn, accts):
    """读取期初数据，并计算启用期间开始时的余额。"""
    out = []
    for r in conn.execute('SELECT * FROM opening'):
        a = accts.get(r['account_code'])
        if not a:
            continue
        is_bs = a['category'] != '损益'
        at_start = r['year_begin'] + ((r['ytd_debit'] - r['ytd_credit']) if is_bs else 0)
        out.append({'code': r['account_code'], 'aux': r['aux_id'], 'year_begin': r['year_begin'],
                    'ytd_debit': r['ytd_debit'], 'ytd_credit': r['ytd_credit'],
                    'at_start': at_start, 'is_bs': is_bs})
    return out


def leaf_balances(conn, pf, pt, accts=None):
    """
    计算 [pf, pt] 区间内每个（末级科目, 辅助项）的：
    期初 begin、本期借 pd、本期贷 pc、本年累计借 yd、本年累计贷 yc、期末 end。
    """
    pf, pt = normalize_range(conn, pf, pt)
    accts = accts or account_map(conn)
    sp = start_period(conn)
    year = pt // 100
    y1 = year * 100 + 1
    res = {}

    def get(k):
        if k not in res:
            res[k] = _z()
        return res[k]

    for o in opening_rows(conn, accts):
        d = get((o['code'], o['aux']))
        d['begin'] += o['at_start']
        # 启用年度的本年累计包含启用前的累计发生额（损益类也一样，与利润表的本年累计口径一致）
        if year == sp // 100:
            d['yd'] += o['ytd_debit']
            d['yc'] += o['ytd_credit']

    sql = '''
        SELECT account_code, aux_id,
          SUM(CASE WHEN period < :pf THEN debit - credit ELSE 0 END) AS pre,
          SUM(CASE WHEN period >= :pf THEN debit ELSE 0 END) AS pd,
          SUM(CASE WHEN period >= :pf THEN credit ELSE 0 END) AS pc,
          SUM(CASE WHEN period >= :y1 THEN debit ELSE 0 END) AS yd,
          SUM(CASE WHEN period >= :y1 THEN credit ELSE 0 END) AS yc
        FROM lines WHERE period <= :pt
        GROUP BY account_code, aux_id'''
    for r in conn.execute(sql, {'pf': pf, 'pt': pt, 'y1': y1}):
        d = get((r['account_code'], r['aux_id']))
        d['begin'] += r['pre']
        d['pd'] += r['pd']
        d['pc'] += r['pc']
        d['yd'] += r['yd']
        d['yc'] += r['yc']
    for d in res.values():
        d['end'] = d['begin'] + d['pd'] - d['pc']
    return res


def leaf_end_balances(conn, p):
    """截至 p 期末每个（末级科目, 辅助项）的余额。"""
    sp = start_period(conn)
    accts = account_map(conn)
    res = {}
    for o in opening_rows(conn, accts):
        k = (o['code'], o['aux'])
        res[k] = res.get(k, 0) + o['at_start']
    if p >= sp:
        for r in conn.execute('SELECT account_code, aux_id, SUM(debit - credit) FROM lines WHERE period <= ? '
                              'GROUP BY account_code, aux_id', (p,)):
            k = (r[0], r[1])
            res[k] = res.get(k, 0) + r[2]
    return res


def leaf_year_begin_balances(conn, year):
    """某年度年初（1 月初）的余额。"""
    sp = start_period(conn)
    accts = account_map(conn)
    if year == sp // 100:
        res = {}
        for o in opening_rows(conn, accts):
            k = (o['code'], o['aux'])
            res[k] = res.get(k, 0) + o['year_begin']
        return res
    if year < sp // 100:
        return {}
    return leaf_end_balances(conn, (year - 1) * 100 + 12)


def leaf_begin_balances(conn, p):
    """p 期开始时（即上期末）每个（末级科目, 辅助项）的余额。"""
    sp = start_period(conn)
    sy = sp // 100
    if p <= sy * 100 + 1:
        return leaf_year_begin_balances(conn, sy)
    if p <= sp:
        accts = account_map(conn)
        res = {}
        for o in opening_rows(conn, accts):
            k = (o['code'], o['aux'])
            res[k] = res.get(k, 0) + o['at_start']
        return res
    return leaf_end_balances(conn, prev_period(p))


def rollup(accts, leaf):
    """把末级数据汇总到各级科目。leaf 的值可以是 dict（余额表）或整数。"""
    numeric = leaf and isinstance(next(iter(leaf.values())), int)
    out = {}
    for (code, _aux), d in leaf.items():
        c = code
        while c:
            if c in accts:
                if numeric:
                    out[c] = out.get(c, 0) + d
                else:
                    t = out.setdefault(c, _z())
                    for k in t:
                        t[k] += d[k]
            c = parent_of(c)
    return out


def split(v):
    """把带符号余额拆成（借方, 贷方）两列显示。"""
    return (v, 0) if v >= 0 else (0, -v)


def direction_text(v):
    return '平' if v == 0 else ('借' if v > 0 else '贷')


# ---------------------------------------------------------------- 科目余额表


def balance_table(conn, pf, pt, level=9, with_aux=False, show_zero=False):
    pf, pt = normalize_range(conn, pf, pt)
    accts = account_map(conn)
    leaf = leaf_balances(conn, pf, pt, accts)
    agg = rollup(accts, leaf)
    aux_names = aux_name_map(conn)

    def mk(code, name, d, lvl, aux=0, is_aux=False):
        bd, bc = split(d['begin'])
        ed, ec = split(d['end'])
        return {'code': code, 'name': name, 'level': lvl, 'aux_id': aux, 'is_aux': is_aux,
                'begin_d': bd, 'begin_c': bc, 'pd': d['pd'], 'pc': d['pc'],
                'yd': d['yd'], 'yc': d['yc'], 'end_d': ed, 'end_c': ec}

    def nonzero(d):
        return any(d[k] for k in ('begin', 'pd', 'pc', 'yd', 'yc', 'end'))

    rows = []
    totals = {k: 0 for k in ('begin_d', 'begin_c', 'pd', 'pc', 'yd', 'yc', 'end_d', 'end_c')}
    for a in sorted(accts.values(), key=lambda x: x['code']):
        d = agg.get(a['code'], _z())
        if a['level'] == 1:
            r1 = mk(a['code'], a['name'], d, 1)
            for k in totals:
                totals[k] += r1[k]
        if a['level'] > level:
            continue
        if not show_zero and not nonzero(d):
            continue
        rows.append(mk(a['code'], a['name'], d, a['level']))
        if with_aux and a['is_leaf'] and a['aux_type']:
            items = [(k[1], v) for k, v in leaf.items() if k[0] == a['code']]
            items.sort(key=lambda x: aux_names.get(x[0], {}).get('code', ''))
            for aux, v in items:
                if not show_zero and not nonzero(v):
                    continue
                info = aux_names.get(aux)
                label = ('%s %s' % (info['code'], info['name'])) if info else '（未指定）'
                rows.append(mk(a['code'], label, v, a['level'] + 1, aux, True))
    balanced = (totals['begin_d'] == totals['begin_c'] and totals['pd'] == totals['pc']
                and totals['end_d'] == totals['end_c'])
    return {'from': pf, 'to': pt, 'rows': rows, 'totals': totals, 'balanced': balanced}


def aux_name_map(conn):
    return {r['id']: dict(r) for r in conn.execute('SELECT id, type, code, name FROM aux_items')}


# ---------------------------------------------------------------- 总账


def _opening_for(conn, accts, code, aux=None):
    """科目（含下级）在启用时点的余额，以及启用前本年累计借贷（损益类为启用前实际发生额）。"""
    at_start = ytd_d = ytd_c = 0
    for o in opening_rows(conn, accts):
        if o['code'].startswith(code) and (aux is None or o['aux'] == aux):
            at_start += o['at_start']
            ytd_d += o['ytd_debit']
            ytd_c += o['ytd_credit']
    return at_start, ytd_d, ytd_c


def general_ledger(conn, code, pf, pt):
    """总账：每月一行“本月合计”、一行“本年累计”。区间可以跨年度，跨年时本年累计从 1 月重新累计。"""
    pf, pt = normalize_range(conn, pf, pt)
    accts = account_map(conn)
    if code not in accts:
        raise AppError('科目不存在：%s' % code)
    sp = start_period(conn)
    sy = sp // 100
    first = max((pf // 100) * 100 + 1, sp)  # 从起始年度的 1 月（或启用月）开始累计
    like = code + '%'
    at_start, open_yd, open_yc = _opening_for(conn, accts, code)
    bal = at_start + conn.execute('SELECT COALESCE(SUM(debit - credit), 0) FROM lines WHERE account_code LIKE ? '
                                  'AND period < ?', (like, first)).fetchone()[0]
    monthly = {row[0]: (row[1], row[2]) for row in conn.execute(
        'SELECT period, SUM(debit), SUM(credit) FROM lines WHERE account_code LIKE ? AND period BETWEEN ? AND ? '
        'GROUP BY period', (like, first, pt))}
    rows = []
    ytd_d = ytd_c = 0
    p = first
    while p <= pt:
        if p == first or p % 100 == 1:
            ytd_d, ytd_c = (open_yd, open_yc) if p // 100 == sy else (0, 0)
        if p == pf:
            label = '年初余额' if p % 100 == 1 else ('期初余额（账套启用）' if p == sp else '期初余额')
            rows.append({'type': 'begin', 'period': p, 'summary': label, 'debit': 0, 'credit': 0,
                         'dir': direction_text(bal), 'balance': abs(bal)})
        elif p > pf and p % 100 == 1:
            rows.append({'type': 'begin', 'period': p, 'summary': '上年结转', 'debit': 0, 'credit': 0,
                         'dir': direction_text(bal), 'balance': abs(bal)})
        d, c = monthly.get(p, (0, 0))
        bal += d - c
        ytd_d += d
        ytd_c += c
        if p >= pf:
            rows.append({'type': 'month', 'period': p, 'summary': '本月合计', 'debit': d, 'credit': c,
                         'dir': direction_text(bal), 'balance': abs(bal)})
            rows.append({'type': 'ytd', 'period': p, 'summary': '本年累计', 'debit': ytd_d, 'credit': ytd_c,
                         'dir': direction_text(bal), 'balance': abs(bal)})
        p = next_period(p)
    return {'account': accts[code], 'from': pf, 'to': pt, 'rows': rows}


# ---------------------------------------------------------------- 明细账


def detail_ledger(conn, code, pf, pt, aux_id=None):
    """明细账：逐笔列示并滚动计算余额；每月末有“本月合计”“本年累计”，跨年时本年累计重新开始。"""
    pf, pt = normalize_range(conn, pf, pt)
    accts = account_map(conn)
    if code not in accts:
        raise AppError('科目不存在：%s' % code)
    sp = start_period(conn)
    sy = sp // 100
    like = code + '%'
    aux_cond, params_aux = '', []
    aux = None
    if aux_id not in (None, '', 'all'):
        aux = int(aux_id)
        aux_cond, params_aux = ' AND aux_id = ?', [aux]

    at_start, open_yd, open_yc = _opening_for(conn, accts, code, aux)
    begin = at_start + conn.execute('SELECT COALESCE(SUM(debit - credit), 0) FROM lines WHERE account_code LIKE ? '
                                    'AND period < ?' + aux_cond, [like, pf] + params_aux).fetchone()[0]
    # 起始月份所在年度，1 月（或启用月）到起始月之前的累计发生额
    y1 = max((pf // 100) * 100 + 1, sp)
    pre = conn.execute('SELECT COALESCE(SUM(debit),0), COALESCE(SUM(credit),0) FROM lines '
                       'WHERE account_code LIKE ? AND period >= ? AND period < ?' + aux_cond,
                       [like, y1, pf] + params_aux).fetchone()
    ytd_d, ytd_c = (open_yd, open_yc) if pf // 100 == sy else (0, 0)
    ytd_d += pre[0]
    ytd_c += pre[1]

    aux_names = aux_name_map(conn)
    q = ('SELECT l.*, v.number, v.date, v.id AS vid FROM lines l JOIN vouchers v ON v.id = l.voucher_id '
         'WHERE l.account_code LIKE ? AND l.period BETWEEN ? AND ?' + aux_cond.replace('aux_id', 'l.aux_id') +
         ' ORDER BY l.period, v.date, v.number, l.seq')
    items = conn.execute(q, [like, pf, pt] + params_aux).fetchall()

    label = '年初余额' if pf % 100 == 1 else ('期初余额（账套启用）' if pf == sp else '期初余额')
    rows = [{'type': 'begin', 'date': '', 'voucher': '', 'summary': label, 'debit': 0, 'credit': 0,
             'dir': direction_text(begin), 'balance': abs(begin)}]
    bal = begin
    by_period = {}
    for it in items:
        by_period.setdefault(it['period'], []).append(it)
    p = pf
    while p <= pt:
        if p != pf and p % 100 == 1:
            ytd_d = ytd_c = 0
            rows.append({'type': 'begin', 'date': '', 'voucher': '', 'summary': '上年结转', 'debit': 0, 'credit': 0,
                         'dir': direction_text(bal), 'balance': abs(bal)})
        md = mc = 0
        for it in by_period.get(p, []):
            bal += it['debit'] - it['credit']
            md += it['debit']
            mc += it['credit']
            ai = aux_names.get(it['aux_id'])
            acc = accts.get(it['account_code'])
            rows.append({'type': 'line', 'date': it['date'], 'voucher': '记-%04d' % it['number'],
                         'voucher_id': it['vid'], 'summary': it['summary'],
                         'account': it['account_code'] + ' ' + (acc['full_name'] if acc else ''),
                         'aux': ('%s %s' % (ai['code'], ai['name'])) if ai else '',
                         'debit': it['debit'], 'credit': it['credit'],
                         'dir': direction_text(bal), 'balance': abs(bal)})
        ytd_d += md
        ytd_c += mc
        rows.append({'type': 'month', 'date': last_day(p)[5:], 'voucher': '', 'summary': '%s 本月合计' % plabel(p),
                     'debit': md, 'credit': mc, 'dir': direction_text(bal), 'balance': abs(bal), 'period': p})
        rows.append({'type': 'ytd', 'date': '', 'voucher': '', 'summary': '本年累计',
                     'debit': ytd_d, 'credit': ytd_c, 'dir': direction_text(bal), 'balance': abs(bal), 'period': p})
        p = next_period(p)
    return {'account': accts[code], 'from': pf, 'to': pt, 'rows': rows}


# ---------------------------------------------------------------- 辅助核算余额表


def aux_balance(conn, code, pf, pt, show_zero=False):
    pf, pt = normalize_range(conn, pf, pt)
    accts = account_map(conn)
    if code not in accts:
        raise AppError('科目不存在：%s' % code)
    leaf = leaf_balances(conn, pf, pt, accts)
    aux_names = aux_name_map(conn)
    agg = {}
    for (c, aux), d in leaf.items():
        if not c.startswith(code):
            continue
        t = agg.setdefault(aux, _z())
        for k in t:
            t[k] += d[k]
    rows = []
    for aux, d in agg.items():
        if not show_zero and not any(d.values()):
            continue
        info = aux_names.get(aux)
        bd, bc = split(d['begin'])
        ed, ec = split(d['end'])
        rows.append({'aux_id': aux, 'aux_code': info['code'] if info else '', 'aux_name': info['name'] if info else '（未指定辅助项）',
                     'begin_d': bd, 'begin_c': bc, 'pd': d['pd'], 'pc': d['pc'], 'end_d': ed, 'end_c': ec,
                     'end': d['end']})
    rows.sort(key=lambda r: (r['aux_code'] == '', r['aux_code']))
    return {'account': accts[code], 'from': pf, 'to': pt, 'rows': rows}
