# 财务数据获取手册（A 股）

## 1. 两条数据通道，各管一段

| 通道 | 拿什么 | 局限 |
|---|---|---|
| **westock CLI** | 三大报表的标准化科目、行情、分红、回购、新闻、比率指标 | 现金流量表**只有三大净额，无明细科目**；部分比率字段恒为 0 |
| **新浪 F10 抓取**（`scripts/fetch_statements.py`） | 三表的**全部明细科目**（购建固定资产支付的现金、投资支付的现金、取得借款、偿还债务、分配股利、未分配利润、盈余公积、折旧摊销……） | 数据为单期/多期 HTML，需解析；单位为万元 |

**原则**：粗口径看趋势用 westock；做张新民框架必须补新浪明细（尤其是现金流四步法、未分配利润勾稽、折旧摊销）。

---

## 2. westock CLI

可执行文件：`C:\Users\Administrator\.local\bin\westock.exe`
（未安装时用 `...\plugins\cache\cb_teams_marketplace\finance-data\1.6.0\skills\westock-data\scripts\setup.cjs` 安装）

常用命令：

```bash
westock finance sz000651 --type income   --fields all --limit 42   # 利润表
westock finance sz000651 --type balance  --fields all --limit 42   # 资产负债表
westock finance sz000651 --type cashflow --fields all --limit 42   # 现金流量表（仅三大净额）
westock quote sz000651                                             # 行情/估值
westock dividend sz000651 --years 12                               # 历年分红
westock buyback sz000651 --start 2019-01-01 --end 2026-09-19       # 历年回购
westock news list sz000651 --limit 15                              # 新闻
westock finance sz000333,sh600690,sz000651 --type income --limit 2 # 同业对照（逗号分隔）
```

代码前缀：深市 `sz`、沪市 `sh`。`--limit 42` ≈ 十年年报 + 季报。

### 2.1 提取范式（务必照抄，避免踩坑）

**坑 1：控制台会按宽度截断。** 先导出到文件再解析：
```powershell
& "$env:USERPROFILE\.local\bin\westock.exe" finance sz000651 --type balance --fields all --limit 42 `
  | Out-File "$env:TEMP\geli_balance.md" -Encoding utf8
```

**坑 2：不要用列索引硬取数**。输出是 markdown 表格，列序会变。按**表头名称映射**取：

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$f   = "$env:TEMP\geli_balance.md"
$cols = @('EndDate','CashEquivalents','Inventories','TotalFixedAsset','SEWithoutMI','RetainedProfit')
$money= @('CashEquivalents','Inventories','TotalFixedAsset','SEWithoutMI','RetainedProfit')
$all = Get-Content $f -Encoding UTF8
$hdr = ($all[0].Split('|') | ForEach-Object { $_.Trim() })
$map = @{}; for ($i=0; $i -lt $hdr.Count; $i++) { $map[$hdr[$i]] = $i }
$all | ForEach-Object {
  if ($_ -match '-12-31 \|') {
    $p = $_.Split('|') | ForEach-Object { $_.Trim() }
    ($cols | ForEach-Object {
      $c = $_; $v = $p[$map[$c]]; $d = 0.0
      if ($money -contains $c -and [double]::TryParse($v, [ref]$d)) { '{0:N1}' -f ($d/1e8) } else { $v }
    }) -join ' | '
  }
}
```
（单位换算：`/1e8` = 元→亿元；新浪数据为万元，用 `/1e4`。）

### 2.2 实测可用字段（balance / income 常用）

**资产负债表**：`EndDate` `CashEquivalents` `Inventories` `BillAccReceivable` `ReceivablesFin` `NotAccountsPayable` `AccountsPayable` `ContractLiability` `OtherCurrentLiability` `SalariesPayable` `TotalCurrentAssets` `TotalNonCurrentAssets` `TotalCurrentLiability` `TotalNonCurrentLiability` `TotalLiability` `TotalShareholderEquity` `SEWithoutMI` `PaidInCapital` `CapitalReserveFund` `SurplusReserveFund` `RetainedProfit` `TotalFixedAsset` `TConstruInProcess` `IntangibleAssets` `GoodWill` `LongtermEquityInvest` `TradingAssets` `ShortTermLoan` `LongtermLoan` `BondsPayable` `LeaseLiabilities` `NonCurrentLiabilityIn1Year` `InterestBearDebt` `CurrentRatio` `QuickRatio` `DebtAssetsRatio` `DebtEquityRatio` `EquityMultipler` `InventoryTDays` `TotalAssetTRate` `AccountsPayablesTRate` `TotalAssetGrowRate` `WorkingCapital`

**利润表**：`EndDate` `OperatingRevenue` `OperatingCost` `OperatingProfit` `TotalProfit` `NetProfit` `ParentNetProfit`（或 `NetProfitAttrParent`）

> 字段清单会随版本变化，取数前先 `--limit 1` 打印表头确认存在性，缺失列会取到空串。

### 2.3 已知字段缺陷

- `GrossIncomeRatio`、`NetProfitRatio` **恒为 0**，不可用 → 自行计算：
  - 毛利率 =（营业收入 − 营业成本）/ 营业收入
  - 净利率 = 净利润 / 营业收入
