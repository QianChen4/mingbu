"""
会计准则 × 行业：生成新账套的科目表、辅助核算类型、凭证模板、现金流量项目。

设计要点：
- 每个科目都有一个“关键字”（如 bank、ar、main_rev、vat_out），程序里的计算（结转损益、折旧、报表取数、
  现金流量建议等）都通过关键字找科目，不写死编码。所以同一套程序可以同时支持
  《企业会计准则》（损益类 6xxx、权益类 4xxx）和《小企业会计准则》（损益类 5xxx、权益类 3xxx）。
- 行业只是在基础科目下面增加/替换二级科目，并提供行业常用的凭证模板和辅助核算类型。
- 新账套建立时把“关键字 → 科目编码”的对照表存进账套（meta.keymap），之后用户改科目名称、
  增加下级科目都不影响程序找科目。
"""

STANDARDS = {
    'enterprise': '企业会计准则',
    'small': '小企业会计准则',
}

BASE_AUX_TYPES = ['客户', '供应商', '员工', '银行账户']

# ---------------------------------------------------------------- 一级科目
# (编码, 关键字, 名称, 类别, 方向, 辅助核算, 辅助必填, 现金类)
ENTERPRISE_L1 = [
    ('1001', 'cash', '库存现金', '资产', '借', '', 0, 1),
    ('1002', 'bank', '银行存款', '资产', '借', '银行账户', 1, 1),
    ('1012', 'other_money', '其他货币资金', '资产', '借', '', 0, 1),
    ('1101', 'trading_fa', '交易性金融资产', '资产', '借', '', 0, 0),
    ('1121', 'notes_rec', '应收票据', '资产', '借', '客户', 0, 0),
    ('1122', 'ar', '应收账款', '资产', '借', '客户', 1, 0),
    ('1123', 'prepay', '预付账款', '资产', '借', '供应商', 1, 0),
    ('1131', 'div_rec', '应收股利', '资产', '借', '', 0, 0),
    ('1132', 'int_rec', '应收利息', '资产', '借', '', 0, 0),
    ('1221', 'other_ar', '其他应收款', '资产', '借', '', 0, 0),
    ('1231', 'bad_debt', '坏账准备', '资产', '贷', '', 0, 0),
    ('1403', 'materials', '原材料', '资产', '借', '', 0, 0),
    ('1405', 'goods', '库存商品', '资产', '借', '', 0, 0),
    ('1411', 'low_value', '周转材料', '资产', '借', '', 0, 0),
    ('1511', 'lt_equity', '长期股权投资', '资产', '借', '', 0, 0),
    ('1531', 'lt_rec', '长期应收款', '资产', '借', '', 0, 0),
    ('1601', 'fa', '固定资产', '资产', '借', '', 0, 0),
    ('1602', 'accum_depr', '累计折旧', '资产', '贷', '', 0, 0),
    ('1603', 'fa_impair', '固定资产减值准备', '资产', '贷', '', 0, 0),
    ('1604', 'cip', '在建工程', '资产', '借', '', 0, 0),
    ('1606', 'fa_clear', '固定资产清理', '资产', '借', '', 0, 0),
    ('1701', 'intangible', '无形资产', '资产', '借', '', 0, 0),
    ('1702', 'amort', '累计摊销', '资产', '贷', '', 0, 0),
    ('1801', 'ltpe', '长期待摊费用', '资产', '借', '', 0, 0),
    ('1811', 'dta', '递延所得税资产', '资产', '借', '', 0, 0),
    ('1901', 'pending', '待处理财产损溢', '资产', '借', '', 0, 0),
    ('2001', 'st_loan', '短期借款', '负债', '贷', '', 0, 0),
    ('2201', 'notes_pay', '应付票据', '负债', '贷', '供应商', 0, 0),
    ('2202', 'ap', '应付账款', '负债', '贷', '供应商', 1, 0),
    ('2203', 'adv', '预收账款', '负债', '贷', '客户', 0, 0),
    ('2204', 'contract_liab', '合同负债', '负债', '贷', '客户', 0, 0),
    ('2211', 'payroll', '应付职工薪酬', '负债', '贷', '', 0, 0),
    ('2221', 'tax', '应交税费', '负债', '贷', '', 0, 0),
    ('2231', 'int_pay', '应付利息', '负债', '贷', '', 0, 0),
    ('2232', 'div_pay', '应付股利', '负债', '贷', '', 0, 0),
    ('2241', 'other_ap', '其他应付款', '负债', '贷', '', 0, 0),
    ('2401', 'deferred_income', '递延收益', '负债', '贷', '', 0, 0),
    ('2501', 'lt_loan', '长期借款', '负债', '贷', '', 0, 0),
    ('2701', 'lt_ap', '长期应付款', '负债', '贷', '供应商', 0, 0),
    ('4001', 'capital', '实收资本', '权益', '贷', '', 0, 0),
    ('4002', 'cap_reserve', '资本公积', '权益', '贷', '', 0, 0),
    ('4101', 'surplus', '盈余公积', '权益', '贷', '', 0, 0),
    ('4103', 'profit', '本年利润', '权益', '贷', '', 0, 0),
    ('4104', 'dist', '利润分配', '权益', '贷', '', 0, 0),
    ('6001', 'main_rev', '主营业务收入', '损益', '贷', '', 0, 0),
    ('6051', 'other_rev', '其他业务收入', '损益', '贷', '', 0, 0),
    ('6101', 'fv_change', '公允价值变动损益', '损益', '贷', '', 0, 0),
    ('6111', 'invest_income', '投资收益', '损益', '贷', '', 0, 0),
    ('6115', 'disposal', '资产处置损益', '损益', '贷', '', 0, 0),
    ('6117', 'other_income', '其他收益', '损益', '贷', '', 0, 0),
    ('6301', 'non_op_inc', '营业外收入', '损益', '贷', '', 0, 0),
    ('6401', 'main_cost', '主营业务成本', '损益', '借', '', 0, 0),
    ('6402', 'other_cost', '其他业务成本', '损益', '借', '', 0, 0),
    ('6403', 'taxes', '税金及附加', '损益', '借', '', 0, 0),
    ('6601', 'selling', '销售费用', '损益', '借', '', 0, 0),
    ('6602', 'admin', '管理费用', '损益', '借', '', 0, 0),
    ('6603', 'finance', '财务费用', '损益', '借', '', 0, 0),
    ('6701', 'asset_impair', '资产减值损失', '损益', '借', '', 0, 0),
    ('6702', 'credit_impair', '信用减值损失', '损益', '借', '', 0, 0),
    ('6711', 'non_op_exp', '营业外支出', '损益', '借', '', 0, 0),
    ('6801', 'income_tax', '所得税费用', '损益', '借', '', 0, 0),
]

