"""
财务报表：资产负债表、利润表、现金流量表。
按账套的会计准则出具：《企业会计准则》一般企业格式（会企01/02/03表），或《小企业会计准则》格式（会小企01/02/03表）。

报表项目的取数项用“科目关键字”（见 charts.py），不写死科目编码：
  ('S',   'bank', +1)   科目期末余额（借正贷负）× 系数
  ('JYE', 'ar',   +1)   科目各明细（含辅助项）中借方余额合计
  ('DYE', 'adv',  +1)   科目各明细（含辅助项）中贷方余额合计
  ('JS',  'vat',  +1)   科目余额为借方时取该余额，否则取 0
  ('CAT', '损益', -1)   某类别全部科目余额合计（用于尚未结转的损益）
合计项写成 'SUM:a,b,-c'。利润表：('REV', key) 贷方减借方；('EXP', key) 借方减贷方（都排除“结转损益”凭证）。

用户自建的一级科目，可以在科目设置里指定“报表项目”；没有指定的归入兜底行，保证报表平衡。
"""
from .db import AppError, company_profile
from .ledger import (account_map, leaf_end_balances, leaf_begin_balances, opening_rows, prev_period,
                     next_period, start_period, plabel, normalize_range, check_period, range_label)


def T(kind, key, k=1):
    return (kind, key, k)


