# 官方材料与研究门禁

本文件用于已披露财报的材料定位、来源核验和停止条件。成功标准是“找对并读完目标正式材料”，不是把工具次数压到固定数字。

## 1. 状态驱动检索

按以下状态推进：

```text
TARGET_DEFINED
→ LOCATING
→ VERIFIED
→ READ_COMPLETE
→ ANALYSIS_READY
→ ENRICHMENT_DECISION
→ DONE
```

- `TARGET_DEFINED`：公司、市场、证券代码、精确报告期和报告类型已明确；
- `LOCATING`：正在官方入口定位材料；
- `VERIFIED`：候选 URL 的公司、期间和类型已核验；
- `READ_COMPLETE`：本期正式材料已读完；最新季报所需的上一份年报也已读完；
- `ANALYSIS_READY`：口径和证据足以开始分析；
- `ENRICHMENT_DECISION`：已判断是否存在财报原文无法回答的数据缺口；
- `DONE`：分析、核验和报告均已完成。

状态不得倒退。相互独立且在同一个 tool turn 发出的并行定位允许共享同一个 `state_before`；校验器对此只记录 warning，不要求为日志元数据另开一轮修复。进入 `READ_COMPLETE` 后停止一切 `locate_official_document`；后续外部调用只能是绑定到明确 `data_gap_id` 的 `enrich_data_gap`。

## 2. 官方财报定位器

用户未提供可直接读取的正式材料时，优先执行一次：

```bash
node scripts/locate-filing.mjs \
  --market HK|US|A \
  --ticker <证券代码> \
  --period "<精确报告期>" \
  --type quarterly|interim|annual|results
```

定位器使用确定性官方入口：

| 市场 | 首选入口 | 识别方式 |
|---|---|---|
| 港股 | HKEX 公司公告索引 | 五位股份代码映射 HKEX `stockId`，再筛选报告期和报告类型 |
| 美股 | SEC Submissions | ticker 映射 CIK，再筛选 `10-K/10-Q/20-F/6-K/8-K` |
| 中概股 ADR | SEC Submissions | 年报优先 `20-F`，阶段性业绩优先核对 `6-K` 附件 |
| A股 | 巨潮资讯公告查询 | 六位代码映射 `orgId`，再筛选年报、半年报或季报 |

最新季报同时返回上一份年报候选。用户未指定报告期时，默认最近已到法定披露截止日的报告期；不要试探尚未到截止日的半年报或季报。公司同时上市时优先按用户指定市场；用户未指定时优先公司 IR，再选择主要上市地监管披露。

定位器未返回正确候选时，使用定向 Web Search 回退：

```text
site:{公司官方根域名或正式披露服务商} "{公司名称或代码}" "{精确报告期}" "{报告类型}"
site:{交易所或监管域名} "{证券代码}" "{精确报告期}" "{报告类型}"
```

搜索结果只有官方索引页时，可以用 WebFetch 或官方页面继续定位。每次调用必须产生新候选、核验候选或明确排除错误路径；不得用媒体解读替代财报原文。

## 3. RetrievalLog 规则

每次外部检索前先记录目标和 `state_before`，调用后补齐：

- `channel`：`official_locator`、`web_search`、`web_fetch`、`shell_network`、`browser_use`、`financial_mcp` 或 `news_mcp`；
- `purpose`：`locate_official_document`、`read_official_document` 或 `enrich_data_gap`；
- `result`：`success` 或 `failed`；
- `progress`：是否产生新候选、新证据、状态推进或明确排除错误路径；
- `candidate_url`：定位成功时记录具体候选；
- `official_document_id`：读取正式材料时记录；
- `data_gap_id`：增强取数时记录；
- `state_after` 和必要的 `note`。

相同 `channel + purpose + target` 不得重复。完全相同的正式材料不得重复读取。连续无进展时切换官方入口或停止并报告，不得机械重试。

WebFetch、命令行联网、Browser Use 和外部获取总调用次数不再触发硬失败。校验器仍核对日志与计数，并对高调用量、连续无进展、现场安装依赖和临时抓取脚本发出 warning，供 Trace 下钻。

## 4. 官方域名与原文门禁

| 市场 | 固定官方域名 | 可增加 |
|---|---|---|
| 港股 | `hkexnews.hk`、`hkex.com.hk`、`*.todayir.com` | 已核验的公司 IR 域名 |
| A股 | `cninfo.com.cn`、`sse.com.cn`、`szse.cn`、`bse.cn` | 已核验的公司 IR 域名 |
| 美股 | `sec.gov` | 已核验的公司 IR 域名 |

