import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import {
  officialLevels,
  validateOfficialUrl,
  validateResearchGate,
} from "./validate-gates.mjs";

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) continue;
    const key = token.slice(2);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) {
      args[key] = true;
    } else {
      args[key] = value;
      index += 1;
    }
  }
  return args;
}

function countMatches(text, expression) {
  return [...text.matchAll(expression)].length;
}

function collectSourceIds(value, ids = []) {
  if (Array.isArray(value)) {
    for (const item of value) collectSourceIds(item, ids);
    return ids;
  }
  if (!value || typeof value !== "object") return ids;
  if (Array.isArray(value.source_ids)) ids.push(...value.source_ids);
  for (const child of Object.values(value)) collectSourceIds(child, ids);
  return ids;
}

const dedicatedRiskTitles = new Set([
  "风险",
  "风险提示",
  "主要风险",
  "主要风险提示",
  "主要风险与关注要点",
  "最该盯紧的风险",
  "核心风险",
  "风险与关注要点",
  "关键风险",
  "情景风险",
  "逻辑风险",
]);

function normalizedSectionTitle(value) {
  return String(value || "").replace(/[\s：:、，,。.!！?？/／·—_-]+/g, "");
}

function visibleHtmlText(value) {
  return String(value || "")
    .replace(/<[^>]+>/g, "")
    .replace(/&(?:amp|lt|gt|quot|#39|nbsp);/gi, "x")
    .trim();
}

function isMarketPlaceholder(value) {
  const text = String(value || "").trim();
  return (
    !text ||
    /^(?:[-—–]|n\/?a)$/i.test(text) ||
    /^(?:待核验|未形成|未获取|不可用|暂无|未披露)(?:[（(].*)?$/i.test(text)
  );
}

export function validateReportData(
  data,
  errors,
  warnings,
  { allowFixture = false } = {},
) {
  const modes = new Set(["brief", "standard", "deep", "preview", "update"]);
  if (!modes.has(data.mode)) errors.push(`invalid mode: ${data.mode}`);
  if (!data.title) errors.push("missing title");
  if (!data.headline) errors.push("missing headline");
  if (!data.company?.name) errors.push("missing company.name");
  if (!data.company?.report_type) errors.push("missing company.report_type");
  if (!data.company?.report_period) errors.push("missing company.report_period");
  if (!data.company?.publication_date) errors.push("missing company.publication_date");
  if (!data.company?.data_as_of) errors.push("missing company.data_as_of");
  const listedCompany = ["A", "HK", "US"].includes(
    String(data.research?.market || "").toUpperCase(),
  );
  if (listedCompany) {
    const snapshot = data.market_snapshot;
    if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) {
      errors.push("listed-company reports require market_snapshot");
    } else if (!["available", "unavailable"].includes(snapshot.lookup_status)) {
      errors.push("market_snapshot.lookup_status must be available or unavailable");
    } else if (snapshot.lookup_status === "available") {
      if (isMarketPlaceholder(snapshot.current_price)) {
        errors.push("available market_snapshot requires a non-placeholder current_price");
      }
      if (isMarketPlaceholder(snapshot.market_cap)) {
        errors.push("available market_snapshot requires a non-placeholder market_cap");
      }
      if (!String(snapshot.as_of || "").trim()) {
        errors.push("available market_snapshot requires as_of");
      }
    }
    for (const fieldName of ["buy_range", "sell_range"]) {
      if (snapshot && Object.hasOwn(snapshot, fieldName) && isMarketPlaceholder(snapshot[fieldName])) {
        errors.push(`market_snapshot.${fieldName} must be omitted instead of using a placeholder`);
      }
    }
  }
  const gateResult = validateResearchGate(data.research, {
    stage: "pre-report",
    allowFixture,
  });
  errors.push(...gateResult.errors.map((error) => `research gate: ${error}`));
  warnings.push(...gateResult.warnings.map((warning) => `research gate: ${warning}`));
  if (data.research?.mode !== data.mode) {
    errors.push("research.mode must match report mode");
  }
  if (data.research?.report_type !== data.company?.report_type) {
    warnings.push(
      "research.report_type differs from company.report_type; this is allowed when research uses a canonical type and the company field uses a display label",
    );
  }
  const normalizePeriod = (value) => String(value || "").replace(/\s+/g, "");
  const currentDocuments = (data.research?.official_documents || []).filter(
    (document) =>
      document.role === "current" &&
      document.read_status === "success" &&
      normalizePeriod(document.report_period) ===
        normalizePeriod(data.company?.report_period),
  );
  if (
    ["brief", "standard", "deep", "update"].includes(data.mode) &&
    currentDocuments.length === 0
  ) {
    errors.push("no successfully read current official document matches report period");
  }

  for (const key of ["executive_summary", "key_metrics", "sections", "sources"]) {
    if (!Array.isArray(data[key]) || data[key].length === 0) {
      errors.push(`${key} must be a non-empty array`);
    }
  }
  const summaryLimit = 3;
  if ((data.executive_summary || []).length > summaryLimit) {
    errors.push(
      `executive_summary has ${data.executive_summary.length} items; maximum is ${summaryLimit} for ${data.mode} mode to preserve visual focus`,
    );
  }

  const chartCount = (data.sections || []).filter((section) => section.chart).length;
  if (chartCount > 2) errors.push(`too many charts: ${chartCount}; maximum is 2`);
  if (data.company?.logo_path && data.company?.logo_data_uri) {
    errors.push("company.logo_path and company.logo_data_uri are mutually exclusive");
  }
  for (const [index, section] of (data.sections || []).entries()) {
    const firstParagraph = String(section.paragraphs?.[0] || "").trim();
    const summary = String(section.summary || "").trim();
    if (summary && firstParagraph && firstParagraph.startsWith(summary)) {
      warnings.push(
        `section ${index + 1} summary duplicates its first paragraph; omit one to preserve visual focus`,
      );
    }
    if (section.table && !section.table.title) {
      errors.push(`section ${index + 1} table missing academic title`);
    }
    if (section.table && !section.table.source) {
      errors.push(`section ${index + 1} table missing source`);
    }
    if (section.chart && !section.chart.source) {
      errors.push(`section ${index + 1} chart missing source`);
    }
  }

  const dedicatedRiskSections = (data.sections || []).filter((section) =>
    dedicatedRiskTitles.has(normalizedSectionTitle(section.title)),
  );
  if (dedicatedRiskSections.length > 1) {
    warnings.push(
      "multiple dedicated risk sections found; keep one risk chapter and use the top-level risks array for its items",
    );
  }
  if (dedicatedRiskSections.length && !(data.risks || []).length) {
    warnings.push(
      "dedicated risk content should use the top-level risks array so risk structure and severity can be validated",
    );
  }

  for (const [index, risk] of (data.risks || []).entries()) {
    if (typeof risk === "string") {
      if (!risk.trim()) errors.push(`risk[${index}] must not be empty`);
      warnings.push(
        `risk[${index}] uses a legacy string and will be rendered visibly; prefer {title, detail, severity, source_ids}`,
      );
      continue;
    }
    if (!risk || typeof risk !== "object" || Array.isArray(risk)) {
      errors.push(`risk[${index}] must be an object with title and detail`);
      continue;
    }
    if (!String(risk.title || "").trim()) errors.push(`risk[${index}].title is required`);
    if (!String(risk.detail || "").trim()) errors.push(`risk[${index}].detail is required`);
    if (risk.severity && !["high", "medium", "low"].includes(risk.severity)) {
      errors.push(`risk[${index}].severity must be high, medium, or low`);
    }
    if (risk.direction && !["positive", "negative", "mixed"].includes(risk.direction)) {
      errors.push(`risk[${index}].direction must be positive, negative, or mixed`);
    }
  }
  for (const [index, gap] of (data.data_gaps || []).entries()) {
    if (typeof gap !== "string" || !gap.trim()) {
      errors.push(`data_gaps[${index}] must be a non-empty string`);
    } else if (/(?:PDF|文档).{0,8}(?:截断|缺页|未完整)|(?:解析|提取|抓取|工具).{0,8}(?:失败|异常|未获取)/i.test(gap)) {
      errors.push(
        `data_gaps[${index}] describes an internal retrieval process; rewrite it as a decision-relevant disclosure limitation`,
      );
    }
  }

  const sourceIds = (data.sources || []).map((source) => source.id);
  const sourceSet = new Set(sourceIds);
  const officialDocuments = new Map(
    (data.research?.official_documents || []).map((document) => [document.id, document]),
  );
  if (sourceSet.size !== sourceIds.length) errors.push("duplicate source ids");
  for (const source of data.sources || []) {
    for (const key of ["id", "title", "publisher", "date", "period", "location", "level"]) {
      if (!source[key]) errors.push(`source ${source.id || "unknown"} missing ${key}`);
    }
    if (officialLevels.has(source.level)) {
      if (!source.url) {
        errors.push(`official source ${source.id || "unknown"} missing real URL`);
      } else {
        const result = validateOfficialUrl(source.url, data.research || {}, {
          allowFixture,
        });
        if (!result.ok) {
          errors.push(`official source ${source.id || "unknown"} URL: ${result.reason}`);
        }
      }
      const document = officialDocuments.get(source.id);
      if (!document) {
        errors.push(`official source ${source.id || "unknown"} is absent from research gate`);
      } else if (document.url !== source.url) {
        errors.push(`official source ${source.id} URL differs from research gate record`);
      }
    } else if (
      ["结构化数据", "一致预期", "外部背景"].includes(source.level) &&
      !source.url &&
      !(
        source.level === "结构化数据" &&
        Array.isArray(source.retrieval_methods) &&
        source.retrieval_methods.includes("MCP")
      )
    ) {
      errors.push(`external source ${source.id || "unknown"} missing real URL`);
    } else if (source.url) {
      try {
        const url = new URL(source.url);
        if (!["http:", "https:"].includes(url.protocol)) {
          errors.push(`source ${source.id || "unknown"} URL must use http or https`);
        }
      } catch {
        errors.push(`source ${source.id || "unknown"} has invalid URL`);
      }
    }
  }

  const referenced = new Set(collectSourceIds(data));
  for (const id of referenced) {
    if (!sourceSet.has(id)) errors.push(`unknown source reference: ${id}`);
  }

  const successfulOfficialIds = new Set(
    (data.research?.official_documents || [])
      .filter((document) => document.read_status === "success")
      .map((document) => document.id),
  );
  const requireOfficialEvidence = (label, ids) => {
    if (!Array.isArray(ids) || !ids.some((id) => successfulOfficialIds.has(id))) {
      errors.push(`${label} must cite a successfully read official report`);
    }
  };
  const requireEvidence = (label, ids) => {
    if (!Array.isArray(ids) || ids.length === 0) {
      errors.push(`${label} must cite at least one recorded source`);
    }
  };
  requireOfficialEvidence("headline", data.headline_source_ids);
  for (const [index, item] of (data.executive_summary || []).entries()) {
    requireEvidence(`executive_summary[${index}]`, item.source_ids);
  }
  for (const [index, risk] of (data.risks || []).entries()) {
    if (risk.severity === "high") {
      requireOfficialEvidence(`high risk[${index}]`, risk.source_ids);
    }
  }

  if (!data.company?.ticker) warnings.push("ticker is empty; this is allowed only when not disclosed or not applicable");
}

export function validateReportHtml(html, errors) {
  if (!/^<!doctype html>/i.test(html.trim())) errors.push("missing <!doctype html>");
  if (!/<meta charset="utf-8">/i.test(html)) errors.push("missing utf-8 charset");
  if (
    !/<meta name="generator" content="earnings-interpretation@[0-9a-z][0-9a-z.-]*">/i.test(
      html,
    )
  ) {
    errors.push("missing earnings template generator version");
  }
  if (!/<body\b[^>]*data-template="earnings-a4-v1"/i.test(html)) {
    errors.push("missing earnings-a4-v1 template marker");
  }
  if (/\{\{[A-Z0-9_]+\}\}/.test(html)) errors.push("unresolved template placeholder");
  if (/<script\b/i.test(html)) errors.push("script tags are not allowed");
  if (/<link\b[^>]*rel=["']?stylesheet/i.test(html)) errors.push("external stylesheets are not allowed");
  if (/@import\s+/i.test(html)) errors.push("CSS @import is not allowed");
  if (/<(?:img|iframe|embed)\b[^>]*(?:src|href)=["']https?:/i.test(html)) {
    errors.push("remote media dependencies are not allowed");
  }
  if (/<img\b(?![^>]*\balt=)[^>]*>/i.test(html)) errors.push("image missing alt text");
  if (/gradient\s*\(/i.test(html)) errors.push("gradients are not allowed");
  if (!/@page\s*\{[\s\S]*?size\s*:\s*A4\b/i.test(html)) {
    errors.push("missing A4 print page rule");
  }
  if (
    !/\.report-columns\s*\{[\s\S]*?display\s*:\s*block/i.test(
      html,
    )
  ) {
    errors.push("missing stable full-width report flow");
  }
  if (
    !/\.section-pair\s*\{[\s\S]*?grid-template-columns\s*:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/i.test(
      html,
    )
  ) {
    errors.push("missing balanced two-column section-pair layout");
  }
  if (
    /\.(?:metric-table|data-table|source-table)\s*\{[^}]*display\s*:\s*block/i.test(
      html,
    )
  ) {
    errors.push("responsive layout must not convert academic tables into block elements");
  }
  if (!/<ol class="thesis-list">/i.test(html)) {
    errors.push("core conclusions must use an editorial numbered list");
  }
  const hasRiskSection = /<section class="[^"]*report-risk-section[^"]*"/i.test(html);
  if (hasRiskSection && !/<table class="risk-table">/i.test(html)) {
    errors.push("missing structured risk table");
  }
  if (hasRiskSection && !/<th>风险维度<\/th>[\s\S]*?<th>下一期需验证指标<\/th>/i.test(html)) {
    errors.push("risk table is missing decision-oriented columns");
  }
  const renderedRiskHeadings = [...html.matchAll(/<h2\b[^>]*>([\s\S]*?)<\/h2>/gi)]
    .map((match) => normalizedSectionTitle(visibleHtmlText(match[1])))
    .filter((title) => dedicatedRiskTitles.has(title));
  if (renderedRiskHeadings.length > 1) {
    errors.push("duplicate dedicated risk chapters were rendered");
  }
  if (/(?:^|\n)\s*tbody tr \+ tr\s*\{/i.test(html)) {
    errors.push("financial tables must not contain generic body-row separators");
  }
  if (/\.thesis-list\s*\{[^}]*border-(?:top|bottom)\s*:/i.test(html)) {
    errors.push("core conclusions must not be styled as a ruled table");
  }
  if (!/<p class="report-deck"[^>]*aria-label="核心判断"/i.test(html)) {
    errors.push("missing compact headline deck");
  }
  if (html.length < 5000) errors.push("report is unexpectedly small");

  for (const tag of ["html", "head", "body", "main", "section", "table", "figure", "svg"]) {
    const open = countMatches(html, new RegExp(`<${tag}\\b`, "gi"));
    const close = countMatches(html, new RegExp(`</${tag}>`, "gi"));
    if (open !== close) errors.push(`unbalanced <${tag}> tags: ${open} open, ${close} close`);
  }

  const tableCount = countMatches(html, /<table\b/gi);
  const captionCount = countMatches(html, /<caption\b/gi);
  if (tableCount !== captionCount) {
    errors.push(`academic table captions missing: ${tableCount} tables, ${captionCount} captions`);
  }
  const figureCount = countMatches(html, /<figure\b/gi);
  const figureCaptionCount = countMatches(html, /<figcaption\b/gi);
  if (figureCount !== figureCaptionCount) {
    errors.push(
      `academic figure captions missing: ${figureCount} figures, ${figureCaptionCount} captions`,
    );
  }

  if (!/<section class="[^"]*report-metrics-section[^"]*"/i.test(html)) {
    errors.push("missing rendered key-metrics section");
  }
  if (!html.includes("来源与证据索引")) {
    errors.push("missing required rendered section: 来源与证据索引");
  }
}

const isDirectRun =
  process.argv[1] &&
  import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;

if (isDirectRun) {
  const args = parseArgs(process.argv.slice(2));
  if (!args.input) {
    process.stderr.write(
      "Usage: node scripts/validate-report.mjs --input report.html [--data report.json]\n",
    );
    process.exit(1);
  }

  const htmlPath = path.resolve(args.input);
  const html = fs.readFileSync(htmlPath, "utf8");
  const errors = [];
  const warnings = [];

  validateReportHtml(html, errors);
  if (args.data) {
    const data = JSON.parse(fs.readFileSync(path.resolve(args.data), "utf8"));
    validateReportData(data, errors, warnings, {
      allowFixture: args["allow-fixture"] === true,
    });
  }

  const result = {
    ok: errors.length === 0,
    input: htmlPath,
    bytes: Buffer.byteLength(html),
    errors,
    warnings,
  };
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  if (errors.length) process.exit(1);
}