# ---------------------------------------------------------------- 资产负债表格式
# (项目代码, 名称, 栏 A/L, 分组, 取数项列表 或 'SUM:...', 为零时隐藏, 附注行)
# 分组用于左右对齐：cur 流动、noncur 非流动、ltotal 负债合计、eq 所有者权益、total 总计
# 附注行（第 7 项为 True）：只列示构成，不参与任何合计，也没有行次。例如企业会计准则格式下
# “固定资产”项目按“固定资产原价 − 累计折旧 − 减值准备 ± 固定资产清理”的净额填列，
# 下面再列出原价、累计折旧、固定资产清理各是多少，方便核对。
ENT_BS = [
    ('cash', '货币资金', 'A', 'cur', [T('S', 'cash'), T('S', 'bank'), T('S', 'other_money')]),
    ('trading_fa', '交易性金融资产', 'A', 'cur', [T('S', 'trading_fa')]),
    ('notes_rec', '应收票据', 'A', 'cur', [T('S', 'notes_rec')]),
    ('ar', '应收账款', 'A', 'cur', [T('JYE', 'ar'), T('JYE', 'adv'), T('S', 'bad_debt')]),
    ('prepay', '预付款项', 'A', 'cur', [T('JYE', 'prepay'), T('JYE', 'ap')]),
    ('other_ar', '其他应收款', 'A', 'cur', [T('JYE', 'other_ar'), T('JYE', 'other_ap'), T('S', 'int_rec'), T('S', 'div_rec')]),
    ('inventory', '存货', 'A', 'cur', [T('S', 'materials'), T('S', 'goods'), T('S', 'low_value')]),
    ('contract_asset', '合同资产', 'A', 'cur', []),
    ('nca_due', '一年内到期的非流动资产', 'A', 'cur', []),
    ('other_ca', '其他流动资产', 'A', 'cur', [T('JS', 'vat'), T('S', 'pending')]),
    ('ca_total', '流动资产合计', 'A', 'cur', 'SUM:cash,trading_fa,notes_rec,ar,prepay,other_ar,inventory,contract_asset,nca_due,other_ca'),
    ('debt_inv', '债权投资', 'A', 'noncur', []),
    ('lt_rec', '长期应收款', 'A', 'noncur', [T('S', 'lt_rec')]),
    ('lt_equity', '长期股权投资', 'A', 'noncur', [T('S', 'lt_equity')]),
    ('inv_property', '投资性房地产', 'A', 'noncur', []),
    ('fixed', '固定资产', 'A', 'noncur', [T('S', 'fa'), T('S', 'accum_depr'), T('S', 'fa_impair'), T('S', 'fa_clear')]),
    ('fa_cost', '其中：固定资产原价', 'A', 'noncur', [T('S', 'fa')], False, True),
    ('accum', '减：累计折旧', 'A', 'noncur', [T('S', 'accum_depr', -1)], False, True),
    ('fa_impair', '减：固定资产减值准备', 'A', 'noncur', [T('S', 'fa_impair', -1)], True, True),
    ('fa_clear', '固定资产清理', 'A', 'noncur', [T('S', 'fa_clear')], False, True),
    ('cip', '在建工程', 'A', 'noncur', [T('S', 'cip')]),
    ('rou', '使用权资产', 'A', 'noncur', []),
    ('intangible', '无形资产', 'A', 'noncur', [T('S', 'intangible'), T('S', 'amort')]),
    ('intangible_cost', '其中：无形资产原价', 'A', 'noncur', [T('S', 'intangible')], True, True),
    ('amort', '减：累计摊销', 'A', 'noncur', [T('S', 'amort', -1)], True, True),
    ('dev', '开发支出', 'A', 'noncur', []),
    ('goodwill', '商誉', 'A', 'noncur', []),
    ('ltpe', '长期待摊费用', 'A', 'noncur', [T('S', 'ltpe')]),
    ('dta', '递延所得税资产', 'A', 'noncur', [T('S', 'dta')]),
    ('other_nca', '其他非流动资产', 'A', 'noncur', []),
    ('nca_total', '非流动资产合计', 'A', 'noncur', 'SUM:debt_inv,lt_rec,lt_equity,inv_property,fixed,cip,rou,intangible,dev,goodwill,ltpe,dta,other_nca'),
    ('assets', '资产总计', 'A', 'total', 'SUM:ca_total,nca_total'),

    ('st_loan', '短期借款', 'L', 'cur', [T('S', 'st_loan', -1)]),
    ('trading_fl', '交易性金融负债', 'L', 'cur', []),
    ('notes_pay', '应付票据', 'L', 'cur', [T('S', 'notes_pay', -1)]),
    ('ap', '应付账款', 'L', 'cur', [T('DYE', 'ap'), T('DYE', 'prepay')]),
    ('adv', '预收款项', 'L', 'cur', [T('DYE', 'adv'), T('DYE', 'ar')]),
    ('contract_liab', '合同负债', 'L', 'cur', [T('S', 'contract_liab', -1)]),
    ('payroll', '应付职工薪酬', 'L', 'cur', [T('S', 'payroll', -1)]),
    ('tax', '应交税费', 'L', 'cur', [T('S', 'tax', -1), T('JS', 'vat')]),
    ('other_ap', '其他应付款', 'L', 'cur', [T('DYE', 'other_ap'), T('DYE', 'other_ar'), T('S', 'int_pay', -1), T('S', 'div_pay', -1)]),
    ('ncl_due', '一年内到期的非流动负债', 'L', 'cur', []),
    ('other_cl', '其他流动负债', 'L', 'cur', []),
    ('cl_total', '流动负债合计', 'L', 'cur', 'SUM:st_loan,trading_fl,notes_pay,ap,adv,contract_liab,payroll,tax,other_ap,ncl_due,other_cl'),
    ('lt_loan', '长期借款', 'L', 'noncur', [T('S', 'lt_loan', -1)]),
    ('bonds', '应付债券', 'L', 'noncur', []),
    ('lease_liab', '租赁负债', 'L', 'noncur', []),
    ('lt_ap', '长期应付款', 'L', 'noncur', [T('S', 'lt_ap', -1)]),
    ('provisions', '预计负债', 'L', 'noncur', []),
    ('deferred_income', '递延收益', 'L', 'noncur', [T('S', 'deferred_income', -1)]),
    ('dtl', '递延所得税负债', 'L', 'noncur', []),
    ('other_ncl', '其他非流动负债', 'L', 'noncur', []),
    ('ncl_total', '非流动负债合计', 'L', 'noncur', 'SUM:lt_loan,bonds,lease_liab,lt_ap,provisions,deferred_income,dtl,other_ncl'),
    ('liab', '负债合计', 'L', 'ltotal', 'SUM:cl_total,ncl_total'),
    ('capital', '实收资本（或股本）', 'L', 'eq', [T('S', 'capital', -1)]),
    ('other_eq_inst', '其他权益工具', 'L', 'eq', []),
    ('cap_reserve', '资本公积', 'L', 'eq', [T('S', 'cap_reserve', -1)]),
    ('treasury', '减：库存股', 'L', 'eq', []),
    ('oci', '其他综合收益', 'L', 'eq', []),
    ('special_reserve', '专项储备', 'L', 'eq', []),
    ('surplus', '盈余公积', 'L', 'eq', [T('S', 'surplus', -1)]),
    ('retained', '未分配利润', 'L', 'eq', [T('S', 'profit', -1), T('S', 'dist', -1), T('CAT', '损益', -1)]),
    ('other_eq', '其他（未归类权益科目）', 'L', 'eq', [], True),
    ('equity', '所有者权益合计', 'L', 'eq', 'SUM:capital,other_eq_inst,cap_reserve,-treasury,oci,special_reserve,surplus,retained,other_eq'),
    ('le_total', '负债和所有者权益总计', 'L', 'total', 'SUM:liab,equity'),
]

