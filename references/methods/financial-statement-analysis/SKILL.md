---
name: financial-statement-analysis
version: 1.2.0
display_name: 财报深度分析（张新民框架）
display_name_en: Financial Statement Deep Analysis
description_zh: 上市公司财务报表深度分析与 HTML 研报生成。基于张新民《火眼金睛读财报》框架（利润表四步法、资产负债表三步法、现金流量表四步法、三表勾稽验证、好企业识别），产出含企业体检表的浅底研报风 HTML 报告；支持银行/券商/保险/地产等特殊行业适配，并可用金字塔原理、SCQA、5W2H、现象-原因-方案、SMART 重组为管理决策版汇报。
description_en: Deep financial-statement analysis for listed companies with HTML report generation. Based on Zhang Xinmin's framework (4-step income statement, 3-step balance sheet, 4-step cash flow, three-statement cross-validation, good-company identification); produces a health-checkup style HTML research report. Includes industry adaptation for banks, brokers, insurers and real estate, and can be restructured into a management decision report using the Pyramid Principle, SCQA, 5W2H, Phenomenon-Cause-Solution and SMART.
description: 上市公司财务报表深度分析与 HTML 研报生成。基于张新民《火眼金睛读财报》框架（利润表四步法、资产负债表三步法、现金流量表四步法、三表勾稽验证、好企业识别），产出体检表式财务分析报告；并支持用金字塔原理、SCQA、5W2H、现象-原因-方案、SMART 重组为管理决策版汇报。当用户要求分析某家 A 股公司的财报、做财务体检、验证报表勾稽关系、识别好企业，或要求把财务结论改写成管理层汇报时使用。
agent_created: true
---

# 财务报表深度分析

## 用途

把一家 A 股上市公司的三张报表，拆解成可判定的结构化结论，并交付浅底研报风的 HTML 报告。分析依据是张新民《火眼金睛读财报》的方法论，核心输出是**企业体检表**（指标 / 数值 / 健康标准 / 判定 / 说明）。

## 何时使用

- 用户点名分析某家公司的利润表、资产负债表、现金流量表，或要求"财务体检""财报分析"
- 用户给出一段方法论（如张新民某节内容）并要求据此分析某公司
- 用户要求验证三表勾稽关系、识别财务异常信号
- 用户要求把已有财务结论用金字塔原理 / SCQA / 5W2H / 现象-原因-方案 / SMART 重新组织

## 报告类型路由

| 用户意图 | 产出 |
|---|---|
| 分析单张报表（利润表/资产负债表/现金流量表） | 单项分析报告：按该表的步骤逐一评定 + 关键判断 3 条 + 跟踪指标 |
| 勾稽 / 验真 | 三表勾稽验证报告：五项勾稽 + 三条异常信号扫描 |
| 识别好企业 / 资产轻重 | 第 18—19 节综合分析：评分卡 + 质量项 vs 方向项二分 |
| 汇总 / 总报表 / 体检表 | 财务体检总报告：九章结构，含 50+ 项体检表 |
| 金字塔 / SMART / 5W2H / 现象原因方案 | 管理决策版：在总报告数据基础上重组表达结构 |
| **分析对象是银行** | **先读 `references/bank-adaptation.md`**，按银行适配口径执行；报告第一章必须前置「框架适配说明」表 |
| **分析对象是券商 / 保险 / 地产 / 周期股 / 软件服务** | **先读 `references/industry-adaptation.md`**，按该行业的替换对照表执行，同样前置适配说明 |

## 工作流程

### 第 1 步：确认范围
确认股票代码（深 `sz` / 沪 `sh` 前缀）、数据截止期（默认最新年报 + 最新中报）、报告类型、是否需要同业对照。**不清楚时按最新年报 + 2 家同业龙头默认执行，不阻塞。**

### 第 2 步：取数（数据未齐不动笔）
1. **westock CLI** 取标准化科目、行情、分红、回购、比率（详见 `references/data-sources.md`）
2. **新浪 F10 脚本**补明细科目——做现金流四步法与未分配利润勾稽**必须**补：
   ```bash
   python scripts/fetch_statements.py 000651 --years 2016-2025 --out ./data
   ```
3. 同业对照：`westock finance <code1>,<code2>,<code3> --type income --limit 2`
4. 事件与新闻：`westock news list <code> --limit 15`，必要时 WebSearch 补充

取数纪律：导出到文件再解析；按**表头名称映射**取列，不用列索引；金额统一亿元。

### 第 3 步：计算指标
**先跑脚本，再手工补**——不要从零手算（过去每分析一家公司都要现写一份计算脚本，既慢又易错）：
```bash
python scripts/calc_metrics.py --dir ./data --code 000651 [--bank] [--check]
```
脚本输出通用口径 59 项 / 银行口径 36 项的**十年序列**（`<code>_metrics.md` + `.json`），含双口径核心利润、双口径获现率、现金周期、三支柱两搅局校验差、未分配利润勾稽缺口、平衡验证；缺失科目会明确告警。

脚本未覆盖的项（分红、回购、同业、监管指标）按 `references/zhangxinmin-framework.md` 第 6 节公式表补齐。至少覆盖：

