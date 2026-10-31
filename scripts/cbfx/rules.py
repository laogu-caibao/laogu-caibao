"""规则手册 v0 的机器可读版本。阈值只在这里定义一次；references/规则手册.md 是它的人读说明，两者必须同步修改。"""
VERSION = "rules/0.3"

# ---- 分型 ----
CYCLICAL_KW = ("有色", "贵金属", "工业金属", "能源金属", "小金属", "稀土", "煤炭", "钢铁", "普钢", "特钢",
               "化工", "化学原料", "化学制品", "化纤", "农化", "石油", "石化", "炼化", "油气", "建材", "水泥",
               "玻璃", "航运", "海运", "养殖", "生猪", "造纸", "面板", "光伏", "硅料", "锂", "磷", "钛白粉")
REALESTATE_KW = ("房地产开发", "房地产-", "房地产业")
GROWTH_REV_YOY = 0.25          # Q3：营收（TTM）同比 >25% → 成长扩张
GROWTH_CIP_FIXED = 0.30        # Q3：在建工程 ÷ 固定资产 >30%
CYCLE_GM_SWING = 0.50          # Q2：年度毛利率峰谷差 ÷ 峰值 >50%
CYCLE_NP_DROP = -0.30          # Q2 数据判周期还需：期内至少一个年度归母同比 ≤ -30%（区分周期波动与趋势性降毛利）
CYCLE_MIN_YEARS = 5            # 用数据判周期至少要 5 个年度
D_RD_TO_REV = 0.30             # Q1：研发 ÷ 营收 >30% 且亏损，或营收 < 研发 → 技术未定型

ARCHETYPE_CN = {"A": "A 成熟稳定型", "B": "B 周期重资产型", "C": "C 成长扩张型", "D": "D 技术未定型",
                "BANK": "金融·银行", "INSURANCE": "金融·保险", "SECURITIES": "金融·券商", "RE": "地产"}

# ---- 分型复核条件（快检触发 → 建议重做深检） ----
RECHECK = {"rev_sq_yoy_abs": 0.50, "gm_sq_change_pp": 10.0}

# ---- 通用指标阈值：(健康条件, 预警条件)，单位与指标一致 ----
TH = {
    "np_ded_ratio": {"good": 0.90, "warn": 0.80, "src": "张 ≥90% 为佳；FRA <80% 预警"},
    "ocf_np": {"good_A": 1.2, "good": 1.0, "warn": 0.5, "src": "张 >1.2；FRA ≥1 健康、<0.5 预警"},
    "cash_rev": {"good": 1.0, "warn": 0.85, "src": "FRA"},
    "core_op": {"good": 0.90, "warn": 0.70, "src": "张"},
    "core_cash": {"good": 1.2, "warn": 1.0, "src": "张 1.2–1.5"},
    "ibd_ta": {"good": 0.25, "warn": 0.50, "src": "张 <25% 优、≥50% 关注"},
    "debt_ratio": {"good": 0.60, "warn": 0.70, "src": "FRA 制造业 <60%；>70% 预警"},
    "goodwill_eq": {"good": 0.10, "warn": 0.30, "src": "FRA"},
    "roe": {"good": 0.15, "warn": 0.08, "src": "FRA/唐"},
    "gm_yoy_pp": {"warn": -3.0, "src": "FRA 毛利率同比下滑 >3pct"},
    "ar_gap_pp": {"warn": 20.0, "src": "FRA/唐 #2"},
    "inv_gap_pp": {"warn": 20.0, "src": "唐 #3"},
    "runway_m": {"red": 12, "yellow": 18, "src": "唐 D 型现金续航"},
    "re_debt_ex_adv": {"warn": 0.70, "src": "三道红线"},
    "re_net_gearing": {"warn": 1.00, "src": "三道红线"},
    "re_cash_short": {"warn": 1.00, "src": "三道红线"},
}

# ---- 红旗（唐 12 条中底稿可算的 8 条） ----
FLAGS = {
    1: {"name": "存贷双高", "cash_ta": 0.20, "ibd_ta": 0.20, "types": "ABCD"},
    2: {"name": "应收异常", "gap_pp": 20.0, "types": "AB", "yellow": "C"},
    3: {"name": "存货+毛利率背离", "types": "AC", "yellow": "B"},
    4: {"name": "在建工程异常", "cip_fixed": 0.50, "types": "ABCD"},
    5: {"name": "其他应收款大", "ratio": 0.05, "types": "ABCD"},
    7: {"name": "商誉过高", "ratio": 0.30, "types": "ABCD"},
    10: {"name": "大额减值", "ratio": 0.30, "types": "ABCD"},
    12: {"name": "现金流背离", "types": "A", "yellow": "C"},
}

# ---- 趋势（FRA“五看”之看连续） ----
TREND_CONFIRM_N = 3            # 同向连续 ≥3 期 = 趋势确立