SMALL_L1 = [
    ('1001', 'cash', '库存现金', '资产', '借', '', 0, 1),
    ('1002', 'bank', '银行存款', '资产', '借', '银行账户', 1, 1),
    ('1012', 'other_money', '其他货币资金', '资产', '借', '', 0, 1),
    ('1101', 'st_inv', '短期投资', '资产', '借', '', 0, 0),
    ('1121', 'notes_rec', '应收票据', '资产', '借', '客户', 0, 0),
    ('1122', 'ar', '应收账款', '资产', '借', '客户', 1, 0),
    ('1123', 'prepay', '预付账款', '资产', '借', '供应商', 1, 0),
    ('1131', 'div_rec', '应收股利', '资产', '借', '', 0, 0),
    ('1132', 'int_rec', '应收利息', '资产', '借', '', 0, 0),
    ('1221', 'other_ar', '其他应收款', '资产', '借', '', 0, 0),
    ('1403', 'materials', '原材料', '资产', '借', '', 0, 0),
    ('1405', 'goods', '库存商品', '资产', '借', '', 0, 0),
    ('1411', 'low_value', '周转材料', '资产', '借', '', 0, 0),
    ('1501', 'lt_bond', '长期债券投资', '资产', '借', '', 0, 0),
    ('1511', 'lt_equity', '长期股权投资', '资产', '借', '', 0, 0),
    ('1601', 'fa', '固定资产', '资产', '借', '', 0, 0),
    ('1602', 'accum_depr', '累计折旧', '资产', '贷', '', 0, 0),
    ('1604', 'cip', '在建工程', '资产', '借', '', 0, 0),
    ('1606', 'fa_clear', '固定资产清理', '资产', '借', '', 0, 0),
    ('1701', 'intangible', '无形资产', '资产', '借', '', 0, 0),
    ('1702', 'amort', '累计摊销', '资产', '贷', '', 0, 0),
    ('1801', 'ltpe', '长期待摊费用', '资产', '借', '', 0, 0),
    ('1901', 'pending', '待处理财产损溢', '资产', '借', '', 0, 0),
    ('2001', 'st_loan', '短期借款', '负债', '贷', '', 0, 0),
    ('2201', 'notes_pay', '应付票据', '负债', '贷', '供应商', 0, 0),
    ('2202', 'ap', '应付账款', '负债', '贷', '供应商', 1, 0),
    ('2203', 'adv', '预收账款', '负债', '贷', '客户', 0, 0),
    ('2211', 'payroll', '应付职工薪酬', '负债', '贷', '', 0, 0),
    ('2221', 'tax', '应交税费', '负债', '贷', '', 0, 0),
    ('2231', 'int_pay', '应付利息', '负债', '贷', '', 0, 0),
    ('2232', 'div_pay', '应付利润', '负债', '贷', '', 0, 0),
    ('2241', 'other_ap', '其他应付款', '负债', '贷', '', 0, 0),
    ('2401', 'deferred_income', '递延收益', '负债', '贷', '', 0, 0),
    ('2501', 'lt_loan', '长期借款', '负债', '贷', '', 0, 0),
    ('2701', 'lt_ap', '长期应付款', '负债', '贷', '供应商', 0, 0),
    ('3001', 'capital', '实收资本', '权益', '贷', '', 0, 0),
    ('3002', 'cap_reserve', '资本公积', '权益', '贷', '', 0, 0),
    ('3101', 'surplus', '盈余公积', '权益', '贷', '', 0, 0),
    ('3103', 'profit', '本年利润', '权益', '贷', '', 0, 0),
    ('3104', 'dist', '利润分配', '权益', '贷', '', 0, 0),
    ('5001', 'main_rev', '主营业务收入', '损益', '贷', '', 0, 0),
    ('5051', 'other_rev', '其他业务收入', '损益', '贷', '', 0, 0),
    ('5111', 'invest_income', '投资收益', '损益', '贷', '', 0, 0),
    ('5301', 'non_op_inc', '营业外收入', '损益', '贷', '', 0, 0),
    ('5401', 'main_cost', '主营业务成本', '损益', '借', '', 0, 0),
    ('5402', 'other_cost', '其他业务成本', '损益', '借', '', 0, 0),
    ('5403', 'taxes', '税金及附加', '损益', '借', '', 0, 0),
    ('5601', 'selling', '销售费用', '损益', '借', '', 0, 0),
    ('5602', 'admin', '管理费用', '损益', '借', '', 0, 0),
    ('5603', 'finance', '财务费用', '损益', '借', '', 0, 0),
    ('5711', 'non_op_exp', '营业外支出', '损益', '借', '', 0, 0),
    ('5801', 'income_tax', '所得税费用', '损益', '借', '', 0, 0),
]


def S(suffix, name, aux='', req=0, key='', cf=None, children=None):
    """二级（或三级）科目。cf=(收到现金时, 支付现金时) 的现金流量项目建议。"""
    return {'suffix': suffix, 'name': name, 'aux': aux, 'req': req, 'key': key, 'cf': cf, 'children': children or []}


WAGE_CF = ('CF05', 'CF05')