- `westock` 的 `RetainedProfit` 与新浪原始报表**存在 1—2 亿级差异** → 做未分配利润精确勾稽时以新浪为准。
- 现金流量表**没有**购建固定资产、投资支付、借款、偿债、分红等明细。

---

## 3. 新浪 F10 抓取脚本

```bash
python scripts/fetch_statements.py 000651 --years 2016-2025 --out ./data
python scripts/fetch_statements.py 000651 --only cashflow --period annual --extra 2026-06-30
```

- 参数：`--years`（默认 2016-2025）、`--out`、`--only income,balance,cashflow`、`--period annual|all`、`--extra 期`、`--unit 亿元|raw`
- 产出：`<code>_<kind>.md`（行=科目，列=报告期）与同名 `.json`
- 单位：新浪原始数据为**万元**，脚本默认换算为亿元
- 页面编码 GBK，脚本已处理；抓取失败会自动重试 3 次

**关键科目名（用于 grep 定位）**：
- 现金流：`经营活动产生的现金流量净额`、`购建固定资产、无形资产和其他长期资产所支付的现金`、`投资所支付的现金` / `投资支付的现金`、`取得借款收到的现金`（`取得借款所收到的现金`）、`偿还债务所支付的现金`、`分配股利、利润或偿付利息所支付的现金`、`固定资产折旧、油气资产折耗、生产性物资折旧`
- 权益：`未分配利润`、`盈余公积`、`资本公积`、`归属于母公司股东权益合计`
- 资产：`货币资金`、`存货`、`应收票据及应收账款`、`固定资产`、`在建工程`

> 科目名在不同年份页面上可能有细微差异（「投资所支付的现金」vs「投资支付的现金」）。若某科目缺失，先用 `--period all` 抓取并 grep 全部科目名确认实际写法。

### 3.1 指标计算：用脚本，不要手算

```bash
python scripts/calc_metrics.py --dir ./data --code 000651            # 通用口径
python scripts/calc_metrics.py --dir ./data --code 601166 --bank     # 银行口径
python scripts/calc_metrics.py --dir ./data --code 000651 --check    # 只诊断缺失科目
```

- 输入 `fetch_statements.py` 产出的 `.json`，输出 `<code>_metrics.md`（指标 × 报告期表）与 `.json`
- 通用口径 59 项、银行口径 36 项，含双口径核心利润、双口径获现率、现金周期、三支柱两搅局校验差、未分配利润勾稽缺口、平衡验证
- **缺失科目会明确告警**，对应指标留空而不是填 0——看到 `[WARN] 缺失 N 个关键科目` 先补数或改用替代口径
- 银行口径含「减值倒算 vs 间接法计提」校验，这是银行最强勾稽

### 3.2 科目名匹配的坑（脚本和人工都踩过）

1. **归母净利的写法各公司不同**：`归属于母公司所有者的净利润`／`归属于母公司股东的净利润`／**`归属于母公司的净利润`**（兴业银行）。若候选名只写了前两种，模糊匹配会退回到 `五、净利润`（含少数股东），**静默虚增 3.85 亿**。排查方法：拿到 json 后先 grep 含"归属于母公司"的行名确认实际写法。
2. **合并列会重复计数**：有的公司只有 `应收票据及应收账款`，没有分开的两行。此时若分别按"应收票据""应收账款"匹配，两行都会命中同一行，周转天数被放大一倍。脚本已按"合并列优先"处理，人工取数时同样要注意。
3. **泛名误命中**：`固定资产` 会命中 `固定资产清理`，`净利润` 会命中任何含"净利润"的行。匹配时应优先精确、其次取**最短**的行名。
4. **「其他收益」常抓不到**：新浪部分年份页面无此行（科大国创全十年缺失）。获现率因此只能用「核心利润」单口径，需在报告中注明差异。
5. **2019 年后「资产减值损失」行为空**（新准则改为信用减值损失），银行必须用倒算补齐。
6. **「现金及现金等价物期末余额」并非每家都有**（科大国创缺失）→ 楔子与可动用净现金算不出来时，直接说明该口径不可用，不要拿货币资金代替。

---

## 4. 其他通道（实测记录）

- **东方财富 datacenter-web 接口**（`RPT_DMSK_FN_CASHFLOW` / `RPT_DMSK_FN_INCOME`）：实测返回失败或字段不完整，**不作为主通道**。
- **东财 F10 `lrbAjax`**：可用作利润表补充，但稳定性一般。
- **`neodata-financial-search` skill**：适合自然语言查财报文章与观点，不适合取结构化明细。
- **优先级**：westock → 新浪脚本 → WebSearch 补新闻/事件 → 东财兜底。

---

## 5. 数据一致性规则

1. 所有金额统一到**亿元、保留 1—2 位小数**，并在报告中标注单位。
2. 同一指标若两个数据源冲突，**在报告中并列披露并说明口径差异**，不要静默取其一。
3. 多年序列必须**逐年核对**后再写进结论（例如"经营正/投资负/筹资负"出现几年，必须数出来，不能凭印象写 6 年）。
4. 所有比率给出**十年序列 + 当期值**，单期数据不足以支撑判定。
5. 年报口径用 `-12-31` 期；最新中报单独标注为 `20XXH1`，不与年度数据混排进趋势图（或明确断开）。
