# 低往返报告契约

与本期正式材料、比较年报放在同一个并行 tool turn 读取本文件；只靠本文件创建 `research-gate.json` 与 `report.json`。不要读取两个 schema、渲染器、校验器或 MCP tool JSON。

## 1. 一次写对的规则

- 两个文件都必须是严格 JSON；正文中的引号统一写 `「」`，不要在字符串中直接写 ASCII 双引号。
- `research-gate.json` 只保存研究与门禁；`report.json` 不嵌入 `research`，构建器会在内存中合并。
- 官方来源在 `official_documents` 和报告 `sources` 中使用同一个 `id` 与 URL。
- `sources` 不只记录财报 PDF：实际支持正文判断的 WebSearch、WebFetch、MCP 返回材料也应尽量写入，并用 `retrieval_methods` 标明获取方式。只用于发现链接、未支持任何判断的中间检索结果不进入来源表。金融 MCP 的结构化数据没有网页 URL 时，使用 `level="结构化数据"`、`retrieval_methods=["MCP"]` 并省略 `url`；不得虚构链接。
- `headline_source_ids` 至少包含一个成功读取的官方来源；核心摘要可引用官方来源、一致预期或分析计算。
- 表格 `rows` 的每一项必须是一整行数组；单元格可为字符串，或 `{"value":"...","tone":"positive|negative|warning|neutral","source_ids":["S1"]}`。
- `executive_summary` 只保留 3 条互不重复的核心结论，复杂报告最多 4 条；不要把每个指标各写成一个小结。
- 核心结论是编辑式编号摘要，不是表格；每条写成“判断标题＋证据与含义”，不要表题、表格线或单独说明栏。
- `section.summary` 只在确有独立判断时写一句；若与标题、核心结论或首段重复则省略。不要生成标签墙、卡片墙或逐段小结。
- 正文主章节按 1、2、3… 连续编号；风险是与经营、盈利、现金流、估值并列的独立章节，不附着在估值章节下。
- 图表只放在确实提高理解的 1–2 个章节。图表与表格并排时使用 `section.insight` 补充较短一侧；只有一项证据时自动改为“证据＋解读”或全宽布局，不保留空图位、不拉伸图表、不让内容超框。
- 现金流/资产负债表优先使用“左侧证据表＋右侧这意味着什么”；股东回报/估值使用“全宽估值证据＋估值判断/验证信号”，不得把两个章节写成同一种左右灰框模板。
- 财务数据表使用严格三线表：只保留顶线、表头分隔线和底线，正文行之间不画灰线；依靠行高、对齐、字重和留白区分数据。
- A 股、港股和美股真实上市公司固定创建 `MARKET_SNAPSHOT` 数据缺口；通过 pre-analysis 后只调用一次金融 MCP，合并查询当前价与当前总市值。成功时两项都必须填写；失败时保留失败日志并把缺口标为 `unavailable`，报告不显示空快照卡片。
- `market_snapshot.buy_range` 与 `sell_range` 是可选估值结果。没有可解释模型时省略字段，不得填写“未形成”“待核验”或其他占位词。
- 风险必须写入顶层 `risks`，每项使用 `title/detail/severity/direction/next_metric/source_ids` 对象；风险章节渲染为汇总表，不要写成字符串，也不要在 `sections` 中再建重复风险章节。
- `data_gaps` 只写会影响判断的披露口径缺口；不得写 PDF 截断、解析、提取、抓取、工具失败或页面缺失等内部过程。没有实质缺口时使用空数组 `[]`，模板仍会输出中性的分析范围说明。
- pre-analysis 前只完整写一次 `research-gate.json`。金融 MCP 返回后不要 Read 或整份重写该文件；用 `apply-market-snapshot.mjs` 原子更新，同时在同一个 assistant tool turn 一次写入 `report.json`。然后只执行一次构建。失败时按错误列表做一次合并修改；禁止逐条 Grep/SearchReplace。

## 2. `research-gate.json` 最小结构