SMALL_BS = [
    ('cash', '货币资金', 'A', 'cur', [T('S', 'cash'), T('S', 'bank'), T('S', 'other_money')]),
    ('st_inv', '短期投资', 'A', 'cur', [T('S', 'st_inv')]),
    ('notes_rec', '应收票据', 'A', 'cur', [T('S', 'notes_rec')]),
    ('ar', '应收账款', 'A', 'cur', [T('JYE', 'ar'), T('JYE', 'adv')]),
    ('prepay', '预付账款', 'A', 'cur', [T('JYE', 'prepay'), T('JYE', 'ap')]),
    ('div_rec', '应收股利', 'A', 'cur', [T('S', 'div_rec')]),
    ('int_rec', '应收利息', 'A', 'cur', [T('S', 'int_rec')]),
    ('other_ar', '其他应收款', 'A', 'cur', [T('JYE', 'other_ar'), T('JYE', 'other_ap')]),
    ('inventory', '存货', 'A', 'cur', [T('S', 'materials'), T('S', 'goods'), T('S', 'low_value')]),
    ('other_ca', '其他流动资产', 'A', 'cur', [T('JS', 'vat'), T('S', 'pending')]),
    ('ca_total', '流动资产合计', 'A', 'cur', 'SUM:cash,st_inv,notes_rec,ar,prepay,div_rec,int_rec,other_ar,inventory,other_ca'),
    ('lt_bond', '长期债券投资', 'A', 'noncur', [T('S', 'lt_bond')]),
    ('lt_equity', '长期股权投资', 'A', 'noncur', [T('S', 'lt_equity')]),
    ('fa_cost', '固定资产原价', 'A', 'noncur', [T('S', 'fa')]),
    ('accum', '减：累计折旧', 'A', 'noncur', [T('S', 'accum_depr', -1)]),
    ('fa_net', '固定资产账面价值', 'A', 'noncur', 'SUM:fa_cost,-accum'),
    ('cip', '在建工程', 'A', 'noncur', [T('S', 'cip')]),
    ('eng_mat', '工程物资', 'A', 'noncur', []),
    ('fa_clear', '固定资产清理', 'A', 'noncur', [T('S', 'fa_clear')]),
    ('bio', '生产性生物资产', 'A', 'noncur', []),
    ('intangible', '无形资产', 'A', 'noncur', [T('S', 'intangible'), T('S', 'amort')]),
    ('dev', '开发支出', 'A', 'noncur', []),
    ('ltpe', '长期待摊费用', 'A', 'noncur', [T('S', 'ltpe')]),
    ('other_nca', '其他非流动资产', 'A', 'noncur', []),
    ('nca_total', '非流动资产合计', 'A', 'noncur', 'SUM:lt_bond,lt_equity,fa_net,cip,eng_mat,fa_clear,bio,intangible,dev,ltpe,other_nca'),
    ('assets', '资产总计', 'A', 'total', 'SUM:ca_total,nca_total'),

    ('st_loan', '短期借款', 'L', 'cur', [T('S', 'st_loan', -1)]),
    ('notes_pay', '应付票据', 'L', 'cur', [T('S', 'notes_pay', -1)]),
    ('ap', '应付账款', 'L', 'cur', [T('DYE', 'ap'), T('DYE', 'prepay')]),
    ('adv', '预收账款', 'L', 'cur', [T('DYE', 'adv'), T('DYE', 'ar')]),
    ('payroll', '应付职工薪酬', 'L', 'cur', [T('S', 'payroll', -1)]),
    ('tax', '应交税费', 'L', 'cur', [T('S', 'tax', -1), T('JS', 'vat')]),
    ('int_pay', '应付利息', 'L', 'cur', [T('S', 'int_pay', -1)]),
    ('profit_pay', '应付利润', 'L', 'cur', [T('S', 'div_pay', -1)]),
    ('other_ap', '其他应付款', 'L', 'cur', [T('DYE', 'other_ap'), T('DYE', 'other_ar')]),
    ('other_cl', '其他流动负债', 'L', 'cur', []),
    ('cl_total', '流动负债合计', 'L', 'cur', 'SUM:st_loan,notes_pay,ap,adv,payroll,tax,int_pay,profit_pay,other_ap,other_cl'),
    ('lt_loan', '长期借款', 'L', 'noncur', [T('S', 'lt_loan', -1)]),
    ('lt_ap', '长期应付款', 'L', 'noncur', [T('S', 'lt_ap', -1)]),
    ('deferred_income', '递延收益', 'L', 'noncur', [T('S', 'deferred_income', -1)]),
    ('other_ncl', '其他非流动负债', 'L', 'noncur', []),
    ('ncl_total', '非流动负债合计', 'L', 'noncur', 'SUM:lt_loan,lt_ap,deferred_income,other_ncl'),
    ('liab', '负债合计', 'L', 'ltotal', 'SUM:cl_total,ncl_total'),
    ('capital', '实收资本（或股本）', 'L', 'eq', [T('S', 'capital', -1)]),
    ('cap_reserve', '资本公积', 'L', 'eq', [T('S', 'cap_reserve', -1)]),
    ('surplus', '盈余公积', 'L', 'eq', [T('S', 'surplus', -1)]),
    ('retained', '未分配利润', 'L', 'eq', [T('S', 'profit', -1), T('S', 'dist', -1), T('CAT', '损益', -1)]),
    ('other_eq', '其他（未归类权益科目）', 'L', 'eq', [], True),
    ('equity', '所有者权益合计', 'L', 'eq', 'SUM:capital,cap_reserve,surplus,retained,other_eq'),
    ('le_total', '负债和所有者权益总计', 'L', 'total', 'SUM:liab,equity'),
]
BS_FALLBACK = {'资产': 'other_nca', '负债': 'other_cl', '权益': 'other_eq'}