# ---------------------------------------------------------------- 两种准则共用的二级科目
COMMON_SUBS = {
    'other_money': [S('01', '微信', key='wechat'), S('02', '支付宝', key='alipay')],
    'other_ar': [S('01', '员工借款', '员工', 1, 'emp_loan', ('CF03', 'CF07')),
                 S('02', '押金及保证金', '供应商', 0, 'deposit_paid'),
                 S('99', '其他', key='other_ar_misc')],
    'fa': [S('01', '房屋及建筑物'), S('02', '运输设备', key='fa_transport'),
           S('03', '办公及电子设备', key='fa_office'), S('04', '机器设备')],
    'accum_depr': [S('01', '房屋及建筑物'), S('02', '运输设备'), S('03', '办公及电子设备', key='depr_office'),
                   S('04', '机器设备')],
    'payroll': [S('01', '工资', key='wages'), S('02', '社会保险费', key='social_ins'), S('03', '住房公积金', key='housing_fund'),
                S('04', '职工福利费'), S('05', '工会经费和职工教育经费')],
    'tax': [
        S('01', '应交增值税', key='vat', children=[
            S('01', '进项税额', key='vat_in', cf=('CF04', 'CF04')),
            S('02', '销项税额', key='vat_out', cf=('CF01', 'CF01')),
            S('03', '进项税额转出', key='vat_in_out'),
            S('04', '转出未交增值税', key='vat_transfer'),
            S('05', '已交税金', key='vat_paid'),
        ]),
        S('02', '未交增值税', key='vat_unpaid'),
        S('03', '简易计税', key='vat_simple'),
        S('04', '应交城市维护建设税', key='city_tax'),
        S('05', '应交教育费附加', key='edu'),
        S('06', '应交地方教育附加', key='local_edu'),
        S('07', '应交企业所得税', key='cit'),
        S('08', '应交个人所得税', key='iit'),
        S('09', '应交房产税'),
        S('10', '应交城镇土地使用税'),
        S('11', '应交车船税'),
        S('12', '应交印花税'),
    ],
    'other_ap': [S('01', '押金及保证金', '客户', 0, 'deposit_recv'), S('02', '代收代付款', key='collect'),
                 S('99', '其他', key='other_ap_misc')],
    'dist': [S('01', '提取法定盈余公积', key='surplus_extract'), S('02', '应付现金股利或利润', key='div_dist'),
             S('99', '未分配利润', key='retained')],
    'deferred_income': [S('01', '政府补助', key='deferred_grant')],
    'taxes': [S('01', '城市维护建设税', key='tx_city'), S('02', '教育费附加', key='tx_edu'),
              S('03', '地方教育附加', key='tx_local_edu'), S('04', '房产税'), S('05', '城镇土地使用税'),
              S('06', '车船税'), S('07', '印花税')],
    'selling': [S('01', '职工薪酬', key='sell_wage', cf=WAGE_CF), S('02', '广告宣传费'),
                S('03', '平台佣金及推广费', key='commission'), S('99', '其他')],
    'admin': [S('01', '职工薪酬', key='admin_wage', cf=WAGE_CF), S('02', '办公费', key='office'),
              S('03', '租赁费及水电费', key='rent_utility'), S('04', '折旧费', key='admin_depr'),
              S('05', '业务招待费'), S('06', '差旅费'), S('07', '长期待摊费用摊销'), S('08', '中介及咨询费'),
              S('99', '其他')],
    'finance': [S('01', '利息支出', key='fin_interest', cf=('CF25', 'CF25')),
                S('02', '利息收入', key='fin_income', cf=('CF03', 'CF03')),
                S('03', '手续费', key='fin_fee')],
}

ENTERPRISE_SUBS = {
    'other_income': [S('01', '政府补助', key='gov_grant', cf=('CF03', 'CF03')), S('02', '增值税加计抵减'),
                     S('03', '个税手续费返还'), S('99', '其他')],
    'non_op_inc': [S('01', '罚没及违约金收入'), S('02', '无法支付的应付款项'), S('99', '其他')],
    'non_op_exp': [S('01', '罚款及滞纳金'), S('02', '非常损失'), S('03', '公益性捐赠支出'), S('99', '其他')],
}
SMALL_SUBS = {
    'non_op_inc': [S('01', '政府补助', key='gov_grant', cf=('CF03', 'CF03')),
                   S('02', '非流动资产处置净收益', key='disposal_gain', cf=('CF13', 'CF13')),
                   S('03', '罚没及违约金收入'), S('99', '其他')],
    'non_op_exp': [S('01', '非流动资产处置净损失', key='disposal_loss', cf=('CF13', 'CF13')),
                   S('02', '罚款及滞纳金'), S('03', '坏账损失'), S('04', '非常损失'), S('05', '公益性捐赠支出'),
                   S('99', '其他')],
}
# 企业会计准则下，资产处置收益和损失都记“资产处置损益”
ENTERPRISE_ALIASES = {'disposal_gain': 'disposal', 'disposal_loss': 'disposal'}

# ---------------------------------------------------------------- 现金流量项目
ENTERPRISE_CF = [
    ('CF01', '销售商品、提供劳务收到的现金', '经营活动', '流入', 1),
    ('CF02', '收到的税费返还', '经营活动', '流入', 2),
    ('CF03', '收到其他与经营活动有关的现金', '经营活动', '流入', 3),
    ('CF04', '购买商品、接受劳务支付的现金', '经营活动', '流出', 4),
    ('CF05', '支付给职工以及为职工支付的现金', '经营活动', '流出', 5),
    ('CF06', '支付的各项税费', '经营活动', '流出', 6),
    ('CF07', '支付其他与经营活动有关的现金', '经营活动', '流出', 7),
    ('CF11', '收回投资收到的现金', '投资活动', '流入', 11),
    ('CF12', '取得投资收益收到的现金', '投资活动', '流入', 12),
    ('CF13', '处置固定资产、无形资产和其他长期资产收回的现金净额', '投资活动', '流入', 13),
    ('CF15', '收到其他与投资活动有关的现金', '投资活动', '流入', 15),
    ('CF16', '购建固定资产、无形资产和其他长期资产支付的现金', '投资活动', '流出', 16),
    ('CF17', '投资支付的现金', '投资活动', '流出', 17),
    ('CF19', '支付其他与投资活动有关的现金', '投资活动', '流出', 19),
    ('CF21', '吸收投资收到的现金', '筹资活动', '流入', 21),
    ('CF22', '取得借款收到的现金', '筹资活动', '流入', 22),
    ('CF23', '收到其他与筹资活动有关的现金', '筹资活动', '流入', 23),
    ('CF24', '偿还债务支付的现金', '筹资活动', '流出', 24),
    ('CF25', '分配股利、利润或偿付利息支付的现金', '筹资活动', '流出', 25),
    ('CF26', '支付其他与筹资活动有关的现金', '筹资活动', '流出', 26),
    ('CF99', '现金内部划转（不计入现金流量）', '不计', '不计', 99),
]
SMALL_CF = [
    ('CF01', '销售产成品、商品、提供劳务收到的现金', '经营活动', '流入', 1),
    ('CF03', '收到其他与经营活动有关的现金', '经营活动', '流入', 3),
    ('CF04', '购买原材料、商品、接受劳务支付的现金', '经营活动', '流出', 4),
    ('CF05', '支付的职工薪酬', '经营活动', '流出', 5),
    ('CF06', '支付的税费', '经营活动', '流出', 6),
    ('CF07', '支付其他与经营活动有关的现金', '经营活动', '流出', 7),
    ('CF11', '收回短期投资、长期债券投资和长期股权投资收到的现金', '投资活动', '流入', 11),
    ('CF12', '取得投资收益收到的现金', '投资活动', '流入', 12),
    ('CF13', '处置固定资产、无形资产和其他非流动资产收回的现金净额', '投资活动', '流入', 13),
    ('CF17', '短期投资、长期债券投资和长期股权投资支付的现金', '投资活动', '流出', 15),
    ('CF16', '购建固定资产、无形资产和其他非流动资产支付的现金', '投资活动', '流出', 16),
    ('CF22', '取得借款收到的现金', '筹资活动', '流入', 21),
    ('CF21', '吸收投资者投资收到的现金', '筹资活动', '流入', 22),
    ('CF24', '偿还借款本金支付的现金', '筹资活动', '流出', 24),
    ('CF25', '偿还借款利息支付的现金', '筹资活动', '流出', 25),
    ('CF27', '分配利润支付的现金', '筹资活动', '流出', 27),
    ('CF99', '现金内部划转（不计入现金流量）', '不计', '不计', 99),
]