```json
{
  "mode": "brief",
  "market": "A",
  "report_type": "quarterly_report",
  "company_ir_domain": "ir.company.com",
  "expanded_scope_authorized": false,
  "workflow": {
    "current_state": "ANALYSIS_READY",
    "target": {
      "company_name": "公司全称",
      "security_code": "000000",
      "report_period": "2026年第一季度"
    },
    "stop_reason": "所需正式材料已读取，信息足以开始分析"
  },
  "official_documents": [
    {
      "id": "S1",
      "title": "正式材料名称",
      "url": "https://官方具体文档URL",
      "document_type": "quarterly_report",
      "role": "current",
      "report_period": "2026年第一季度",
      "publication_date": "2026-04-30",
      "read_status": "success"
    }
  ],
  "comparison_policy": {
    "income_statement": "official_native_comparative",
    "balance_sheet": "official_report_opening"
  },
  "retrieval_log": [],
  "tool_usage": {
    "web_search_count": 0,
    "web_fetch_count": 1,
    "official_locator_count": 1,
    "shell_network_count": 0,
    "browser_use_count": 0,
    "package_install_count": 0,
    "ad_hoc_retrieval_script_count": 0,
    "official_documents_read": 1,
    "financial_mcp_count": 0,
    "news_mcp_count": 0,
    "elapsed_seconds": 120,
    "todo_write_used": false,
    "company_profile_used": false,
    "market_valuation_used": false,
    "generic_news_search_used": false,
    "renderer_source_read": false
  },
  "enrichment_decision": {
    "status": "needed",
    "reason": "上市公司报告固定需要补充带日期的当前价与当前总市值",
    "data_gaps": [
      {
        "id": "MARKET_SNAPSHOT",
        "description": "当前价与当前总市值",
        "source_type": "financial",
        "status": "open"
      }
    ]
  },
  "mcp_fields": [],
  "reconciliations": [
    {
      "name": "income_statement_comparative",
      "status": "pass",
      "basis": "official_native_comparative",
      "source_ids": ["S1"]
    },
    {
      "name": "balance_sheet_opening",
      "status": "pass",
      "basis": "official_report_opening",
      "source_ids": ["S1"]
    },
    {
      "name": "cash_closing_balance",
      "status": "pass",
      "left_value": 100,
      "right_value": 100,
      "tolerance": 0.01,
      "source_ids": ["S1"]
    }
  ]
}
```

`document_type` 使用 `annual_report|interim_report|quarterly_report|results_announcement`。最新季报另加一条 `role=comparison`、`document_type=annual_report` 的成功记录。

每次外部调用在 `retrieval_log` 记录 `sequence/channel/purpose/target/result/state_before/state_after/progress`，并按需增加 `candidate_url`、`official_document_id` 或 `data_gap_id`。pre-analysis 通过后，`MARKET_SNAPSHOT` 使用一次 `financial_mcp` 合并查询，日志必须绑定 `data_gap_id=MARKET_SNAPSHOT`。成功时把缺口改为 `resolved`，在 `mcp_fields` 分别记录 `current_price` 与 `market_cap`，两者的 `used_in` 均为 `["market_snapshot"]`；MCP 返回空数据时保留真实日志，写 `result=failed`、`progress=false`，并把对应缺口标为 `unavailable`；不要删除调用记录。

成功时两个字段必须使用以下完整结构，不要增加 `source_type`，不要用 `official_verified: false` 代替 `status`：

```json
[
  {
    "field": "current_price",
    "data_gap_id": "MARKET_SNAPSHOT",
    "status": "pending",
    "value": "12.34",
    "unit": "元",
    "as_of": "2026-08-01 15:00",
    "provider": "同花顺 iFinD",
    "official_source_ids": [],
    "used_in": ["market_snapshot"]
  },
  {
    "field": "market_cap",
    "data_gap_id": "MARKET_SNAPSHOT",
    "status": "pending",
    "value": "123400000000",
    "unit": "元",
    "as_of": "2026-08-01 15:00",
    "provider": "同花顺 iFinD",
    "official_source_ids": [],
    "used_in": ["market_snapshot"]
  }
]
```

## 3. `report.json` 最小结构