# ---------------------------------------------------------------- 利润表格式
# (项目代码, 名称, 取数项 / 公式, 缩进, 是否“其中”项)
ENT_IS = [
    ('revenue', '一、营业收入', [('REV', 'main_rev'), ('REV', 'other_rev')], 0),
    ('cost', '减：营业成本', [('EXP', 'main_cost'), ('EXP', 'other_cost')], 1),
    ('taxes', '税金及附加', [('EXP', 'taxes')], 1),
    ('selling', '销售费用', [('EXP', 'selling')], 1),
    ('admin', '管理费用', [('EXP', 'admin')], 1),
    ('rnd', '研发费用', [('EXP', 'rnd')], 1),
    ('finance', '财务费用', [('EXP', 'finance')], 1),
    ('interest_exp', '其中：利息费用', [('EXP', 'fin_interest')], 2, True),
    ('interest_inc', '利息收入', [('REV', 'fin_income')], 2, True),
    ('other_income', '加：其他收益', [('REV', 'other_income')], 1),
    ('invest', '投资收益（损失以“-”号填列）', [('REV', 'invest_income')], 1),
    ('fv_change', '公允价值变动收益（损失以“-”号填列）', [('REV', 'fv_change')], 1),
    ('credit_loss', '信用减值损失（损失以“-”号填列）', [('REV', 'credit_impair')], 1),
    ('impair', '资产减值损失（损失以“-”号填列）', [('REV', 'asset_impair')], 1),
    ('disposal', '资产处置收益（损失以“-”号填列）', [('REV', 'disposal')], 1),
    ('other_pl', '其他损益（未归类科目）', [], 1),
    ('op_profit', '二、营业利润（亏损以“-”号填列）',
     'revenue-cost-taxes-selling-admin-rnd-finance+other_income+invest+fv_change+credit_loss+impair+disposal+other_pl', 0),
    ('non_op_inc', '加：营业外收入', [('REV', 'non_op_inc')], 1),
    ('non_op_exp', '减：营业外支出', [('EXP', 'non_op_exp')], 1),
    ('total_profit', '三、利润总额（亏损总额以“-”号填列）', 'op_profit+non_op_inc-non_op_exp', 0),
    ('income_tax', '减：所得税费用', [('EXP', 'income_tax')], 1),
    ('net_profit', '四、净利润（净亏损以“-”号填列）', 'total_profit-income_tax', 0),
]
SMALL_IS = [
    ('revenue', '一、营业收入', [('REV', 'main_rev'), ('REV', 'other_rev')], 0),
    ('cost', '减：营业成本', [('EXP', 'main_cost'), ('EXP', 'other_cost')], 1),
    ('taxes', '税金及附加', [('EXP', 'taxes')], 1),
    ('selling', '销售费用', [('EXP', 'selling')], 1),
    ('admin', '管理费用', [('EXP', 'admin')], 1),
    ('finance', '财务费用', [('EXP', 'finance')], 1),
    ('interest_exp', '其中：利息费用（收入以“-”号填列）', [('EXP', 'fin_interest'), ('EXP', 'fin_income')], 2, True),
    ('invest', '加：投资收益（损失以“-”号填列）', [('REV', 'invest_income')], 1),
    ('other_pl', '其他损益（未归类科目）', [], 1),
    ('op_profit', '二、营业利润（亏损以“-”号填列）', 'revenue-cost-taxes-selling-admin-finance+invest+other_pl', 0),
    ('non_op_inc', '加：营业外收入', [('REV', 'non_op_inc')], 1),
    ('gov_grant', '其中：政府补助', [('REV', 'gov_grant')], 2, True),
    ('non_op_exp', '减：营业外支出', [('EXP', 'non_op_exp')], 1),
    ('total_profit', '三、利润总额（亏损总额以“-”号填列）', 'op_profit+non_op_inc-non_op_exp', 0),
    ('income_tax', '减：所得税费用', [('EXP', 'income_tax')], 1),
    ('net_profit', '四、净利润（净亏损以“-”号填列）', 'total_profit-income_tax', 0),
]
IS_EXPENSE_KEYS = {'cost', 'taxes', 'selling', 'admin', 'rnd', 'finance', 'non_op_exp', 'income_tax'}

