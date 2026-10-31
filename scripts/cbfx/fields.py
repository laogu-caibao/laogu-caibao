"""规范字段表：一个字段 = 一个口径，三个来源各自映射过来。

flow=True 表示利润表/现金流量表科目（定期报告为年初累计口径，单季须差分）；
flow=False 表示资产负债表时点值。
pdf 为公告原文中的行标签（规范化后精确匹配，见 pdfparse.norm_label）。
"""

# (key, 中文名, 报表, flow, 东方财富字段, 新浪字段, PDF 标签别名)
FIELDS = [
    # ---- 利润表 ----
    ("rev_total", "营业总收入", "is", True, "TOTAL_OPERATE_INCOME", "BIZTOTINCO", ["营业总收入"]),
    ("rev", "营业收入", "is", True, "OPERATE_INCOME", "BIZINCO", ["营业收入", "营业收入合计"]),
    ("cost", "营业成本", "is", True, "OPERATE_COST", "BIZCOST", ["营业成本"]),
    ("tax_surcharge", "税金及附加", "is", True, "OPERATE_TAX_ADD", "BIZTAX", ["税金及附加"]),
    ("sell_exp", "销售费用", "is", True, "SALE_EXPENSE", "SALESEXPE", ["销售费用"]),
    ("admin_exp", "管理费用", "is", True, "MANAGE_EXPENSE", "MANAEXPE", ["管理费用"]),
    ("rd_exp", "研发费用", "is", True, "RESEARCH_EXPENSE", "DEVEEXPE", ["研发费用"]),
    ("fin_exp", "财务费用", "is", True, "FINANCE_EXPENSE", "FINEXPE", ["财务费用", "财务费用/收入", "财务/收入"]),
    ("int_exp", "利息费用", "is", True, "FE_INTEREST_EXPENSE", "INTERESTEXPENSE", ["利息费用"]),
    ("int_inc", "利息收入", "is", True, "FE_INTEREST_INCOME", "INTEINCOOPCOST", ["利息收入"]),
    ("other_inc", "其他收益", "is", True, "OTHER_INCOME", "OTHERINCO", ["其他收益"]),
    ("invest_inc", "投资收益", "is", True, "INVEST_INCOME", "INVEINCO", ["投资收益"]),
    ("fv_chg", "公允价值变动收益", "is", True, "FAIRVALUE_CHANGE_INCOME", "VALUECHGLOSS", ["公允价值变动收益"]),
    ("credit_impair", "信用减值损失", "is", True, "CREDIT_IMPAIRMENT_INCOME", "CREDITIMPLOSSEPROFIT", ["信用减值损失"]),
    ("asset_impair", "资产减值损失", "is", True, "ASSET_IMPAIRMENT_INCOME", "ASSEIMPALOSSPROFIT", ["资产减值损失"]),
    ("op_profit", "营业利润", "is", True, "OPERATE_PROFIT", "PERPROFIT", ["营业利润"]),
    ("total_profit", "利润总额", "is", True, "TOTAL_PROFIT", "TOTPROFIT", ["利润总额"]),
    ("income_tax", "所得税费用", "is", True, "INCOME_TAX", "INCOTAXEXPE", ["所得税费用"]),
    ("np", "净利润", "is", True, "NETPROFIT", "NETPROFIT", ["净利润"]),
    ("np_parent", "归母净利润", "is", True, "PARENT_NETPROFIT", "PARENETP",
     ["归属于母公司股东的净利润", "归属于母公司所有者的净利润", "归属于上市公司股东的净利润"]),
    ("minority_pl", "少数股东损益", "is", True, "MINORITY_INTEREST", "MINYSHARRIGH", ["少数股东损益"]),
    ("np_ded", "扣非归母净利润", "is", True, "DEDUCT_PARENT_NETPROFIT", None,
     ["归属于上市公司股东的扣除非经常性损益的净利润", "扣除非经常性损益后归属于上市公司股东的净利润",
      "归属于母公司股东的扣除非经常性损益后的净利润", "扣除非经常性损益后的归属于母公司股东净利润"]),
    # ---- 资产负债表 ----
    ("cash", "货币资金", "bs", False, "MONETARYFUNDS", "CURFDS", ["货币资金"]),
    ("notes_rec", "应收票据", "bs", False, "NOTE_RECE", "NOTESRECE", ["应收票据"]),
    ("ar", "应收账款", "bs", False, "ACCOUNTS_RECE", "ACCORECE", ["应收账款"]),
    ("rec_fin", "应收款项融资", "bs", False, "FINANCE_RECE", "RECFINANC", ["应收款项融资"]),
    ("prepay", "预付款项", "bs", False, "PREPAYMENT", "PREP", ["预付款项"]),
    ("other_rec", "其他应收款", "bs", False, "TOTAL_OTHER_RECE", "OTHERRECETOT", ["其他应收款"]),
    ("inv", "存货", "bs", False, "INVENTORY", "INVE", ["存货"]),
    ("contract_asset", "合同资产", "bs", False, "CONTRACT_ASSET", "CONTRACTASSET", ["合同资产"]),
    ("lt_equity_inv", "长期股权投资", "bs", False, "LONG_EQUITY_INVEST", "EQUIINVE", ["长期股权投资"]),
    ("fixed", "固定资产", "bs", False, "FIXED_ASSET", "FIXEDASSECLEATOT", ["固定资产"]),
    ("cip", "在建工程", "bs", False, "CIP", "CONSPROGTOT", ["在建工程"]),
    ("intangible", "无形资产", "bs", False, "INTANGIBLE_ASSET", "INTAASSET", ["无形资产"]),
    ("goodwill", "商誉", "bs", False, "GOODWILL", "GOODWILL", ["商誉"]),
    ("ta", "资产总计", "bs", False, "TOTAL_ASSETS", "TOTASSET", ["资产总计", "资产合计"]),
    ("st_loan", "短期借款", "bs", False, "SHORT_LOAN", "SHORTTERMBORR", ["短期借款"]),
    ("notes_pay", "应付票据", "bs", False, "NOTE_PAYABLE", "NOTESPAYA", ["应付票据"]),
    ("ap", "应付账款", "bs", False, "ACCOUNTS_PAYABLE", "ACCOPAYA", ["应付账款"]),
    ("adv_rec", "预收款项", "bs", False, "ADVANCE_RECEIVABLES", "ADVAPAYM", ["预收款项"]),
    ("contract_liab", "合同负债", "bs", False, "CONTRACT_LIAB", "CONTRACTLIAB", ["合同负债"]),
    ("ncl_1y", "一年内到期的非流动负债", "bs", False, "NONCURRENT_LIAB_1YEAR", "DUENONCLIAB", ["一年内到期的非流动负债"]),
    ("lt_loan", "长期借款", "bs", False, "LONG_LOAN", "LONGBORR", ["长期借款"]),
    ("bonds", "应付债券", "bs", False, "BOND_PAYABLE", "BDSPAYA", ["应付债券"]),
    ("lease_liab", "租赁负债", "bs", False, "LEASE_LIAB", "LEASELIAB", ["租赁负债"]),
    ("tl", "负债合计", "bs", False, "TOTAL_LIABILITIES", "TOTLIAB", ["负债合计"]),
    ("eq_parent", "归母所有者权益", "bs", False, "TOTAL_PARENT_EQUITY", "PARESHARRIGH",
     ["归属于母公司所有者权益合计", "归属于母公司股东权益合计"]),
    ("minority_eq", "少数股东权益", "bs", False, "MINORITY_EQUITY", "MINYSHARRIGH", ["少数股东权益"]),
    ("eq_total", "所有者权益合计", "bs", False, "TOTAL_EQUITY", "RIGHAGGR", ["所有者权益合计", "股东权益合计"]),
    ("undist", "未分配利润", "bs", False, "UNASSIGN_RPOFIT", "UNDIPROF", ["未分配利润"]),
    # ---- 现金流量表 ----
    ("sales_cash", "销售商品、提供劳务收到的现金", "cf", True, "SALES_SERVICES", "LABORGETCASH", ["销售商品、提供劳务收到的现金"]),
    ("ocf", "经营活动现金流量净额", "cf", True, "NETCASH_OPERATE", "MANANETR", ["经营活动产生的现金流量净额"]),
    ("capex", "购建长期资产支付的现金", "cf", True, "CONSTRUCT_LONG_ASSET", "ACQUASSETCASH",
     ["购建固定资产、无形资产和其他长期资产支付的现金"]),
    ("icf", "投资活动现金流量净额", "cf", True, "NETCASH_INVEST", "INVNETCASHFLOW", ["投资活动产生的现金流量净额"]),
    ("fcf_fin", "筹资活动现金流量净额", "cf", True, "NETCASH_FINANCE", "FINNETCFLOW", ["筹资活动产生的现金流量净额"]),
    ("div_int_paid", "分配股利、利润或偿付利息支付的现金", "cf", True, "ASSIGN_DIVIDEND_PORFIT", "DIVIPROFPAYCASH",
     ["分配股利、利润或偿付利息支付的现金"]),
    ("cce_end", "期末现金及现金等价物余额", "cf", False, "END_CCE", "FINALCASHBALA", ["期末现金及现金等价物余额"]),
]

BY_KEY = {f[0]: dict(key=f[0], name=f[1], stmt=f[2], flow=f[3], em=f[4], sina=f[5], pdf=f[6]) for f in FIELDS}
STMT_KEYS = {s: [f[0] for f in FIELDS if f[2] == s] for s in ("is", "bs", "cf")}

# 非一般工商企业：通用字段表不适用，先原样保留接口数据并显式标注
COMPANY_TYPES = {4: "general", 3: "bank", 2: "insurance", 1: "securities"}
COMPANY_TYPE_CN = {"general": "一般工商企业", "bank": "银行", "insurance": "保险", "securities": "证券"}