# 对方科目（关键字）→ (收到现金时, 支付现金时) 的现金流量项目（企业准则编码）
CF_SUGGEST = {
    'main_rev': ('CF01', 'CF01'), 'other_rev': ('CF01', 'CF01'), 'ar': ('CF01', 'CF01'), 'adv': ('CF01', 'CF01'),
    'contract_liab': ('CF01', 'CF01'), 'notes_rec': ('CF01', 'CF01'),
    'other_ap': ('CF03', 'CF07'), 'other_ar': ('CF03', 'CF07'),
    'ap': ('CF04', 'CF04'), 'prepay': ('CF04', 'CF04'), 'notes_pay': ('CF04', 'CF04'), 'materials': ('CF04', 'CF04'),
    'goods': ('CF04', 'CF04'), 'low_value': ('CF04', 'CF04'), 'main_cost': ('CF04', 'CF04'),
    'other_cost': ('CF04', 'CF04'),
    'payroll': ('CF05', 'CF05'),
    'tax': ('CF02', 'CF06'), 'taxes': ('CF02', 'CF06'), 'income_tax': ('CF02', 'CF06'),
    'selling': ('CF03', 'CF07'), 'admin': ('CF03', 'CF07'), 'finance': ('CF03', 'CF07'),
    'other_income': ('CF03', 'CF07'), 'non_op_inc': ('CF03', 'CF07'), 'non_op_exp': ('CF03', 'CF07'),
    'deferred_income': ('CF03', 'CF03'),
    'fa': ('CF13', 'CF16'), 'cip': ('CF13', 'CF16'), 'intangible': ('CF13', 'CF16'), 'ltpe': ('CF13', 'CF16'),
    'fa_clear': ('CF13', 'CF13'), 'disposal': ('CF13', 'CF13'),
    'trading_fa': ('CF11', 'CF17'), 'st_inv': ('CF11', 'CF17'), 'lt_bond': ('CF11', 'CF17'),
    'lt_equity': ('CF11', 'CF17'), 'invest_income': ('CF12', 'CF12'), 'div_rec': ('CF12', 'CF12'),
    'int_rec': ('CF12', 'CF12'),
    'st_loan': ('CF22', 'CF24'), 'lt_loan': ('CF22', 'CF24'), 'int_pay': ('CF23', 'CF25'),
    'div_pay': ('CF23', 'CF25'), 'dist': ('CF21', 'CF25'), 'lt_ap': ('CF23', 'CF26'),
    'capital': ('CF21', 'CF26'), 'cap_reserve': ('CF21', 'CF26'),
    'cash': ('CF99', 'CF99'), 'bank': ('CF99', 'CF99'), 'other_money': ('CF99', 'CF99'),
}
# 小企业现金流量表没有的项目，换成最接近的项目
SMALL_CF_MAP = {'CF02': 'CF03', 'CF15': 'CF13', 'CF19': 'CF16', 'CF23': 'CF22', 'CF26': 'CF24'}
SMALL_CF_KEY_OVERRIDE = {'div_pay': ('CF22', 'CF27'), 'dist': ('CF21', 'CF27'), 'int_pay': ('CF22', 'CF25')}


# ---------------------------------------------------------------- 通用凭证模板
# 模板行：(摘要, 科目关键字, 借/贷, 金额规则)；金额规则见 vouchers 模板说明（T / NET:13 / TAX:13 / 空）
def common_templates(wage_cost_keys):
    wage_lines = [('计提本月工资', k, '借', '') for k in wage_cost_keys] + [('计提本月工资', 'admin_wage', '借', ''),
                                                                         ('计提本月工资', 'wages', '贷', '')]
    return [
        ('收到客户欠款', [('收到客户欠款', 'bank', '借', 'T'), ('收到客户欠款', 'ar', '贷', 'T')]),
        ('支付供应商欠款', [('支付供应商欠款', 'ap', '借', 'T'), ('支付供应商欠款', 'bank', '贷', 'T')]),
        ('支付办公费', [('支付办公费', 'office', '借', 'T'), ('支付办公费', 'bank', '贷', 'T')]),
        ('计提本月工资', wage_lines),
        ('发放工资', [('发放工资', 'wages', '借', 'T'), ('发放工资', 'bank', '贷', 'T')]),
        ('银行手续费', [('银行手续费', 'fin_fee', '借', 'T'), ('银行手续费', 'bank', '贷', 'T')]),
        ('从银行提取现金', [('提取备用金', 'cash', '借', 'T'), ('提取备用金', 'bank', '贷', 'T')]),
        ('收到政府补助', [('收到政府补助', 'bank', '借', 'T'), ('收到政府补助', 'gov_grant', '贷', 'T')]),
        ('月末转出未交增值税', [('转出本月未交增值税', 'vat_transfer', '借', 'T'),
                         ('转出本月未交增值税', 'vat_unpaid', '贷', 'T')]),
        ('计提附加税费', [('计提城建税', 'tx_city', '借', ''), ('计提教育费附加', 'tx_edu', '借', ''),
                    ('计提地方教育附加', 'tx_local_edu', '借', ''), ('计提城建税', 'city_tax', '贷', ''),
                    ('计提教育费附加', 'edu', '贷', ''), ('计提地方教育附加', 'local_edu', '贷', '')]),
        ('缴纳上月税费', [('缴纳增值税', 'vat_unpaid', '借', ''), ('缴纳城建税', 'city_tax', '借', ''),
                    ('缴纳教育费附加', 'edu', '借', ''), ('缴纳地方教育附加', 'local_edu', '借', ''),
                    ('缴纳税费', 'bank', '贷', '')]),
    ]


def sale(name, summary, rev_key, rate, cash_key='bank'):
    """含税收款模板：借 现金类，贷 收入（不含税）、销项税额。rate=0 表示免税。"""
    if not rate:
        return (name, [(summary, cash_key, '借', 'T'), (summary, rev_key, '贷', 'T')])
    return (name, [(summary, cash_key, '借', 'T'), (summary, rev_key, '贷', 'NET:%s' % rate),
                   (summary, 'vat_out', '贷', 'TAX:%s' % rate)])