官方材料 URL 必须使用 `http/https`，指向具体公告、HTML 披露页或 PDF，并在 `official_documents` 与报告 `sources` 中记录同一个真实 URL。媒体、搜索结果页、转载页、Logo 聚合站和 MCP 名称不属于官方财报来源。

对 `brief`、`standard`、`deep` 和 `update`：

1. 至少成功读取一份本期正式财报、业绩公告或正式报告原文；
2. 最新季报必须再成功读取上一份年报；
3. 利润表同比使用本期官方报告原生比较列；
4. 资产负债表期初使用本期官方报告原生期初列；
5. 一次写入 `research-gate.json` 后执行：

   ```bash
   node scripts/validate-gates.mjs --input research-gate.json --stage pre-analysis
   ```

门禁未通过时，不得调用金融或资讯 MCP，不得开始数据分析。
失败时只按返回的字段路径做一次合并修改；不要读取或搜索校验器源码。

## 5. 自主增强决策

官方原文读完后，先处理固定市场快照，再回答：“除市场快照外，现有材料能否直接回答用户问题？”

- 对 A 股、港股和美股真实上市公司：在 `data_gaps` 创建固定缺口 `MARKET_SNAPSHOT`（`source_type=financial`），一次合并查询当前价与当前总市值；成功后标为 `resolved`，空结果或连接失败标为 `unavailable`；
- 除固定市场快照外没有其他缺口：完成查询后使用 `enrichment_decision.status=completed`；仅 `OTHER` 市场、模拟公司或不适用市场快照时才可使用 `not_needed`；
- 不能：把缺失字段或背景写入 `data_gaps`，指定 `source_type` 和用途，再选择金融、资讯或官方补充来源；
- 调用完成：将缺口标为 `resolved` 或 `unavailable`，并把状态改为 `completed`。

MCP 不设固定调用上限，但每次调用都必须绑定一个真实 `data_gap_id`。`MARKET_SNAPSHOT` 是报告固定事实字段，不属于版面填充；除该字段外，不得为了公司简介、版面填充或“显得专业”调用行情、估值或泛新闻。市场快照直接使用 SKILL.md 给出的固定 server/tool 优先级，禁止 LS MCP 目录或读取 tool JSON。空结果保留为 `result=failed`、`progress=false`，把缺口标为 `unavailable`；不要删除真实调用日志。

MCP 返回后不要 Read 或整份重写研究文件，调用 `apply-market-snapshot.mjs` 一次写入日志、计数、缺口状态和两个字段。每个 MCP 字段写入 `research.mcp_fields`：

- `official_verified`：已在成功读取的官方原文中核验，并记录官方 `source_ids`；
- `pending`：未完成官方原文核验，只能进入正文补充或附录，并显式标注“待核验”。

`pending` 字段禁止进入报告标题、核心判断、核心结论和高风险判断。金融 MCP 不得替代官方财报原生比较口径。

## 6. 勾稽门禁

交付前至少完成：

1. `income_statement_comparative`：确认同比来自官方原生比较列；
2. `balance_sheet_opening`：确认期初来自官方报告原生期初列；
3. `cash_closing_balance`：现金流量表期末现金与资产负债表或附注核对，差异不超过记录的容差。

最终报告阶段不再把 `research` 复制进 `report.json`。按
[report-contract.md](report-contract.md) 分别保留 `research-gate.json` 和
`report.json`，再一次执行：

```bash
node scripts/build-report.mjs \
  --research research-gate.json \
  --report report.json \
  --output earnings-report.html
```

构建器在内存中合并研究数据，一次完成 pre-report 门禁、渲染和 HTML
校验。失败时按错误列表一次合并修正后只重跑一次；任何原文、来源、
MCP 字段或勾稽硬门禁仍失败时停止交付。

## 7. 效率诊断

正常 `brief` 任务仍以 120–180 秒为目标，通常只需要 1–2 次定位和 1–2 份正式材料读取。以下情况只产生诊断 warning，不直接判失败：

- Web Search 或 WebFetch 次数高于常见范围；
- 使用命令行联网或 Browser；
- 外部获取总调用超过参考值；
- 金融或资讯 MCP 调用较多；
- 现场安装依赖或编写临时抓取脚本；
- 总耗时超过 180 秒。

Brief 模式仍禁止 TodoWrite、公司 Profile、除固定 `MARKET_SNAPSHOT` 外为填充报告进行行情估值、泛新闻搜索和读取 schema、MCP tool JSON、渲染器或校验器源码。固定快照只取当前价与当前总市值，不等同于估值建模，`market_valuation_used=false`。MCP 后的研究更新与 `report.json` 写入必须在同一个 assistant tool turn；构建器只执行，成功后不打开、不摘要、不修改、不重复校验。
