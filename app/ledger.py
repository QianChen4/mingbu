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


# ---------------------------------------------------------------- 日期区间
#
# 从 v1.8 起，账簿和报表都按日期查询（起始日期 至 结束日期），可以是某一天、几天、几个月，也可以跨年度。
# 凭证的日期总是落在它所属的会计期间里，所以按整月的日期查，和以前按月查的结果完全一样。
# 期末处理（折旧、结转、结账）仍然按会计期间进行，它们用下面的 leaf_end_balances(期间) 等函数。


def first_day(p):
    return '%04d-%02d-01' % divmod(int(p), 100)


def _norm_date(d):
    import datetime
    try:
        return datetime.datetime.strptime(str(d).strip(), '%Y-%m-%d').strftime('%Y-%m-%d')
    except ValueError:
        raise AppError('日期格式不正确：%s（应为 2026-01-05 这样的格式）' % (d or '空'))


def start_date(conn):
    return first_day(start_period(conn))


def date_range(conn, d1, d2):
    """查询区间：起始日期、结束日期（也接受 YYYYMM 期间整数，按整月处理）。
    起始日期早于账套启用时自动从启用日开始；返回 (d1, d2, 原始起始日期)。"""
    def conv(d, end):
        if isinstance(d, int) or (isinstance(d, str) and d.isdigit()):
            p = check_period(int(d))
            return last_day(p) if end else first_day(p)
        return _norm_date(d)
    if not d1 and not d2:
        raise AppError('请选择查询日期')
    d1, d2 = conv(d1 or d2, False), conv(d2 or d1, True)
    if d1 > d2:
        raise AppError('起始日期（%s）不能晚于结束日期（%s）' % (d1, d2))
    sd = start_date(conn)
    if d2 < sd:
        raise AppError('查询日期早于账套启用日期 %s' % sd)
    return max(d1, sd), d2, d1


def year_first(d, sd):
    """d 所在年度的 1 月 1 日；启用年度从启用日开始。"""
    return max(d[:4] + '-01-01', sd)


def date_label(d1, d2):
    return d1 if d1 == d2 else '%s 至 %s' % (d1, d2)


def prev_day(d):
    import datetime
    return (datetime.datetime.strptime(d, '%Y-%m-%d') - datetime.timedelta(days=1)).strftime('%Y-%m-%d')


def next_day(d):
    import datetime
    return (datetime.datetime.strptime(d, '%Y-%m-%d') + datetime.timedelta(days=1)).strftime('%Y-%m-%d')


def month_spans(d1, d2):
    """把 [d1, d2] 按自然月切开：[(期间, 本段起, 本段止, 是否整月)]。"""
    out = []
    p = period_of_date(d1)
    while True:
        a, b = first_day(p), last_day(p)
        s, e = max(a, d1), min(b, d2)
        if s > e:
            break
        out.append((p, s, e, s == a and e == b))
        if e >= d2:
            break
        p = next_period(p)
    return out


# ---------------------------------------------------------------- 余额核心

LINES_DATED = 'lines l JOIN vouchers v ON v.id = l.voucher_id'

# 账簿查询条件“包含未审核凭证”：不勾时只统计已审核的凭证。
# 每个请求在自己的线程里处理，所以用线程内的开关；不在 audited_only() 里时和以前一样统计全部凭证。
import threading as _threading
from contextlib import contextmanager as _contextmanager

_flags = _threading.local()


@_contextmanager
def audited_only(on=True):
    old = getattr(_flags, 'audited', False)
    _flags.audited = bool(on)
    try:
        yield
    finally:
        _flags.audited = old


def _aud():
    return ' AND v.audited = 1' if getattr(_flags, 'audited', False) else ''


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