def buy(name, summary, cost_key, rate, credit_key='bank'):
    """取得专票的采购 / 费用模板：借 成本费用（不含税）、进项税额，贷 银行或应付。rate=0 表示无可抵扣进项。"""
    if not rate:
        return (name, [(summary, cost_key, '借', 'T'), (summary, credit_key, '贷', 'T')])
    return (name, [(summary, cost_key, '借', 'NET:%s' % rate), (summary, 'vat_in', '借', 'TAX:%s' % rate),
                   (summary, credit_key, '贷', 'T')])


def vehicle_fa(label):
    """有营运车辆的行业：固定资产、累计折旧的第一个明细是车辆，按车辆辅助核算
    （固定资产必选车辆；累计折旧可选车辆，系统计提折旧时自动按车辆分别记账）。"""
    return {
        'fa': [S('01', '运输设备—' + label, '车辆', 1, 'vehicle_fa'), S('02', '房屋及建筑物'),
               S('03', '办公及电子设备', key='fa_office'), S('04', '其他设备')],
        'accum_depr': [S('01', label, '车辆', 0, 'vehicle_depr'), S('02', '房屋及建筑物'),
                       S('03', '办公及电子设备', key='depr_office'), S('04', '其他设备')],
    }


# 有车辆的行业：资产处置损益、固定资产清理也可以按车辆记账
VEHICLE_AUX_OVERRIDES = {'disposal': ('车辆', 0), 'fa_clear': ('车辆', 0)}

# ---------------------------------------------------------------- 行业
INDUSTRIES = {}


def industry(code, name, desc, subs, templates, features=(), aux_types=(), wage_cost=(), aux_overrides=None,
             vehicle_label='车辆'):
    INDUSTRIES[code] = {'code': code, 'name': name, 'desc': desc, 'subs': subs, 'templates': templates,
                        'features': list(features), 'aux_types': list(aux_types), 'wage_cost': list(wage_cost),
                        'aux_overrides': aux_overrides or {}, 'vehicle_label': vehicle_label}


# 1. 汽车租赁
industry(
    'car_rental', '汽车租赁', '短租、长租、带驾。含车辆台账、自动计提折旧、单车盈利分析。租赁收入按 13% 预置。',
    dict(vehicle_fa('租赁车辆'), **{
        'main_rev': [S('01', '短租租金收入', '车辆', 0, 'rent_short'), S('02', '长租租金收入', '车辆', 0, 'rent_long'),
                     S('03', '带驾服务收入', '车辆', 0, 'rent_driver')],
        'other_rev': [S('01', '超时及超里程费', '车辆', 0, 'rent_extra'), S('02', '油费及充电费', key='rent_fuel'),
                      S('03', '车损赔偿收入', '车辆', 0, 'rent_damage'), S('99', '其他')],
        'main_cost': [S('01', '车辆折旧', key='depr_exp'), S('02', '车辆保险费', '车辆', 0, 'veh_ins'),
                      S('03', '维修保养费', '车辆', 0, 'veh_repair'), S('04', '燃油及充电费', '车辆', 0, 'veh_fuel'),
                      S('05', '年检及GPS费', '车辆', 0, 'veh_check'), S('06', '停车及洗车费', key='veh_park'),
                      S('07', '司机及调度人员薪酬', key='cost_wage', cf=WAGE_CF), S('99', '其他')],
        'materials': [S('01', '轮胎'), S('02', '配件及耗材')],
        'other_ar': [S('01', '代垫违章罚款', '客户', 0, 'fine_advance'), S('02', '应收保险理赔款', '车辆', 0, 'ins_claim'),
                     S('03', '员工借款', '员工', 1, 'emp_loan', ('CF03', 'CF07')), S('99', '其他')],
        'other_ap': [S('01', '租车押金', '客户', 0, 'deposit_recv'), S('02', '违章押金', '客户', 0, 'fine_deposit'),
                     S('99', '其他')],
    }),
    [sale('收取租金（银行，含税13%）', '收到租金', 'rent_short', 13),
     sale('收取租金（微信，含税13%）', '收到租金', 'rent_short', 13, 'wechat'),
     ('收取租车押金', [('收到租车押金', 'bank', '借', 'T'), ('收到租车押金', 'deposit_recv', '贷', 'T')]),
     ('退还租车押金', [('退还租车押金', 'deposit_recv', '借', 'T'), ('退还租车押金', 'bank', '贷', 'T')]),
     ('代垫违章罚款', [('代客户缴纳违章罚款', 'fine_advance', '借', 'T'), ('代客户缴纳违章罚款', 'bank', '贷', 'T')]),
     ('违章押金抵扣代垫罚款', [('违章押金抵扣罚款', 'fine_deposit', '借', 'T'), ('违章押金抵扣罚款', 'fine_advance', '贷', 'T')]),
     buy('支付维修保养费（13%专票）', '支付车辆维修保养费', 'veh_repair', 13),
     buy('支付车辆保险费（6%专票）', '支付车辆保险费', 'veh_ins', 6),
     buy('购入车辆（13%专票，挂应付）', '购入车辆', 'vehicle_fa', 13, 'ap'),
     buy('支付平台佣金（6%专票）', '支付平台佣金', 'commission', 6),
     ('收到保险理赔款', [('收到保险公司理赔款', 'bank', '借', 'T'), ('收到保险公司理赔款', 'ins_claim', '贷', 'T')])],
    features=['vehicles'], wage_cost=['cost_wage'], aux_overrides=VEHICLE_AUX_OVERRIDES, vehicle_label='租赁车辆')

# 2. 旅客运输
industry(
    'passenger', '旅客运输', '班线客运、旅游包车、定制客运。含车辆台账、自动折旧、单车盈利，增加“线路”辅助核算。客运收入按 9% 预置。',
    dict(vehicle_fa('营运车辆'), **{
        'main_rev': [S('01', '客票收入', '线路', 0, 'ticket'), S('02', '包车收入', '车辆', 0, 'charter'),
                     S('03', '行包托运收入', key='luggage'), S('04', '定制客运收入', '线路', 0, 'custom_bus')],
        'other_rev': [S('01', '车身广告收入', key='ad_income'), S('02', '车辆出租收入'), S('99', '其他')],
        'main_cost': [S('01', '车辆折旧', key='depr_exp'), S('02', '燃料费', '车辆', 0, 'veh_fuel'),
                      S('03', '路桥费', '车辆', 0, 'toll'), S('04', '驾乘人员薪酬', key='cost_wage', cf=WAGE_CF),
                      S('05', '车辆保险费', '车辆', 0, 'veh_ins'), S('06', '维修保养费', '车辆', 0, 'veh_repair'),
                      S('07', '站务费及车站服务费', key='station_fee'), S('08', '承运人责任险'),
                      S('09', '年检及GPS费', '车辆', 0, 'veh_check'), S('99', '其他')],
        'materials': [S('01', '燃料'), S('02', '轮胎'), S('03', '配件及耗材')],
        'other_ap': [S('01', '代收票款', key='ticket_collect'), S('02', '押金及保证金', '客户', 0, 'deposit_recv'),
                     S('99', '其他')],
    }),
    [sale('收到客票收入（含税9%）', '收到客票收入', 'ticket', 9),
     sale('收到包车款（含税9%）', '收到包车款', 'charter', 9),
     buy('支付燃料费（13%专票）', '支付燃料费', 'veh_fuel', 13),
     ('支付路桥费', [('支付路桥费', 'toll', '借', 'T'), ('支付路桥费', 'bank', '贷', 'T')]),
     buy('支付维修保养费（13%专票）', '支付车辆维修保养费', 'veh_repair', 13),
     buy('支付车辆保险费（6%专票）', '支付车辆保险费', 'veh_ins', 6),
     buy('支付车站服务费（6%专票）', '支付车站服务费', 'station_fee', 6),
     buy('购入车辆（13%专票，挂应付）', '购入车辆', 'vehicle_fa', 13, 'ap')],
    features=['vehicles'], aux_types=['线路'], wage_cost=['cost_wage'], aux_overrides=VEHICLE_AUX_OVERRIDES,
    vehicle_label='营运车辆')