FORMATS = {
    'enterprise': {'bs': ENT_BS, 'is': ENT_IS, 'bs_no': '会企01表', 'is_no': '会企02表', 'cf_no': '会企03表'},
    'small': {'bs': SMALL_BS, 'is': SMALL_IS, 'bs_no': '会小企01表', 'is_no': '会小企02表', 'cf_no': '会小企03表'},
}


def _fmt(conn):
    prof = company_profile(conn)
    return FORMATS.get(prof['standard'], FORMATS['enterprise']), prof['keymap']


def report_line_options(standard='enterprise'):
    """科目设置界面里“报表项目”的下拉选项。"""
    f = FORMATS.get(standard, FORMATS['enterprise'])
    bs = [{'key': x[0], 'name': x[1], 'side': ('A' if x[2] == 'A' else ('E' if x[3] == 'eq' else 'L'))}
          for x in f['bs'] if isinstance(x[4], list) and not (len(x) > 6 and x[6])]
    is_ = [{'key': it[0], 'name': it[1]} for it in f['is'] if isinstance(it[2], list) and len(it) < 5]
    return {'bs': bs, 'is': is_}


def _covered(code, prefixes):
    return any(code.startswith(p) or p.startswith(code) for p in prefixes)


def _sum_parts(spec):
    out = []
    for k in spec[4:].split(','):
        out.append((k[1:], -1) if k.startswith('-') else (k, 1))
    return out


def _bs_term_text(t, keymap, accts):
    kind, key, k = t
    sign = '+' if k > 0 else '−'
    if kind == 'CAT':
        return '%s 全部%s类科目余额' % (sign, key)
    code = keymap.get(key, key)
    name = accts[code]['name'] if code in accts else ''
    label = {'S': '余额', 'JYE': '借方余额明细', 'DYE': '贷方余额明细', 'JS': '借方余额'}[kind]
    return '%s %s%s %s' % (sign, code, name, label)


# ---------------------------------------------------------------- 资产负债表