def balances_before(conn, d, accts=None):
    """日期 d 当天开始之前（即前一天结束时）每个（末级科目, 辅助项）的余额。
    d 不晚于启用年度 1 月 1 日时取“年初余额”；不晚于启用日时取启用时的余额。"""
    accts = accts or account_map(conn)
    sd = start_date(conn)
    res = {}
    if d <= sd[:4] + '-01-01':
        for o in opening_rows(conn, accts):
            k = (o['code'], o['aux'])
            res[k] = res.get(k, 0) + o['year_begin']
        return res
    for o in opening_rows(conn, accts):
        k = (o['code'], o['aux'])
        res[k] = res.get(k, 0) + o['at_start']
    if d > sd:
        for r in conn.execute('SELECT l.account_code, l.aux_id, SUM(l.debit - l.credit) FROM ' + LINES_DATED +
                              ' WHERE v.date < ?' + _aud() + ' GROUP BY l.account_code, l.aux_id', (d,)):
            k = (r[0], r[1])
            res[k] = res.get(k, 0) + r[2]
    return res


def balances_through(conn, d, accts=None):
    """日期 d 当天结束时每个（末级科目, 辅助项）的余额。"""
    return balances_before(conn, next_day(d), accts) if d >= start_date(conn) else balances_before(conn, d, accts)


def leaf_balances(conn, d1, d2, accts=None):
    """
    计算 [d1, d2] 区间内每个（末级科目, 辅助项）的：
    期初 begin、本期借 pd、本期贷 pc、本年累计借 yd、本年累计贷 yc、期末 end。
    本年累计 = d2 所在年度 1 月 1 日（启用年度从启用日）到 d2。d1、d2 也可以传期间整数。
    """
    d1, d2, _raw = date_range(conn, d1, d2)
    accts = accts or account_map(conn)
    sd = start_date(conn)
    y1 = year_first(d2, sd)
    res = {}

    def get(k):
        if k not in res:
            res[k] = _z()
        return res[k]

    for o in opening_rows(conn, accts):
        d = get((o['code'], o['aux']))
        d['begin'] += o['at_start']
        # 启用年度的本年累计包含启用前的累计发生额（损益类也一样，与利润表的本年累计口径一致）
        if d2[:4] == sd[:4]:
            d['yd'] += o['ytd_debit']
            d['yc'] += o['ytd_credit']

    sql = '''
        SELECT l.account_code, l.aux_id,
          SUM(CASE WHEN v.date < :d1 THEN l.debit - l.credit ELSE 0 END) AS pre,
          SUM(CASE WHEN v.date >= :d1 THEN l.debit ELSE 0 END) AS pd,
          SUM(CASE WHEN v.date >= :d1 THEN l.credit ELSE 0 END) AS pc,
          SUM(CASE WHEN v.date >= :y1 THEN l.debit ELSE 0 END) AS yd,
          SUM(CASE WHEN v.date >= :y1 THEN l.credit ELSE 0 END) AS yc
        FROM ''' + LINES_DATED + ''' WHERE v.date <= :d2''' + _aud() + '''
        GROUP BY l.account_code, l.aux_id'''
    for r in conn.execute(sql, {'d1': d1, 'd2': d2, 'y1': y1}):
        d = get((r['account_code'], r['aux_id']))
        d['begin'] += r['pre']
        d['pd'] += r['pd']
        d['pc'] += r['pc']
        d['yd'] += r['yd']
        d['yc'] += r['yc']
    for d in res.values():
        d['end'] = d['begin'] + d['pd'] - d['pc']
    return res


# 按会计期间取余额（期末处理、车辆核对等用）
def leaf_end_balances(conn, p):
    """截至 p 期末每个（末级科目, 辅助项）的余额。"""
    return balances_through(conn, last_day(p))


def leaf_year_begin_balances(conn, year):
    """某年度年初（1 月初）的余额。"""
    if year < start_period(conn) // 100:
        return {}
    return balances_before(conn, '%04d-01-01' % year)


def leaf_begin_balances(conn, p):
    """p 期开始时（即上期末）每个（末级科目, 辅助项）的余额。"""
    return balances_before(conn, first_day(p))


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