# 3. 道路货物运输
industry(
    'freight', '道路货物运输', '整车、零担、城配运输。含车辆台账、自动折旧、单车盈利。运输收入按 9% 预置。',
    dict(vehicle_fa('营运车辆'), **{
        'main_rev': [S('01', '运输收入', '车辆', 0, 'freight_rev'), S('02', '装卸搬运收入', key='handling_rev'),
                     S('03', '仓储服务收入', key='storage_rev')],
        'other_rev': [S('01', '车辆出租收入'), S('99', '其他')],
        'main_cost': [S('01', '车辆折旧', key='depr_exp'), S('02', '燃料费', '车辆', 0, 'veh_fuel'),
                      S('03', '路桥费', '车辆', 0, 'toll'), S('04', '司机薪酬', key='cost_wage', cf=WAGE_CF),
                      S('05', '车辆保险费', '车辆', 0, 'veh_ins'), S('06', '维修保养费', '车辆', 0, 'veh_repair'),
                      S('07', '外包运费', key='outsourced'), S('08', '装卸费'), S('99', '其他')],
        'materials': [S('01', '燃料'), S('02', '轮胎'), S('03', '配件及耗材')],
    }),
    [sale('收到运费（含税9%）', '收到运费', 'freight_rev', 9),
     ('开票确认运费（挂应收）', [('确认运输收入', 'ar', '借', 'T'), ('确认运输收入', 'freight_rev', '贷', 'NET:9'),
                          ('确认运输收入', 'vat_out', '贷', 'TAX:9')]),
     buy('支付燃料费（13%专票）', '支付燃料费', 'veh_fuel', 13),
     ('支付路桥费', [('支付路桥费', 'toll', '借', 'T'), ('支付路桥费', 'bank', '贷', 'T')]),
     buy('支付外包运费（9%专票）', '支付外包运费', 'outsourced', 9),
     buy('支付维修保养费（13%专票）', '支付车辆维修保养费', 'veh_repair', 13),
     buy('购入车辆（13%专票，挂应付）', '购入车辆', 'vehicle_fa', 13, 'ap')],
    features=['vehicles'], wage_cost=['cost_wage'], aux_overrides=VEHICLE_AUX_OVERRIDES, vehicle_label='营运车辆')

# 4. 居家养老服务
industry(
    'elderly_care', '居家养老服务', '上门服务、助餐、日间照料、康复护理。增加“服务对象”“服务站点”辅助核算，'
    '包含政府购买服务和运营补贴。符合条件的养老服务可以免征增值税，收入模板按免税预置。',
    {
        'main_rev': [S('01', '居家上门服务收入', '服务对象', 0, 'care_home'), S('02', '助餐服务收入', '服务站点', 0, 'care_meal'),
                     S('03', '日间照料收入', '服务站点', 0, 'care_day'), S('04', '康复护理服务收入', '服务对象', 0, 'care_rehab'),
                     S('05', '政府购买服务收入', key='care_gov')],
        'other_rev': [S('01', '场地及设备出租收入'), S('02', '助老用品销售收入', key='care_goods'), S('99', '其他')],
        'main_cost': [S('01', '护理及服务人员薪酬', key='cost_wage', cf=WAGE_CF), S('02', '餐食及食材成本', key='meal_cost'),
                      S('03', '服务耗材及用品', key='care_supplies'), S('04', '场地租金及物业费', key='site_rent'),
                      S('05', '水电燃气费', key='site_utility'), S('06', '设施设备折旧', key='depr_exp'),
                      S('07', '服务车辆费用'), S('08', '外包服务费', key='care_outsourced'), S('99', '其他')],
        'materials': [S('01', '食材', key='food'), S('02', '护理耗材'), S('03', '助老用品')],
        'adv': [],
        'other_ap': [S('01', '服务对象押金及预存款', '服务对象', 0, 'deposit_recv'), S('02', '代收代付款', key='collect'),
                     S('99', '其他')],
    },
    [sale('收到上门服务费（免税）', '收到上门服务费', 'care_home', 0),
     sale('收到助餐费（免税，微信）', '收到助餐费', 'care_meal', 0, 'wechat'),
     sale('收到日间照料费（免税）', '收到日间照料费', 'care_day', 0),
     sale('收到政府购买服务款', '收到政府购买服务款', 'care_gov', 0),
     ('收到服务对象预存款', [('收到预存款', 'bank', '借', 'T'), ('收到预存款', 'deposit_recv', '贷', 'T')]),
     ('采购食材', [('采购食材', 'food', '借', 'T'), ('采购食材', 'bank', '贷', 'T')]),
     ('领用食材结转餐食成本', [('结转餐食成本', 'meal_cost', '借', 'T'), ('结转餐食成本', 'food', '贷', 'T')]),
     ('支付场地租金', [('支付场地租金', 'site_rent', '借', 'T'), ('支付场地租金', 'bank', '贷', 'T')])],
    aux_types=['服务对象', '服务站点'], wage_cost=['cost_wage'],
    aux_overrides={'adv': ('服务对象', 0)})