```json
{
  "mode": "brief",
  "title": "公司财报解读",
  "company": {
    "name": "公司全称",
    "short_name": "简称",
    "ticker": "000000",
    "market": "A",
    "sector": "一级行业",
    "subsector": "细分行业",
    "report_date": "2026-04-30",
    "report_type": "季度报告",
    "report_period": "2026年第一季度",
    "publication_date": "2026-04-30",
    "currency": "人民币",
    "unit": "亿元",
    "accounting_standard": "中国企业会计准则",
    "data_as_of": "2026-04-30"
  },
  "market_snapshot": {
    "lookup_status": "available",
    "current_price": "¥12.34",
    "market_cap": "1234亿元",
    "as_of": "2026-04-30 15:00",
    "source_note": "金融 MCP 结构化行情；口径待官方披露核验",
    "disclaimer": "仅作市场观察参考，非投资建议"
  },
  "headline": "一句话判断",
  "headline_source_ids": ["S1"],
  "executive_summary": [
    {
      "label": "盈利",
      "conclusion": "核心结论与比较",
      "tone": "positive",
      "source_ids": ["S1"]
    }
  ],
  "key_metrics": [
    {
      "label": "营业收入",
      "value": "100亿元",
      "comparison": "上年同期90亿元",
      "change": "+11.1%",
      "interpretation": "主要驱动",
      "tone": "positive",
      "source_ids": ["S1"]
    }
  ],
  "key_metrics_summary": "用两到三句话解释指标之间的关系、主要矛盾与下一步应关注什么。",
  "sections": [
    {
      "title": "经营与风险",
      "summary": "仅在不重复正文时填写的一句判断",
      "insight": "用于补充较短图表或表格一侧的关键解读，不重复 summary。",
      "bullets": ["事实、原因与持续性"],
      "source_ids": ["S1"]
    }
  ],
  "risks": [
    {
      "title": "需求恢复不及预期",
      "detail": "若销量和价格继续承压，利润率与现金流可能进一步走弱。",
      "severity": "medium",
      "direction": "negative",
      "next_metric": "下一期销量、ASP 与毛利率",
      "source_ids": ["S1"]
    }
  ],
  "data_gaps": [],
  "sources": [
    {
      "id": "S1",
      "title": "正式材料名称",
      "publisher": "发布主体",
      "date": "2026-04-30",
      "period": "2026年第一季度",
      "location": "页码或章节",
      "url": "https://与official_documents一致的URL",
      "retrieval_methods": ["WebSearch", "WebFetch"],
      "level": "监管披露"
    },
    {
      "id": "M1",
      "title": "公司当前价与当前总市值",
      "publisher": "同花顺 iFinD",
      "date": "2026-08-01",
      "period": "截至 2026-08-01 15:00",
      "location": "金融 MCP 结构化行情",
      "retrieval_methods": ["MCP"],
      "level": "结构化数据"
    }
  ]
}
```

`market_snapshot.lookup_status` 只使用 `available|unavailable`。`available` 必须同时提供非占位的 `current_price`、`market_cap` 与 `as_of`；`unavailable` 表示已真实调用金融 MCP 但无有效结果，此时不填写占位值，渲染器会省略整个快照区。买卖区间只有在估值模型充分时才增加。

模式结构：`brief` 只保留 3 条核心结论、关键指标、驱动与风险；`standard` 增加业务拆解、现金流和资产负债表；`deep` 再增加多期趋势、量价与验证清单；`preview` 使用官方指引、一致预期、情景和超预期标准；`update` 使用实际对原预测、调整桥接和逻辑状态。未适用章节不生成，适用但数据不足时才写入 `data_gaps`。构建器会按模式调整前置章节与风险/缺口标题，并自动合并重复风险章节；所有模式优先合并重复判断，视觉层级只保留“标题—核心判断—核心结论—正文—附录”五级。

## 4. MCP 后单轮落盘

MCP 返回后不要读取 `research-gate.json`，直接执行：

```bash
node scripts/apply-market-snapshot.mjs \
  --research research-gate.json \
  --status available \
  --price "12.34" \
  --price-unit "元" \
  --market-cap "123400000000" \
  --market-cap-unit "元" \
  --as-of "2026-08-01 15:00" \
  --provider "同花顺 iFinD" \
  --tool "get_stock_summary" \
  --query "公司最新股价和总市值"
```

空结果改用 `--status unavailable --note "真实失败原因"`，省略价格、市值和时间。调用该脚本与写入 `report.json` 相互独立，必须放在 MCP 返回后的同一个 assistant tool turn；不要等待脚本结果后再开启一轮写报告。

## 5. 单命令构建

```bash
node scripts/build-report.mjs \
  --research research-gate.json \
  --report report.json \
  --output earnings-report.html
```

构建器一次完成最终门禁、数据合并、渲染与 HTML 校验，并自动把可结束的 workflow 状态推进到 `DONE`。成功后不要再次打开、搜索、修改或重复校验产物。