def balance_table(conn, d1, d2, level=9, with_aux=False, show_zero=False, code_from='', code_to='', level_from=1):
    """code_from、code_to：科目范围（含起止科目和止科目的全部下级）；level_from ~ level：显示的级次范围。
    指定了科目范围时，合计只算范围内的科目，不再判断试算平衡。"""
    d1, d2, _raw = date_range(conn, d1, d2)
    code_from, code_to = (code_from or '').strip(), (code_to or '').strip()
    if code_from and code_to and code_from > code_to and not code_from.startswith(code_to):
        code_from, code_to = code_to, code_from
    filtered = bool(code_from or code_to)

    def in_range(code):
        if code_from and code < code_from:
            return False
        if code_to and code > code_to and not code.startswith(code_to):
            return False
        return True
    accts = account_map(conn)
    leaf = leaf_balances(conn, d1, d2, accts)
    agg = rollup(accts, leaf)
    aux_names = aux_name_map(conn)

    def mk(code, name, d, lvl, aux=0, is_aux=False, path=''):
        bd, bc = split(d['begin'])
        ed, ec = split(d['end'])
        return {'code': code, 'name': name, 'path': path, 'level': lvl, 'aux_id': aux, 'is_aux': is_aux,
                'begin_d': bd, 'begin_c': bc, 'pd': d['pd'], 'pc': d['pc'],
                'yd': d['yd'], 'yc': d['yc'], 'end_d': ed, 'end_c': ec,
                # 方向 + 余额（借 / 贷 / 平），和常见财务软件的余额表一样
                'begin_dir': _dir(d['begin']), 'begin': abs(d['begin']),
                'end_dir': _dir(d['end']), 'end': abs(d['end'])}

    def path_of(a):
        # 1002\银行存款\工商银行：一级科目编码 + 各级科目名称
        names = []
        x = a
        while x:
            names.append(x['name'])
            x = accts.get(x.get('parent') or '')
        top = a['code']
        x = a
        while x.get('parent') and x['parent'] in accts:
            x = accts[x['parent']]
            top = x['code']
        return '\\'.join([top] + list(reversed(names)))

    def nonzero(d):
        return any(d[k] for k in ('begin', 'pd', 'pc', 'yd', 'yc', 'end'))

    rows = []
    totals = {k: 0 for k in ('begin_d', 'begin_c', 'pd', 'pc', 'yd', 'yc', 'end_d', 'end_c')}
    for a in sorted(accts.values(), key=lambda x: x['code']):
        d = agg.get(a['code'], _z())
        if not filtered:
            top = a['level'] == 1
        else:
            # 合计只加范围内最上面一级的科目（它的上级不在范围内），免得上下级重复相加
            if not in_range(a['code']):
                continue
            top = not (a['parent'] in accts and in_range(a['parent']))
        if top:
            r1 = mk(a['code'], a['name'], d, 1)
            for k in totals:
                totals[k] += r1[k]
        if a['level'] > level or a['level'] < level_from:
            continue
        if not show_zero and not nonzero(d):
            continue
        pth = path_of(a)
        rows.append(mk(a['code'], a['name'], d, a['level'], path=pth))
        if with_aux and a['is_leaf'] and a['aux_type']:
            items = [(k[1], v) for k, v in leaf.items() if k[0] == a['code']]
            items.sort(key=lambda x: aux_names.get(x[0], {}).get('code', ''))
            for aux, v in items:
                if not show_zero and not nonzero(v):
                    continue
                info = aux_names.get(aux)
                label = ('%s %s' % (info['code'], info['name'])) if info else '（未指定）'
                rows.append(mk(a['code'], label, v, a['level'] + 1, aux, True, pth + '\\' + label))
    for k, kd, kc in (('begin', 'begin_d', 'begin_c'), ('end', 'end_d', 'end_c')):
        net = totals[kd] - totals[kc]
        totals[k + '_dir'], totals[k] = _dir(net), abs(net)
    balanced = (totals['begin_d'] == totals['begin_c'] and totals['pd'] == totals['pc']
                and totals['end_d'] == totals['end_c'])
    return {'from': d1, 'to': d2, 'label': date_label(d1, d2), 'year': int(d2[:4]),
            'rows': rows, 'totals': totals, 'balanced': balanced, 'filtered': filtered}