# 5. 商贸（批发零售）
industry(
    'trade', '商贸（批发零售）', '商品购销。包含库存商品、销售成本结转模板。销售按 13% 预置。',
    {
        'main_rev': [S('01', '商品销售收入', '客户', 0, 'sales')],
        'other_rev': [S('01', '材料销售收入'), S('02', '租金收入'), S('99', '其他')],
        'main_cost': [S('01', '商品销售成本', key='cogs')],
        'other_cost': [S('01', '材料销售成本'), S('99', '其他')],
        'goods': [S('01', '库存商品', key='goods_main')],
    },
    [sale('销售商品（银行收款，含税13%）', '销售商品', 'sales', 13),
     ('销售商品（挂应收，含税13%）', [('销售商品', 'ar', '借', 'T'), ('销售商品', 'sales', '贷', 'NET:13'),
                            ('销售商品', 'vat_out', '贷', 'TAX:13')]),
     buy('采购商品（13%专票，挂应付）', '采购商品', 'goods_main', 13, 'ap'),
     buy('采购商品（13%专票，银行付款）', '采购商品', 'goods_main', 13),
     ('结转本月销售成本', [('结转销售成本', 'cogs', '借', 'T'), ('结转销售成本', 'goods_main', '贷', 'T')])],
    wage_cost=[])

# 6. 餐饮服务
industry(
    'catering', '餐饮服务', '堂食、外卖。增加“门店”辅助核算。餐饮服务按 6% 预置。',
    {
        'main_rev': [S('01', '餐饮服务收入', '门店', 0, 'dine'), S('02', '外卖收入', '门店', 0, 'takeaway'),
                     S('03', '外带食品销售收入', '门店', 0, 'food_sale')],
        'main_cost': [S('01', '食材成本', '门店', 0, 'food_cost'), S('02', '燃料及能源', key='energy'),
                      S('03', '厨房及服务人员薪酬', key='cost_wage', cf=WAGE_CF), S('04', '餐具及低值易耗品'),
                      S('99', '其他')],
        'materials': [S('01', '食材', key='food'), S('02', '调料'), S('03', '酒水饮料'), S('04', '包装物')],
    },
    [sale('收到餐饮收入（微信，含税6%）', '收到餐饮收入', 'dine', 6, 'wechat'),
     sale('收到餐饮收入（银行，含税6%）', '收到餐饮收入', 'dine', 6),
     sale('外卖平台结算（含税6%）', '外卖平台结算', 'takeaway', 6),
     ('采购食材', [('采购食材', 'food', '借', 'T'), ('采购食材', 'bank', '贷', 'T')]),
     ('领用食材结转成本', [('结转食材成本', 'food_cost', '借', 'T'), ('结转食材成本', 'food', '贷', 'T')]),
     buy('支付平台佣金（6%专票）', '支付平台佣金', 'commission', 6)],
    aux_types=['门店'], wage_cost=['cost_wage'])

# 7. 物业管理
industry(
    'property', '物业管理', '住宅、商业物业。增加“项目”（小区）辅助核算。物业服务按 6% 预置，车位出租按 9% 预置。',
    {
        'main_rev': [S('01', '物业服务费收入', '项目', 0, 'pm_fee'), S('02', '停车服务收入', '项目', 0, 'parking'),
                     S('03', '有偿维修服务收入', '项目', 0, 'pm_repair')],
        'other_rev': [S('01', '场地及广告位出租收入'), S('99', '其他')],
        'main_cost': [S('01', '物业人员薪酬', key='cost_wage', cf=WAGE_CF), S('02', '保洁绿化费', key='cleaning'),
                      S('03', '安保费'), S('04', '公共水电能耗', key='public_energy'),
                      S('05', '设施设备维修保养', key='facility_repair'), S('06', '外包服务费'), S('99', '其他')],
        'other_ap': [S('01', '代收水电费', key='collect_utility'), S('02', '装修押金', '客户', 0, 'deposit_recv'),
                     S('03', '代管维修基金'), S('99', '其他')],
    },
    [sale('收到物业费（含税6%）', '收到物业费', 'pm_fee', 6),
     sale('收到停车费（含税9%）', '收到停车费', 'parking', 9),
     ('代收业主水电费', [('代收水电费', 'bank', '借', 'T'), ('代收水电费', 'collect_utility', '贷', 'T')]),
     ('代缴水电费', [('代缴水电费', 'collect_utility', '借', 'T'), ('代缴水电费', 'bank', '贷', 'T')]),
     buy('支付保洁绿化外包费（6%专票）', '支付保洁绿化费', 'cleaning', 6),
     buy('支付公共水电费（13%专票）', '支付公共水电费', 'public_energy', 13)],
    aux_types=['项目'], wage_cost=['cost_wage'])

# 8. 现代服务业
industry(
    'service', '现代服务业（咨询、技术、设计等）', '咨询、技术服务、设计等。增加“项目”辅助核算。服务收入按 6% 预置。',
    {
        'main_rev': [S('01', '咨询服务收入', '项目', 0, 'consult'), S('02', '技术服务收入', '项目', 0, 'tech'),
                     S('03', '设计服务收入', '项目', 0, 'design')],
        'main_cost': [S('01', '项目人员薪酬', '项目', 0, 'cost_wage', WAGE_CF), S('02', '外包及劳务费', '项目', 0, 'outsourced'),
                      S('03', '项目差旅费', '项目', 0), S('04', '项目材料及耗材', '项目', 0), S('99', '其他')],
    },
    [sale('收到服务费（含税6%）', '收到服务费', 'consult', 6),
     ('开票确认服务收入（挂应收）', [('确认服务收入', 'ar', '借', 'T'), ('确认服务收入', 'consult', '贷', 'NET:6'),
                            ('确认服务收入', 'vat_out', '贷', 'TAX:6')]),
     buy('支付外包服务费（6%专票）', '支付外包服务费', 'outsourced', 6)],
    aux_types=['项目'], wage_cost=['cost_wage'])

# 9. 通用
industry(
    'general', '通用（其他行业）', '只预置准则规定的常用科目和通用凭证模板，可以按需要自行增加明细科目。',
    {'main_rev': [S('01', '主营业务收入', key='rev_main')], 'main_cost': [S('01', '主营业务成本', key='cost_main')]},
    [sale('收到销售款（含税13%）', '收到销售款', 'rev_main', 13),
     sale('收到服务费（含税6%）', '收到服务费', 'rev_main', 6)],
    wage_cost=[])

INDUSTRY_ORDER = ['car_rental', 'passenger', 'freight', 'elderly_care', 'trade', 'catering', 'property', 'service',
                  'general']


def options():
    return {
        'standards': [{'code': k, 'name': v} for k, v in STANDARDS.items()],
        'industries': [{'code': c, 'name': INDUSTRIES[c]['name'], 'desc': INDUSTRIES[c]['desc']} for c in INDUSTRY_ORDER],
    }


# ---------------------------------------------------------------- 生成账套数据