# ---- 估值 ----
PUB_LAG = {"03-31": "04-30", "06-30": "08-31", "09-30": "10-31", "12-31": "04-30"}  # 法定披露截止日，防“未来函数”
PCT_LOW, PCT_HIGH = 0.30, 0.70  # 分位 <30% 偏低区、>70% 偏高区（只描述位置，不构成建议）

# ---- 门禁（财报解读插件 source-gates）----
GATE_KEY_FIELDS = ("rev", "np_parent", "np_ded", "ocf", "ta", "tl", "eq_parent")
HEADLINE_OK_STATUS = ("一致", "原文自洽")   # 只有这些状态的数能进一句话结论（单一来源 = 待核验）

# ---- 综合判断 ----
TREND_DOWNGRADE_N = 3          # 当期达标但连续 3 期变差 → 降一档（FRA 趋势修正）
JUMP_Z = 2.0                   # 单季比率偏离过去均值 >2σ → 跳变（FRA）
JUMP_MIN_N = 8                 # 至少 8 个历史季度才做跳变检测
JUMP_STD_FLOOR = 0.005         # 比率标准差下限 0.5pct，避免历史极平稳时小波动被放大
ONE_OFF_SHARE = 0.5            # 归母变化中非经常性损益贡献 >50% → 一次性主导
PRICE_UP_GM_PP = 3.0           # 同源判断：毛利率同比 ≥+3pct 且营收增长 → 视为量价上行

# 指标方向：+1 越高越好，-1 越低越好（趋势降档、跟踪验证用）
METRIC_DIR = {"roe": 1, "np_ded_ratio": 1, "ocf_np": 1, "cash_rev": 1, "core_op": 1, "core_cash": 1,
              "ibd_ta": -1, "debt_ratio": -1, "fcf": 1, "goodwill_eq": -1, "ar_gap": -1, "inv_gap": -1,
              "runway": 1, "re_debt_ex_adv": -1, "re_net_gearing": -1, "re_cash_short": 1, "gm": 1}

# 同源风险组（张新民：多个预警指向同一件事时先合并说明）。按顺序匹配，信号归入第一个条件成立且列为成员的组。
# 成员写法：指标 key 或 "flag<编号>"
# 风险组定级（rules/0.3，经历史回放校准：组基础严重度会让单个“预警”就判高，对照样本误报 5/6）
SEV_HIGH_SCORE = 4      # 红=2、预警=1、黄=0.5；≥4 且含红 → 高
SEV_MEDIUM_SCORE = 2    # ≥2 或含红 → 中
RESONANCE_GROUPS = 2    # ≥2 个风险组同时含红色信号 → 均升为高
CASH_DEBT_BOTH = 0.20   # 存贷双高：货币资金/总资产 与 有息负债/总资产 均 ≥20%

RISK_GROUPS = [
    {"id": "price_up", "name": "量价上行带动营运资本扩张", "severity": "low",
     "members": ["flag2", "flag3", "ar_gap", "inv_gap", "core_cash", "ocf_np", "cash_rev"],
     "next": {"metric": "core_cash", "op": ">=", "value": 1.0, "text": "核心利润获现率回到 1.0 以上；若价格回落而应收、存货仍高增，转为真实风险"}},
    {"id": "collection", "name": "回款变差", "severity": "high",
     "members": ["flag2", "ar_gap", "cash_rev", "ocf_np", "core_cash", "flag12"],
     "next": {"metric": "ar_gap", "op": "<=", "value": 20.0, "text": "应收增速差回落到 20pct 以内，收现比回到 1.0 以上"}},
    {"id": "expansion", "name": "扩张期投入", "severity": "medium",
     "members": ["fcf", "flag4", "inv_gap", "flag3", "ibd_ta"],
     "next": {"metric": "fcf", "op": ">=", "value": 0.0, "text": "在建工程转固、自由现金流转正的节奏"}},
    {"id": "earnings_quality", "name": "利润含金量（非经常性/非主业）", "severity": "medium",
     "members": ["np_ded_ratio", "core_op"],
     "next": {"metric": "np_ded_ratio", "op": ">=", "value": 0.8, "text": "扣非占归母回到 80% 以上"}},
    {"id": "solvency", "name": "偿债与流动性压力", "severity": "high",
     "members": ["re_debt_ex_adv", "re_net_gearing", "re_cash_short", "debt_ratio", "ibd_ta", "flag1", "runway"],
     "next": {"metric": "re_cash_short", "op": ">=", "value": 1.0, "text": "现金短债比回到 1 以上、有息负债下降"}},
    {"id": "asset_quality", "name": "资产质量与减值", "severity": "medium",
     "members": ["cash_debt", "flag5", "flag7", "flag10", "goodwill_eq"],
     "next": {"metric": None, "text": "其他应收款、商誉与减值是否继续扩大（需附注）"}},
]