def _dir(v):
    return '借' if v > 0 else '贷' if v < 0 else '平'


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


def _sum_range(conn, like, a, b, aux=None):
    """科目（含下级）在 [a, b] 日期内的借、贷合计。"""
    q = ('SELECT COALESCE(SUM(l.debit), 0), COALESCE(SUM(l.credit), 0) FROM ' + LINES_DATED +
         ' WHERE l.account_code LIKE ? AND v.date BETWEEN ? AND ?' + _aud())
    args = [like, a, b]
    if aux is not None:
        q += ' AND l.aux_id = ?'
        args.append(aux)
    r = conn.execute(q, args).fetchone()
    return r[0], r[1]


def _begin_for(conn, accts, code, d, aux=None):
    """科目（含下级）在日期 d 开始前的余额。"""
    bal = balances_before(conn, d, accts)
    return sum(v for (c, a), v in bal.items() if c.startswith(code) and (aux is None or a == aux))


def _ytd_before(conn, accts, code, d, aux=None):
    """d 所在年度 1 月 1 日（启用年度从启用日、含启用前累计数）到 d 前一天的借、贷累计。"""
    sd = start_date(conn)
    y1 = year_first(d, sd)
    yd = yc = 0
    if d[:4] == sd[:4]:
        _s, yd, yc = _opening_for(conn, accts, code, aux)
    if d > y1:
        a, b = _sum_range(conn, code + '%', y1, prev_day(d), aux)
        yd += a
        yc += b
    return yd, yc


def general_ledger(conn, code, d1, d2):
    """总账：按自然月列示，每月一行“本月合计”、一行“本年累计”；起止日期不是整月时，首尾月份只算区间内的部分。
    区间可以跨年度，跨年时本年累计从 1 月重新累计。"""
    d1, d2, _raw = date_range(conn, d1, d2)
    accts = account_map(conn)
    if code not in accts:
        raise AppError('科目不存在：%s' % code)
    like = code + '%'
    bal = _begin_for(conn, accts, code, d1)
    sd = start_date(conn)
    label = '年初余额' if d1[5:] == '01-01' else ('期初余额（账套启用）' if d1 == sd else '期初余额（%s）' % d1)
    rows = [{'type': 'begin', 'period': period_of_date(d1), 'summary': label, 'debit': 0, 'credit': 0,
             'dir': direction_text(bal), 'balance': abs(bal)}]
    ytd_d, ytd_c = _ytd_before(conn, accts, code, d1)
    for i, (p, s, e, whole) in enumerate(month_spans(d1, d2)):
        if i and p % 100 == 1:
            ytd_d = ytd_c = 0
            rows.append({'type': 'begin', 'period': p, 'summary': '上年结转', 'debit': 0, 'credit': 0,
                         'dir': direction_text(bal), 'balance': abs(bal)})
        d, c = _sum_range(conn, like, s, e)
        bal += d - c
        ytd_d += d
        ytd_c += c
        rows.append({'type': 'month', 'period': p, 'from': s, 'to': e,
                     'summary': '本月合计', 'partial': not whole,
                     'debit': d, 'credit': c, 'dir': direction_text(bal), 'balance': abs(bal)})
        rows.append({'type': 'ytd', 'period': p, 'summary': '本年累计', 'debit': ytd_d, 'credit': ytd_c,
                     'dir': direction_text(bal), 'balance': abs(bal)})
    return {'account': accts[code], 'from': d1, 'to': d2, 'label': date_label(d1, d2), 'rows': rows}


# ---------------------------------------------------------------- 明细账