def build(standard, industry_code):
    if standard not in STANDARDS:
        raise ValueError('未知的会计准则')
    ind = INDUSTRIES.get(industry_code)
    if not ind:
        raise ValueError('未知的行业')
    base = ENTERPRISE_L1 if standard == 'enterprise' else SMALL_L1
    subs = dict(COMMON_SUBS)
    subs.update(ENTERPRISE_SUBS if standard == 'enterprise' else SMALL_SUBS)
    for k, v in ind['subs'].items():
        subs[k] = v

    aux_types = list(BASE_AUX_TYPES)
    if 'vehicles' in ind['features']:
        aux_types.append('车辆')
    for t in ind['aux_types']:
        if t not in aux_types:
            aux_types.append(t)

    accounts = []      # (code, name, category, direction, aux, req, is_cash)
    keymap = {}
    hints = {}         # 编码 -> 现金流量建议
    for code, key, name, cat, direction, aux, req, cash in base:
        keymap[key] = code
        accounts.append([code, name, cat, direction, aux, req, cash])

        def add_subs(parent, items, level_cat, level_dir, cash_flag):
            for s in items:
                c = parent + s['suffix']
                accounts.append([c, s['name'], level_cat, level_dir, s['aux'], s['req'], cash_flag])
                if s['key']:
                    keymap[s['key']] = c
                if s['cf']:
                    hints[c] = s['cf']
                if s['children']:
                    add_subs(c, s['children'], level_cat, level_dir, cash_flag)
        if subs.get(key):
            # 有下级科目时，辅助核算放到下级科目上（上级不再记账）
            add_subs(code, subs[key], cat, direction, cash)
            if aux and key not in ('bank',):
                accounts[[a[0] for a in accounts].index(code)][4] = ''
                for a in accounts:
                    if a[0].startswith(code) and a[0] != code and not a[4]:
                        a[4], a[5] = aux, req
    if standard == 'enterprise':
        for alias, target in ENTERPRISE_ALIASES.items():
            if alias not in keymap and target in keymap:
                keymap[alias] = keymap[target]
    # 行业对某些科目的辅助核算设置
    by_code = {a[0]: a for a in accounts}
    for key, (aux, req) in ind['aux_overrides'].items():
        code = keymap.get(key)
        if code and code in by_code:
            for a in accounts:
                if a[0] == code or (a[0].startswith(code) and not any(x[0].startswith(a[0]) and x[0] != a[0] for x in accounts)):
                    a[4], a[5] = aux, req

    # 现金流量建议：按关键字找到编码，再叠加二级科目上的提示
    cf_suggest = {}
    for key, pair in CF_SUGGEST.items():
        if key in keymap:
            if standard == 'small':
                pair = SMALL_CF_KEY_OVERRIDE.get(key) or tuple(SMALL_CF_MAP.get(x, x) for x in pair)
            cf_suggest[keymap[key]] = list(pair)
    for code, pair in hints.items():
        if standard == 'small':
            pair = tuple(SMALL_CF_MAP.get(x, x) for x in pair)
        cf_suggest[code] = list(pair)
    cf_suggest[''] = ['CF03', 'CF07']

    # 凭证模板：只保留所有科目都能找到、且都是末级科目的模板
    codes = [a[0] for a in accounts]
    is_leaf = {c: not any(o != c and o.startswith(c) for o in codes) for c in codes}
    templates = []
    for name, lines in ind['templates'] + common_templates(ind['wage_cost']):
        out = []
        ok = True
        for summary, key, d, expr in lines:
            code = keymap.get(key)
            if not code or not is_leaf.get(code):
                ok = False
                break
            out.append({'summary': summary, 'account': code, 'dir': d, 'expr': expr})
        if ok:
            templates.append((name, out))

    return {
        'standard': standard,
        'industry': industry_code,
        'industry_name': ind['name'],
        'accounts': [tuple(a) for a in accounts],
        'keymap': keymap,
        'aux_types': aux_types,
        'preset_aux': [('银行账户', '01', '基本户')],
        'templates': templates,
        'cf_items': ENTERPRISE_CF if standard == 'enterprise' else SMALL_CF,
        'cf_suggest': cf_suggest,
        'features': ind['features'],
        'vehicle_label': ind['vehicle_label'],
    }


# ---------------------------------------------------------------- 旧版本（v1.3 及以前）汽车租赁账套的对照表
# 旧账套没有存关键字，第一次打开时用这张表补上（只保留账套里确实存在的科目）。
LEGACY_CAR_RENTAL_KEYMAP = {
    'cash': '1001', 'bank': '1002', 'other_money': '1012', 'wechat': '101201', 'alipay': '101202',
    'ar': '1122', 'prepay': '1123', 'other_ar': '1221', 'fine_advance': '122101', 'ins_claim': '122102',
    'emp_loan': '122103', 'materials': '1403', 'fa': '1601', 'vehicle_fa': '160101', 'fa_office': '160102',
    'accum_depr': '1602', 'vehicle_depr': '160201', 'depr_office': '160202', 'fa_clear': '1606', 'ltpe': '1801',
    'st_loan': '2001', 'ap': '2202', 'adv': '2203', 'payroll': '2211', 'wages': '221101', 'tax': '2221',
    'vat': '222101', 'vat_in': '22210101', 'vat_out': '22210102', 'vat_transfer': '22210103', 'vat_paid': '22210104',
    'vat_unpaid': '222102', 'vat_simple': '222103', 'city_tax': '222104', 'edu': '222105', 'local_edu': '222106',
    'cit': '222107', 'iit': '222108', 'int_pay': '2231', 'div_pay': '2232', 'other_ap': '2241',
    'deposit_recv': '224101', 'fine_deposit': '224102', 'lt_loan': '2501', 'lt_ap': '2701',
    'capital': '4001', 'cap_reserve': '4002', 'surplus': '4101', 'profit': '4103', 'dist': '4104',
    'surplus_extract': '410401', 'div_dist': '410402', 'retained': '410499',
    'main_rev': '6001', 'rent_short': '600101', 'rent_long': '600102', 'rent_driver': '600103',
    'other_rev': '6051', 'disposal': '6115', 'disposal_gain': '6115', 'disposal_loss': '6115', 'non_op_inc': '6301',
    'main_cost': '6401', 'depr_exp': '640101', 'veh_ins': '640102', 'veh_repair': '640103', 'veh_fuel': '640104',
    'cost_wage': '640107', 'taxes': '6403', 'tx_city': '640301', 'tx_edu': '640302', 'tx_local_edu': '640303',
    'selling': '6601', 'commission': '660101', 'admin': '6602', 'admin_wage': '660201', 'office': '660202',
    'admin_depr': '660204', 'finance': '6603', 'fin_interest': '660301', 'fin_income': '660302', 'fin_fee': '660303',
    'non_op_exp': '6711', 'income_tax': '6801',
}
LEGACY_AUX_TYPES = ['客户', '供应商', '车辆', '员工', '银行账户']