- 核心利润及其占比（双口径）、核心利润率
- 营收/净利 CAGR 与逐年增速、超额增速
- 营业利润/利润总额、扣非/归母
- 资本支出/折旧摊销、自由现金流、获现率（双口径）、收现比
- 现金周期、资产有息负债率、经营性负债占比
- 利润积累占比、自我造血倍数、投资资产/经营资产
- 楔子（货币资金 − 现金等价物）、可动用口径净现金

### 第 4 步：交叉核对
- 跑三表勾稽五项（未分配利润 / 货币资金 / 间接法 / 平衡 / 异常信号）
- 缺口先尝试用**股份回购**、**少数股权收购**、**楔子**解释，解释不了的标注"需追年报《所有者权益变动表》"
- **银行必做**：信用减值损失倒算（营业支出−税金−管理费−其他业务支出）vs 间接法「计提的资产减值准备」逐年比对，这是银行版最强勾稽；未分配利润勾稽须计入**一般风险准备**
- 同业对照定位：跌幅/涨幅是否显著偏离同业
- **逐年核对计数**（如某现金流组合出现几年），不凭印象写数

### 第 5 步：生成报告
1. 复制 `assets/report_skeleton.html` 的样式基线（CSS 变量、组件类、ECharts CDN）
2. 先 `Write` 骨架并留占位注释（`<!--PART2-->`…），再 `Edit` 逐段替换，避免超长写入截断
3. 章节按 `references/report-spec.md` 第 4 节选模板
4. 管理决策版按 `references/management-frameworks.md` 第 5 节组装
5. 收尾 grep 确认 `</body>`、`</html>` 各只出现一次且在末尾

### 第 6 步：校验（强制）
```bash
python scripts/check_report.py 报告.html
```
必须出现 `[OK] 内联 JS 语法` 且 0 个 `[ERR]`。同时人工核对每个图表的 `xAxis` 类目数与各 series `data` 长度一致。

### 第 7 步：交付
用 `present_files` 打开文件，回复中给出**核心结论表格**（分维度评级 + 依据），提炼 3 条关键判断，附口径修正与跟踪指标，结尾附免责声明。

## 不可违反的规则

1. **数据未齐不动笔**——边写边补数会导致前后口径不一致
2. **结论必须挂数据**——"核心利润占比高"不合格，"核心利润占营业利润 96.8%"合格
3. **强制十年序列**——单期数据不足以支撑任何趋势判定
4. **双口径并列**——核心利润（含/不含财务费用净收益）、净现金（货币资金/可动用现金等价物）、获现率（含/不含其他收益）
5. **同业对照**——成长性判定必须有同业基准，否则无法区分行业 beta 与份额流失
6. **结论必须给出唯一关键变量**——"转折的关键在营收拐点"这类收口，只给好坏定性等于没结论
7. **区分质量项与方向项**——盈利真不真、还长不长，是两类问题，不能混为一谈
8. **识别同源风险**——多项预警指向同一事实时必须点明，这是汇报价值最高的动作
9. **行业口径必须先替换**——非一般工商企业（银行/券商/保险/地产/周期/软件）直接套制造业公式会得出反向结论，必须前置适配说明表
10. **附免责声明**
11. **关键科目取到值后要交叉验一次**——科目名各公司写法不同，模糊匹配会**静默取错行**。教训：兴业银行的归母净利科目名是「归属于母公司的净利润」，候选名没覆盖时脚本退回到「五、净利润」（含少数股东），虚增 3.85 亿、同比从 +0.34% 变成 +0.47%。归母净利、固定资产、应收类这三项尤其要复核

## 资源索引

| 文件 | 内容 |
|---|---|
| `references/zhangxinmin-framework.md` | 五套分析框架、全部公式与判定阈值、交付前自检清单 |
| `references/bank-adaptation.md` | **商业银行适配**：指标替换对照表、银行专属指标与自算口径、减值倒算验证、数据源坑、常见误判、章节结构 |
| `references/industry-adaptation.md` | **其他特殊行业适配**：券商／保险／地产／重资产周期／轻资产软件的替换口径、专属指标、收口变量，含"三步判断法" |
| `references/data-sources.md` | westock CLI 命令与字段、新浪抓取脚本用法、**指标计算脚本用法**、已知字段缺陷与科目名匹配的坑 |
| `references/report-spec.md` | HTML 报告视觉基线、组件、图表规范、章节模板、常见错误清单 |
| `references/management-frameworks.md` | SCQA、金字塔、5W2H、现象-原因-方案、SMART 的落地模板与组装顺序 |
| `scripts/fetch_statements.py` | 新浪 F10 三表明细抓取（多年、全科目、自动转亿元） |
| `scripts/calc_metrics.py` | 指标计算：通用 59 项 / 银行 36 项十年序列，输出 md+json，缺失科目告警 |
| `scripts/check_report.py` | 交付前校验：内联 JS 语法、标签平衡、图表 id、逐图序列长度、CSS 变量 |
| `assets/report_skeleton.html` | 报告骨架：CSS 基线 + **体检表分组行 / 评分条 / 雷达图 / 风险卡 / 红黄绿看板** 组件，复制后填充 |

## 环境路径

- Python：`C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe`
- Node（校验 JS 用）：`C:\Users\Administrator\.workbuddy\binaries\node\versions\22.22.2-3\node.exe`
- westock：`C:\Users\Administrator\.local\bin\westock.exe`
- 输出目录：默认当前工作区目录，文件名格式 `<公司名>_<主题>.html`