def detail_ledger(conn, code, d1, d2, aux_id=None):
    """明细账：列出凭证日期在 [d1, d2] 之间的分录（可以是某一天或一段时间）并滚动计算余额。
    每个月后面有“本月合计”（区间不是整月时为这几天的合计）和“本年累计”，跨年时本年累计重新开始。"""
    d1, d2, _raw = date_range(conn, d1, d2)
    accts = account_map(conn)
    if code not in accts:
        raise AppError('科目不存在：%s' % code)
    like = code + '%'
    aux = None
    aux_cond, params_aux = '', []
    if aux_id not in (None, '', 'all', 0, '0'):
        aux = int(aux_id)
        aux_cond, params_aux = ' AND l.aux_id = ?', [aux]
    begin = _begin_for(conn, accts, code, d1, aux)
    ytd_d, ytd_c = _ytd_before(conn, accts, code, d1, aux)
    items = conn.execute('SELECT l.*, v.number, v.date, v.id AS vid FROM ' + LINES_DATED +
                         ' WHERE l.account_code LIKE ? AND v.date BETWEEN ? AND ?' + _aud() + aux_cond +
                         ' ORDER BY v.date, l.period, v.number, l.seq', [like, d1, d2] + params_aux).fetchall()
    aux_names = aux_name_map(conn)
    sd = start_date(conn)
    label = '年初余额' if d1[5:] == '01-01' else ('期初余额（账套启用）' if d1 == sd else '期初余额（%s 之前）' % d1)
    rows = [{'type': 'begin', 'date': '', 'voucher': '', 'summary': label, 'debit': 0, 'credit': 0,
             'dir': direction_text(begin), 'balance': abs(begin)}]
    bal = begin
    by_period = {}
    for it in items:
        by_period.setdefault(period_of_date(it['date']), []).append(it)
    spans = month_spans(d1, d2)
    for i, (p, s, e, whole) in enumerate(spans):
        if i and p % 100 == 1:
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
        # 和用友一样，每个月后面都是“本月合计”“本年累计”；查询区间不是整月时，本月合计只算区间内的部分
        rows.append({'type': 'month', 'date': e[5:], 'voucher': '', 'summary': '本月合计', 'partial': not whole,
                     'debit': md, 'credit': mc, 'dir': direction_text(bal), 'balance': abs(bal), 'period': p})
        rows.append({'type': 'ytd', 'date': '', 'voucher': '', 'summary': '本年累计',
                     'debit': ytd_d, 'credit': ytd_c, 'dir': direction_text(bal), 'balance': abs(bal), 'period': p})
    return {'account': accts[code], 'from': d1, 'to': d2, 'label': date_label(d1, d2), 'rows': rows}


# ---------------------------------------------------------------- 辅助核算余额表


def aux_balance(conn, code, d1, d2, show_zero=False):
    d1, d2, _raw = date_range(conn, d1, d2)
    accts = account_map(conn)
    if code not in accts:
        raise AppError('科目不存在：%s' % code)
    leaf = leaf_balances(conn, d1, d2, accts)
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
                     'begin_d': bd, 'begin_c': bc, 'pd': d['pd'], 'pc': d['pc'], 'yd': d['yd'], 'yc': d['yc'],
                     'end_d': ed, 'end_c': ec, 'begin_dir': _dir(d['begin']), 'begin': abs(d['begin']),
                     'end_dir': _dir(d['end']), 'end': abs(d['end']), 'begin_signed': d['begin'], 'end_signed': d['end']})
    rows.sort(key=lambda r: (r['aux_code'] == '', r['aux_code']))
    tb, te = sum(r['begin_signed'] for r in rows), sum(r['end_signed'] for r in rows)
    totals = {'begin_dir': _dir(tb), 'begin': abs(tb), 'end_dir': _dir(te), 'end': abs(te)}
    for k in ('pd', 'pc', 'yd', 'yc'):
        totals[k] = sum(r[k] for r in rows)
    return {'account': accts[code], 'from': d1, 'to': d2, 'label': date_label(d1, d2), 'year': int(d2[:4]),
            'rows': rows, 'totals': totals}