def balance_sheet(conn, pf, pt=None):
    """资产负债表：pt 期末余额，与 pf 期初余额对比（pf 为 1 月时即“年初余额”）。"""
    if pt is None:
        pt = pf
        pf = (int(pf) // 100) * 100 + 1
    pf, pt = check_period(pf), check_period(pt)
    if pf > pt:
        raise AppError('起始期间（%s）不能晚于结束期间（%s）' % (plabel(pf), plabel(pt)))
    sp = start_period(conn)
    if pt < sp:
        raise AppError('报表期间早于账套启用期间 %s' % plabel(sp))
    fmt, keymap = _fmt(conn)
    accts = account_map(conn)
    # (key, name, side, group, terms, hide0) —— 把关键字换成科目编码，找不到的取数项忽略
    items = []
    for x in fmt['bs']:
        terms = x[4]
        if isinstance(terms, list):
            terms = [(k, keymap[key] if k != 'CAT' else key, f) for k, key, f in terms
                     if k == 'CAT' or (key in keymap and keymap[key] in accts)]
        items.append([x[0], x[1], x[2], x[3], terms, x[5] if len(x) > 5 else False, x[6] if len(x) > 6 else False])
    by_key = {x[0]: x for x in items}

    # 自建一级科目的归属
    prefixes = [t[1] for x in items if isinstance(x[4], list) for t in x[4] if t[0] != 'CAT']
    for a in accts.values():
        if a['level'] != 1 or a['category'] == '损益' or _covered(a['code'], prefixes):
            continue
        rl = by_key.get(a['report_line'])
        key = a['report_line'] if rl and isinstance(rl[4], list) and not rl[6] else BS_FALLBACK[a['category']]
        side = by_key[key][2]
        by_key[key][4] = by_key[key][4] + [('S', a['code'], 1 if side == 'A' else -1)]

    def evaluate(bal):
        acc_bal = {}
        for (code, aux), v in bal.items():
            acc_bal[code] = acc_bal.get(code, 0) + v

        def S(pre):
            return sum(v for c, v in acc_bal.items() if c.startswith(pre))

        def term(t):
            kind, pre, k = t
            if kind == 'S':
                return S(pre) * k
            if kind == 'JS':
                return max(0, S(pre)) * k
            if kind == 'JYE':
                return sum(v for (c, a), v in bal.items() if c.startswith(pre) and v > 0) * k
            if kind == 'DYE':
                return sum(-v for (c, a), v in bal.items() if c.startswith(pre) and v < 0) * k
            if kind == 'CAT':
                return sum(v for c, v in acc_bal.items() if c in accts and accts[c]['category'] == pre) * k
            raise ValueError(kind)

        vals = {}
        for key, name, side, group, terms, hide0, memo in items:
            if isinstance(terms, list):
                vals[key] = sum(term(t) for t in terms)
            else:
                vals[key] = sum(vals[k] * f for k, f in _sum_parts(terms))
        return vals

    end_vals = evaluate(leaf_end_balances(conn, pt))
    begin_vals = evaluate(leaf_begin_balances(conn, pf))
    rows = []
    for key, name, side, group, terms, hide0, memo in items:
        if hide0 and not end_vals[key] and not begin_vals[key]:
            continue
        is_total = not isinstance(terms, list)
        if is_total:
            formula = '合计：' + '、'.join(('减 ' if f < 0 else '') + by_key[k][1] for k, f in _sum_parts(terms))
        else:
            formula = '；'.join(_bs_term_text(t, {}, accts) for t in terms) or '（本账套没有对应的科目）'
        rows.append({'key': key, 'name': name, 'side': side, 'group': group, 'total': is_total, 'memo': memo,
                     'end': end_vals[key], 'begin': begin_vals[key], 'formula': formula})
    checks = {
        'end_diff': end_vals['assets'] - end_vals['le_total'],
        'begin_diff': begin_vals['assets'] - begin_vals['le_total'],
    }
    sy = sp // 100
    if pf % 100 == 1 or pf <= sy * 100 + 1:
        begin_label = '年初余额'
    elif pf <= sp:
        begin_label = '期初余额（%s初）' % plabel(sp)
    else:
        begin_label = '期初余额（%s初）' % plabel(pf)
    return {'period': pt, 'from': pf, 'to': pt, 'label': '%s末' % plabel(pt), 'begin_label': begin_label,
            'form_no': fmt['bs_no'], 'rows': rows, 'checks': checks}


# ---------------------------------------------------------------- 利润表


def pl_signed(conn, pf, pt):
    """损益类末级科目在区间内的发生额（借减贷），排除“结转损益”凭证。"""
    out = {}
    q = ('SELECT l.account_code, SUM(l.debit - l.credit) FROM lines l JOIN vouchers v ON v.id = l.voucher_id '
         'WHERE l.period BETWEEN ? AND ? AND v.kind != ? GROUP BY l.account_code')
    for r in conn.execute(q, (pf, pt, '结转损益')):
        out[r[0]] = out.get(r[0], 0) + r[1]
    return out


def _is_values(conn, pf, pt, accts, items, include_opening):
    sig = pl_signed(conn, pf, pt)
    if include_opening:
        for o in opening_rows(conn, accts):
            if not o['is_bs']:
                sig[o['code']] = sig.get(o['code'], 0) + o['ytd_debit'] - o['ytd_credit']

    def S(pre):
        return sum(v for c, v in sig.items() if c.startswith(pre) and c in accts and accts[c]['category'] == '损益')

    vals = {}
    for it in items:
        key, terms = it[0], it[2]
        if isinstance(terms, list):
            vals[key] = sum((-S(pre) if kind == 'REV' else S(pre)) for kind, pre in terms)
    for it in items:
        key, terms = it[0], it[2]
        if isinstance(terms, str):
            total, sign, tok = 0, 1, ''
            for ch in terms + '+':
                if ch in '+-':
                    if tok:
                        total += sign * vals[tok]
                    sign, tok = (1 if ch == '+' else -1), ''
                else:
                    tok += ch
            vals[key] = total
    return vals


def income_statement(conn, pf, pt=None):
    """利润表：本期（pf~pt，可跨年）、本年累计（pt 所在年度 1 月至 pt）、上年同期（区间整体前移一年）。"""
    if pt is None:
        pt = pf
    raw_pf = check_period(pf)
    pf, pt = normalize_range(conn, pf, pt)
    sp = start_period(conn)
    sy = sp // 100
    accts = account_map(conn)
    fmt, keymap = _fmt(conn)
    items = []
    for x in fmt['is']:
        x = list(x)
        if isinstance(x[2], list):
            x[2] = [(k, keymap[key]) for k, key in x[2] if key in keymap and keymap[key] in accts]
        items.append(x)
    by_key = {x[0]: x for x in items}
    prefixes = [t[1] for x in items if isinstance(x[2], list) for t in x[2]]
    for a in accts.values():
        if a['level'] != 1 or a['category'] != '损益' or _covered(a['code'], prefixes):
            continue
        key = a['report_line'] if a['report_line'] in by_key and isinstance(by_key[a['report_line']][2], list) \
            else 'other_pl'
        kind = 'EXP' if key in IS_EXPENSE_KEYS else 'REV'
        by_key[key][2] = by_key[key][2] + [(kind, a['code'])]

    year = pt // 100
    # 账套年中启用时，启用前的本年累计数只有合计数：区间从启用月之前开始时才计入
    month = _is_values(conn, pf, pt, accts, items, raw_pf < sp <= pt)
    ytd = _is_values(conn, max(year * 100 + 1, sp), pt, accts, items, year == sy)
    prev = None
    ppf, ppt = pf - 100, pt - 100
    if ppf >= sp:  # 上年同期必须完整落在账套启用之后，才有可比数据
        prev = _is_values(conn, ppf, ppt, accts, items, False)
    rows = []
    for it in items:
        key, name, terms, indent = it[0], it[1], it[2], it[3]
        if key == 'other_pl' and not terms:
            continue
        if isinstance(terms, list):
            formula = ' '.join(('+%s贷方−借方' if k == 'REV' else '+%s借方−贷方') % pre for k, pre in terms)
        else:
            formula = terms
        rows.append({'key': key, 'name': name, 'indent': indent, 'total': isinstance(terms, str),
                     'memo': len(it) > 4, 'month': month[key], 'ytd': ytd[key],
                     'prev': prev[key] if prev else None, 'formula': formula})
    return {'period': pt, 'from': pf, 'to': pt, 'label': range_label(pf, pt), 'single': pf == pt,
            'prev_label': range_label(ppf, ppt), 'rows': rows, 'has_prev': prev is not None,
            'form_no': fmt['is_no']}


# ---------------------------------------------------------------- 现金流量表


def _cash_codes(accts):
    return [c for c, a in accts.items() if a['is_cash'] and a['is_leaf']]


def cash_balance_before(conn, p, accts):
    """p 期期初（即 p-1 期末）的货币资金余额。p 不晚于启用期间时取启用时余额。"""
    sp = start_period(conn)
    codes = set(_cash_codes(accts))
    if p <= sp:
        return sum(o['at_start'] for o in opening_rows(conn, accts) if o['code'] in codes)
    bal = leaf_end_balances(conn, prev_period(p))
    return sum(v for (c, a), v in bal.items() if c in codes)


def _cf_values(conn, pf, pt, accts):
    codes = _cash_codes(accts)
    if not codes:
        return {}, 0
    marks = ','.join('?' * len(codes))
    flows = {}
    for r in conn.execute('SELECT cf_item, SUM(debit - credit) FROM lines WHERE period BETWEEN ? AND ? '
                          'AND account_code IN (%s) GROUP BY cf_item' % marks, [pf, pt] + codes):
        flows[r[0] or ''] = r[1]
    return flows, flows.pop('', 0)


def cash_flow(conn, pf, pt=None):
    """现金流量表：本期（pf~pt，可跨年）与本年累计（pt 所在年度）。"""
    if pt is None:
        pt = pf
    pf, pt = normalize_range(conn, pf, pt)
    sp = start_period(conn)
    p = pt
    accts = account_map(conn)
    items = [dict(r) for r in conn.execute('SELECT * FROM cf_items ORDER BY sort')]
    year = p // 100
    y1 = max(year * 100 + 1, sp)

    def build(pf, pt):
        flows, unassigned = _cf_values(conn, pf, pt, accts)
        vals = {}
        for it in items:
            v = flows.get(it['code'], 0)
            vals[it['code']] = -v if it['flow'] == '流出' else v
        return vals, unassigned, flows.get('CF99', 0)

    mv, m_un, m_int = build(pf, pt)
    yv, y_un, y_int = build(y1, pt)
    m_begin = cash_balance_before(conn, pf, accts)
    y_begin = cash_balance_before(conn, y1, accts)
    end_bal = cash_balance_before(conn, next_period(pt), accts)

    rows = []
    totals_m, totals_y = {}, {}
    sections = [('经营活动', '一、经营活动产生的现金流量：'), ('投资活动', '二、投资活动产生的现金流量：'),
                ('筹资活动', '三、筹资活动产生的现金流量：')]
    net_m = net_y = 0
    for sec, title in sections:
        rows.append({'name': title, 'header': True})
        sec_net_m = sec_net_y = 0
        for flow in ('流入', '流出'):
            sub_m = sub_y = 0
            for it in items:
                if it['section'] == sec and it['flow'] == flow:
                    rows.append({'name': it['name'], 'code': it['code'], 'month': mv[it['code']], 'ytd': yv[it['code']],
                                 'indent': 1})
                    sub_m += mv[it['code']]
                    sub_y += yv[it['code']]
            rows.append({'name': '%s现金%s小计' % (sec, flow), 'month': sub_m, 'ytd': sub_y, 'subtotal': True, 'indent': 1})
            sign = 1 if flow == '流入' else -1
            sec_net_m += sign * sub_m
            sec_net_y += sign * sub_y
        rows.append({'name': '%s产生的现金流量净额' % sec, 'month': sec_net_m, 'ytd': sec_net_y, 'total': True})
        net_m += sec_net_m
        net_y += sec_net_y
    fmt, _km = _fmt(conn)
    if fmt is FORMATS['small']:
        rows.append({'name': '四、现金净增加额', 'month': net_m, 'ytd': net_y, 'total': True})
        rows.append({'name': '加：期初现金余额', 'month': m_begin, 'ytd': y_begin, 'indent': 1})
        rows.append({'name': '五、期末现金余额', 'month': m_begin + net_m, 'ytd': y_begin + net_y, 'total': True})
    else:
        rows.append({'name': '四、汇率变动对现金及现金等价物的影响', 'month': 0, 'ytd': 0, 'total': True})
        rows.append({'name': '五、现金及现金等价物净增加额', 'month': net_m, 'ytd': net_y, 'total': True})
        rows.append({'name': '加：期初现金及现金等价物余额', 'month': m_begin, 'ytd': y_begin, 'indent': 1})
        rows.append({'name': '六、期末现金及现金等价物余额', 'month': m_begin + net_m, 'ytd': y_begin + net_y, 'total': True})
    checks = {
        'book_end': end_bal,
        'month_diff': end_bal - (m_begin + net_m),
        'ytd_diff': end_bal - (y_begin + net_y),
        'unassigned_month': m_un, 'unassigned_ytd': y_un,
        'internal_month': m_int, 'internal_ytd': y_int,
    }
    return {'period': pt, 'from': pf, 'to': pt, 'label': range_label(pf, pt), 'single': pf == pt,
            'rows': rows, 'checks': checks, 'form_no': fmt['cf_no']}
