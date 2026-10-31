import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const skillDir = path.resolve(scriptDir, "..");

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

function fail(message) {
  throw new Error(message);
}

function readSkillVersion() {
  const skillText = fs.readFileSync(path.join(skillDir, "SKILL.md"), "utf8");
  const match = skillText.match(/Plugin version[：:]\s*`([^`]+)`/);
  if (!match) fail("SKILL.md is missing Plugin version");
  return match[1];
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function emphasizeNumbers(value) {
  const text = String(value ?? "");
  const expression = /[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(?:%|pct|个百分点|倍|亿元|万元|元|亿|万|人|家|吨|股)/giu;
  let result = "";
  let cursor = 0;
  for (const match of text.matchAll(expression)) {
    const index = match.index ?? 0;
    result += escapeHtml(text.slice(cursor, index));
    result += `<strong class="inline-number">${escapeHtml(match[0])}</strong>`;
    cursor = index + match[0].length;
  }
  return result + escapeHtml(text.slice(cursor));
}

function safeUrl(value) {
  if (!value) return "";
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}

function bundledCompanyLogo(company) {
  const ticker = String(company.ticker || "").replace(/\D/g, "").padStart(5, "0");
  const name = String(company.name || "").toLowerCase();
  if (ticker === "03690" || name.includes("meituan") || name.includes("美团")) {
    return path.join(skillDir, "assets", "company-logos", "meituan.png");
  }
  return "";
}

function resolveCompanyLogo(company, inputPath) {
  if (company.logo_data_uri) {
    if (!/^data:image\/(?:png|jpeg|webp);base64,[a-z0-9+/=\s]+$/i.test(company.logo_data_uri)) {
      fail("company.logo_data_uri must be a base64 PNG, JPEG, or WebP data URI");
    }
    return company.logo_data_uri.replace(/\s+/g, "");
  }
  const bundledLogo = bundledCompanyLogo(company);
  const logoReference = company.logo_path || bundledLogo;
  if (!logoReference) return "";

  let logoPath = path.isAbsolute(logoReference)
    ? logoReference
    : path.resolve(path.dirname(inputPath), logoReference);
  if (!fs.existsSync(logoPath) && !path.isAbsolute(logoReference)) {
    const skillRelativePath = path.resolve(skillDir, logoReference);
    if (fs.existsSync(skillRelativePath)) {
      logoPath = skillRelativePath;
    } else if (bundledLogo && fs.existsSync(bundledLogo)) {
      logoPath = bundledLogo;
    }
  }
  const extension = path.extname(logoPath).toLowerCase();
  const mimeByExtension = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
  };
  const mime = mimeByExtension[extension];
  if (!mime) fail("company.logo_path must point to a PNG, JPEG, WebP, or SVG file");
  if (!fs.existsSync(logoPath)) fail(`company logo not found: ${logoPath}`);
  const logo = fs.readFileSync(logoPath);
  if (logo.byteLength > 3 * 1024 * 1024) fail("company logo exceeds 3 MB");
  if (extension === ".svg") {
    const svg = logo.toString("utf8");
    if (
      !/<svg\b/i.test(svg) ||
      /<(?:script|foreignObject)\b/i.test(svg) ||
      /\son[a-z]+\s*=/i.test(svg) ||
      /(?:href|xlink:href)\s*=\s*["']https?:/i.test(svg)
    ) {
      fail("company SVG logo must be self-contained and must not contain active content");
    }
  }
  return `data:${mime};base64,${logo.toString("base64")}`;
}

function companyMonogram(company) {
  const preferred = String(company.short_name || "").trim();
  if (preferred) return preferred.slice(0, 4);
  const name = String(company.name || "").replace(/\s+/g, "");
  const han = [...name].filter((character) => /\p{Script=Han}/u.test(character));
  if (han.length) return han.slice(0, 2).join("");
  const initials = String(company.name || "")
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
  return (initials || company.ticker || "ER").slice(0, 3);
}

function displayTicker(company) {
  const ticker = String(company.ticker || "").trim();
  if (!ticker || /\.[A-Z]{2,4}$/i.test(ticker)) return ticker;
  const market = String(company.market || "").trim().toUpperCase();
  if (market === "A" && /^6/.test(ticker)) return `${ticker}.SH`;
  if (market === "A" && /^(?:0|3)/.test(ticker)) return `${ticker}.SZ`;
  if (market === "HK" && /^\d+$/.test(ticker)) return `${ticker.padStart(5, "0")}.HK`;
  return ticker;
}

function renderCompanyIdentity(company, inputPath) {
  const logo = resolveCompanyLogo(company, inputPath);
  const mark = logo
    ? `<span class="company-mark has-logo"><img src="${escapeHtml(logo)}" alt="${escapeHtml(
        company.logo_alt || `${company.name} Logo`,
      )}"></span>`
    : "";
  const listing = [
    displayTicker(company),
    company.sector || company.industry,
    company.subsector,
    company.report_date || company.data_as_of,
  ]
    .filter(Boolean)
    .join("  |  ") || "上市公司";
  return `<div class="company-identity">
    ${mark}
    <div class="company-name">
      <strong>${escapeHtml(company.name)}</strong>
      <span>${escapeHtml(listing)}</span>
    </div>
  </div>`;
}

function toneClass(tone) {
  return ["positive", "negative", "warning", "neutral"].includes(tone)
    ? `tone-${tone}`
    : "tone-neutral";
}

function sourceRefs(ids, sourceNumber) {
  if (!Array.isArray(ids) || ids.length === 0) return "";
  return ids
    .filter((id) => sourceNumber.has(id))
    .map((id) => {
      const number = sourceNumber.get(id);
      return `<a class="source-ref" href="#source-${number}" aria-label="来源 ${number}">[${number}]</a>`;
    })
    .join("");
}

function renderMeta(data) {
  const company = data.company || {};
  const items = [
    `报告日期：${company.report_date || data.market_snapshot?.as_of || company.publication_date || company.data_as_of}`,
    company.report_period ? `基于${company.report_period}` : "",
    [company.currency, company.unit].filter(Boolean).length
      ? `货币单位：${[company.currency, company.unit].filter(Boolean).join(" · ")}`
      : "",
  ].filter(Boolean);
  return `<p class="report-meta">${items
    .map((value) => `<span>${escapeHtml(value)}</span>`)
    .join("")}</p>`;
}

function isMarketPlaceholder(value) {
  const text = String(value || "").trim();
  return (
    !text ||
    /^(?:[-—–]|n\/?a)$/i.test(text) ||
    /^(?:待核验|未形成|未获取|不可用|暂无|未披露)(?:[（(].*)?$/i.test(text)
  );
}

function renderMarketSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return "";
  if (snapshot.lookup_status === "unavailable") return "";

  const currentPrice = isMarketPlaceholder(snapshot.current_price)
    ? ""
    : snapshot.current_price;
  const marketCap = isMarketPlaceholder(snapshot.market_cap)
    ? ""
    : snapshot.market_cap;
  if (!currentPrice || !marketCap) return "";

  const rows = [
    ["当前价", currentPrice],
    ["当前总市值", marketCap],
    ["参考买入区间", isMarketPlaceholder(snapshot.buy_range) ? "" : snapshot.buy_range],
    ["参考卖出区间", isMarketPlaceholder(snapshot.sell_range) ? "" : snapshot.sell_range],
    ["数据截至", snapshot.as_of],
  ].filter(([, value]) => String(value || "").trim());
  return `<aside class="market-snapshot" aria-label="市场快照">
    <h2>市场快照</h2>
    <dl>${rows
      .map(
        ([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`,
      )
      .join("")}</dl>
    <p>${escapeHtml(snapshot.source_note || snapshot.disclaimer || "金融 MCP 结构化行情；仅作观察参考，非投资建议")}</p>
  </aside>`;
}

function cleanNumberedTitle(value, type) {
  const expression =
    type === "figure"
      ? /^\s*图\s*[A-Za-z0-9一二三四五六七八九十]+\s*[：:、.\-—　 ]*/
      : /^\s*表\s*[A-Za-z0-9一二三四五六七八九十]+\s*[：:、.\-—　 ]*/;
  return String(value || "").replace(expression, "").trim();
}

function cleanAnnotation(value, label) {
  return String(value || "")
    .replace(new RegExp(`^\\s*${label}\\s*[：:]\\s*`), "")
    .trim();
}

function nextTableCaption(context, title) {
  context.table += 1;
  return `<caption>表 ${context.table}　${escapeHtml(
    cleanNumberedTitle(title, "table") || "财务数据",
  )}</caption>`;
}

function tableNotes(note, source) {
  const parts = [];
  const cleanNote = cleanAnnotation(note, "注");
  const cleanSource = cleanAnnotation(source, "资料来源");
  if (cleanNote) parts.push(`<span>注：${escapeHtml(cleanNote)}</span>`);
  if (cleanSource) parts.push(`<span>资料来源：${escapeHtml(cleanSource)}</span>`);
  if (!parts.length) return "";
  return `<div class="table-notes">${parts.join("<br>")}</div>`;
}

function modeSectionLabels(mode) {
  const defaults = {
    executiveSummary: "核心结论",
    keyMetrics: "关键财务指标",
    risks: "风险因素",
    dataGaps: "数据局限性说明",
  };
  const labels = {
    brief: {
      executiveSummary: "核心判断",
      keyMetrics: "关键数据",
      risks: "关键风险",
      dataGaps: "口径与局限",
    },
    preview: {
      executiveSummary: "预期框架",
      keyMetrics: "关键预测指标",
      risks: "情景风险",
      dataGaps: "预测口径与缺口",
    },
    update: {
      executiveSummary: "更新结论",
      keyMetrics: "实际与预测关键指标",
      risks: "逻辑风险",
      dataGaps: "更新口径与缺口",
    },
  };
  return { ...defaults, ...(labels[mode] || {}) };
}

function registerSection(context, title) {
  context.section += 1;
  const id = `report-section-${context.section}`;
  context.navigation.push({ id, title });
  return id;
}

function renderNavigation(context) {
  if (!context.navigation.length) return "";
  const links = context.navigation
    .map(
      ({ id, title }) =>
        `<li><a href="#${id}">${escapeHtml(title)}</a></li>`,
    )
    .join("");
  return `<nav class="report-navigation" aria-label="报告章节导航">
    <span class="report-navigation-label">章节</span>
    <ol>${links}</ol>
  </nav>`;
}

function renderExecutiveSummary(items, sourceNumber, context, heading) {
  if (!items?.length) return "";
  const sectionId = registerSection(context, heading);
  const conclusions = items
    .map(
      (item, index) =>
        `<li class="${toneClass(item.tone)}">
          <span class="thesis-number" aria-hidden="true">${index + 1}</span>
          <div class="thesis-copy">
            <strong>${escapeHtml(item.label)}</strong>
            <p>${emphasizeNumbers(item.conclusion)}${sourceRefs(item.source_ids, sourceNumber)}</p>
          </div>
        </li>`,
    )
    .join("");
  return `<section class="report-section report-lead-section"><h2 id="${sectionId}">${escapeHtml(heading)}</h2>
    <ol class="thesis-list">${conclusions}</ol>
  </section>`;
}

function derivedMetricsSummary(items) {
  const clauses = (items || [])
    .filter((item) => item.interpretation || item.change)
    .slice(0, 3)
    .map((item) => {
      const change = item.change && item.change !== "—" ? ` ${item.change}` : "";
      const interpretation = item.interpretation ? `，${item.interpretation}` : "";
      return `${item.label}${change}${interpretation}`;
    });
  return clauses.length ? `从关键指标看，${clauses.join("；")}。` : "";
}

function renderMetrics(items, sourceNumber, context, heading, summary) {
  if (!items?.length) return "";
  const sectionId = registerSection(context, heading);
  const rows = items
    .map(
      (item) => `<tr>
        <td>${escapeHtml(item.label)}</td>
        <td class="metric-value ${toneClass(item.tone)}">${escapeHtml(item.value)}${sourceRefs(
          item.source_ids,
          sourceNumber,
        )}</td>
        <td>${escapeHtml(item.comparison || "—")}</td>
        <td class="${toneClass(item.tone)}">${escapeHtml(item.change || "—")}</td>
        <td>${escapeHtml(item.interpretation || "")}</td>
      </tr>`,
    )
    .join("");
  const interpretation = String(summary || derivedMetricsSummary(items)).trim();
  return `<section class="report-section report-metrics-section"><h2 id="${sectionId}">${escapeHtml(heading)}</h2>
    ${interpretation ? `<p class="metrics-interpretation">${emphasizeNumbers(interpretation)}</p>` : ""}
    <div class="table-figure">
      <table class="metric-table">
        ${nextTableCaption(context, "关键财务指标及比较")}
        <thead><tr><th>指标</th><th>本期</th><th>比较基准</th><th>变化</th><th>解读</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      ${tableNotes("金额、币种和单位以报告口径为准；变化值按披露数据或分析计算。", "")}
    </div>
  </section>`;
}

function renderCell(cell, sourceNumber) {
  if (cell && typeof cell === "object" && !Array.isArray(cell)) {
    return `<td class="${toneClass(cell.tone)}">${escapeHtml(cell.value)}${sourceRefs(
      cell.source_ids,
      sourceNumber,
    )}</td>`;
  }
  return `<td>${escapeHtml(cell ?? "")}</td>`;
}

function normalizeTableRows(rows, columnCount) {
  const normalized = [];
  let pendingCells = [];
  const flushPending = () => {
    while (pendingCells.length) {
      normalized.push(pendingCells.splice(0, columnCount));
    }
  };
  for (const row of rows || []) {
    if (Array.isArray(row)) {
      flushPending();
      normalized.push(row);
    } else {
      pendingCells.push(row);
      if (pendingCells.length === columnCount) flushPending();
    }
  }
  flushPending();
  return normalized;
}

function renderTable(table, sourceNumber, context, fallbackTitle) {
  if (!table?.columns?.length) return "";
  const header = table.columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("");
  const rows = normalizeTableRows(table.rows, table.columns.length)
    .map((row) => `<tr>${row.map((cell) => renderCell(cell, sourceNumber)).join("")}</tr>`)
    .join("");
  const note = table.note || table.caption || "";
  return `<div class="table-figure">
    <table class="data-table">
      ${nextTableCaption(context, table.title || fallbackTitle || "财务数据")}
      <thead><tr>${header}</tr></thead>
      <tbody>${rows}</tbody>
    </table>
    ${tableNotes(note, table.source)}
  </div>`;
}

function chartScale(chart) {
  const values = chart.series
    .flatMap((series) => series.values)
    .filter((value) => Number.isFinite(value));
  if (!values.length) return { min: 0, max: 1 };
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const min = rawMin > 0 ? 0 : rawMin;
  const max = rawMax === min ? min + 1 : rawMax;
  const padding = (max - min) * 0.08;
  return { min: min < 0 ? min - padding : 0, max: max + padding };
}

function renderChart(chart, context) {
  if (!chart?.labels?.length || !chart?.series?.length) return "";
  context.figure += 1;
  const width = 640;
  const height = 300;
  const plot = { left: 68, top: 36, right: 22, bottom: 68 };
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const scale = chartScale(chart);
  const palette = ["#153a66", "#6f89a8", "#9a7044"];
  const x = (index) =>
    plot.left + (chart.labels.length === 1 ? plotWidth / 2 : (index * plotWidth) / (chart.labels.length - 1));
  const labelX = (index) =>
    chart.type === "bar"
      ? plot.left + ((index + 0.5) * plotWidth) / chart.labels.length
      : x(index);
  const y = (value) =>
    plot.top + plotHeight - ((value - scale.min) / (scale.max - scale.min)) * plotHeight;
  const grid = Array.from({ length: 5 }, (_, index) => {
    const ratio = index / 4;
    const yPos = plot.top + ratio * plotHeight;
    const value = scale.max - ratio * (scale.max - scale.min);
    return `<line x1="${plot.left}" y1="${yPos}" x2="${width - plot.right}" y2="${yPos}" stroke="#e2e7ee" stroke-width="1"/>
      <text x="${plot.left - 9}" y="${yPos + 6}" text-anchor="end" fill="#667085" font-size="18">${escapeHtml(
        Number(value.toFixed(2)).toLocaleString("zh-CN"),
      )}</text>`;
  }).join("");
  const xLabels = chart.labels
    .map(
      (label, index) =>
        `<text x="${labelX(index)}" y="${height - 34}" text-anchor="middle" fill="#667085" font-size="18">${escapeHtml(
          label,
        )}</text>`,
    )
    .join("");

  let marks = "";
  if (chart.type === "bar") {
    const groupWidth = plotWidth / Math.max(chart.labels.length, 1);
    const barWidth = Math.min(28, (groupWidth * 0.68) / chart.series.length);
    marks = chart.series
      .map((series, seriesIndex) =>
        series.values
          .map((value, index) => {
            if (!Number.isFinite(value)) return "";
            const baseX =
              plot.left +
              index * groupWidth +
              groupWidth / 2 -
              (barWidth * chart.series.length) / 2;
            const yZero = y(0);
            const yValue = y(value);
            return `<rect x="${baseX + seriesIndex * barWidth}" y="${Math.min(
              yZero,
              yValue,
            )}" width="${Math.max(4, barWidth - 3)}" height="${Math.max(
              1,
              Math.abs(yZero - yValue),
            )}" fill="${palette[seriesIndex % palette.length]}"/>`;
          })
          .join(""),
      )
      .join("");
  } else {
    marks = chart.series
      .map((series, seriesIndex) => {
        let pathData = "";
        let drawing = false;
        const points = series.values
          .map((value, index) => {
            if (!Number.isFinite(value)) {
              drawing = false;
              return "";
            }
            const point = `${x(index)},${y(value)}`;
            pathData += `${drawing ? " L " : " M "}${point}`;
            drawing = true;
            return `<circle cx="${x(index)}" cy="${y(value)}" r="4" fill="${
              palette[seriesIndex % palette.length]
            }"/>`;
          })
          .join("");
        return `<path d="${pathData.trim()}" fill="none" stroke="${
          palette[seriesIndex % palette.length]
        }" stroke-width="3"/>${points}`;
      })
      .join("");
  }

  const legend = chart.series
    .map(
      (series, index) =>
        `<g transform="translate(${plot.left + index * 175},${height - 8})">
          <rect width="15" height="5" y="-5" fill="${palette[index % palette.length]}"/>
          <text x="22" y="0" fill="#475467" font-size="17">${escapeHtml(series.name)}</text>
        </g>`,
    )
    .join("");

  return `<figure class="chart-figure">
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(
      chart.title,
    )}" style="display:block;width:100%;height:auto">
      ${grid}${xLabels}${marks}${legend}
      <text x="${plot.left}" y="20" fill="#667085" font-size="18">${escapeHtml(
        chart.unit || "",
      )}</text>
    </svg>
    <figcaption>图 ${context.figure}　${escapeHtml(
      cleanNumberedTitle(chart.title, "figure"),
    )}</figcaption>
    <div class="figure-notes">
      ${chart.note ? `<span>注：${escapeHtml(cleanAnnotation(chart.note, "注"))}</span><br>` : ""}
      <span>资料来源：${escapeHtml(
        cleanAnnotation(chart.source, "资料来源") || "见文末证据索引。",
      )}</span>
    </div>
  </figure>`;
}

function stripSectionNumber(value) {
  return String(value || "")
    .replace(/^\s*(?:第\s*)?[一二三四五六七八九十0-9]+\s*[、.．：:]\s*/, "")
    .trim();
}

function registerAnalysisSection(context, title) {
  context.analysisSection += 1;
  const cleanTitle = stripSectionNumber(title) || "分析";
  const displayTitle = `${context.analysisSection}. ${cleanTitle}`;
  return {
    id: registerSection(context, displayTitle),
    displayTitle,
  };
}

function sectionKind(section) {
  const title = stripSectionNumber(section?.title);
  if (/现金流|资产负债/.test(title)) return "balance";
  if (/股东回报|估值|分红|回购/.test(title)) return "valuation";
  if (/成本|费用|盈利质量|利润率/.test(title)) return "profitability";
  if (/收入|产品|分部|业务结构/.test(title)) return "revenue";
  return "general";
}

function renderParagraphs(items, className = "") {
  if (!items?.length) return "";
  return `<div${className ? ` class="${className}"` : ""}>${items
    .map((paragraph) => `<p>${emphasizeNumbers(paragraph)}</p>`)
    .join("")}</div>`;
}

function renderBullets(items, className = "") {
  if (!items?.length) return "";
  return `<ul${className ? ` class="${className}"` : ""}>${items
    .map((bullet) => `<li>${emphasizeNumbers(bullet)}</li>`)
    .join("")}</ul>`;
}

function renderInterpretation(section, heading = "解读") {
  const paragraphs = renderParagraphs(section.paragraphs || []);
  const bullets = renderBullets(section.bullets || []);
  if (!paragraphs && !bullets && !section.insight) return "";
  return `<div class="interpretation-panel">
    <h3>${escapeHtml(heading)}</h3>
    ${section.insight ? `<p class="interpretation-insight">${emphasizeNumbers(section.insight)}</p>` : ""}
    ${paragraphs}${bullets}
  </div>`;
}

function renderValuationBody(section, table) {
  const bullets = section.bullets || [];
  let signals = bullets.filter((bullet) => /下一|关注|验证|若|催化|风险/.test(bullet));
  let judgments = bullets.filter((bullet) => !signals.includes(bullet));
  if (!signals.length && judgments.length > 1) signals = judgments.splice(-1);
  const judgmentCopy = renderParagraphs(section.paragraphs || []) + renderBullets(judgments);
  const signalCopy = renderBullets(signals, "verification-list");
  const decisionGrid = judgmentCopy || signalCopy || section.insight
    ? `<div class="valuation-decision-grid">
        <div><h3>估值判断</h3>${section.insight ? `<p>${emphasizeNumbers(section.insight)}</p>` : ""}${judgmentCopy}</div>
        <div><h3>观点与验证信号</h3>${signalCopy || "<p>结合下一期正式披露继续验证。</p>"}</div>
      </div>`
    : "";
  return `${table}${decisionGrid}`;
}

function renderSection(section, sourceNumber, context) {
  const heading = registerAnalysisSection(context, section.title);
  const refs = sourceRefs(section.source_ids, sourceNumber);
  const kind = sectionKind(section);
  const summary = section.summary
    ? `<p class="section-lead">${emphasizeNumbers(section.summary)}${refs}</p>`
    : "";
  const table = renderTable(section.table, sourceNumber, context, section.title);
  const chart = renderChart(section.chart, context);
  const interpretation = renderInterpretation(
    section,
    kind === "balance" ? "这意味着什么" : kind === "profitability" ? "利润变化的原因" : "解读",
  );

  let body = "";
  if (kind === "valuation") {
    body = renderValuationBody(section, table);
  } else if (kind === "balance" && table && interpretation) {
    body = `<div class="section-analysis-grid section-analysis-grid-balance">
      <div class="evidence-panel">${table}</div>
      ${interpretation}
    </div>`;
  } else if (chart && table) {
    body = `<div class="section-evidence-grid">
      <div class="evidence-panel">${chart}</div>
      <div class="evidence-panel">${table}${
        section.insight ? `<p class="panel-support"><strong>值得关注：</strong>${emphasizeNumbers(section.insight)}</p>` : ""
      }</div>
    </div>${renderInterpretation({ paragraphs: section.paragraphs, bullets: section.bullets }, "解读")}`;
  } else if ((chart || table) && interpretation) {
    body = `<div class="section-analysis-grid">
      <div class="evidence-panel">${chart || table}</div>
      ${interpretation}
    </div>`;
  } else {
    body = `${chart || table}${interpretation}`;
  }

  return `<section class="report-section report-analysis-section section-${kind}" data-layout="full">
    <h2 id="${heading.id}">${escapeHtml(heading.displayTitle)}</h2>
    ${summary}
    ${body}
    ${!section.summary && refs ? `<p class="source-note">主要证据${refs}</p>` : ""}
  </section>`;
}

function renderSections(sections, sourceNumber, context) {
  return (sections || [])
    .map((section) => renderSection(section, sourceNumber, context))
    .join("");
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
]);

function normalizedSectionTitle(value) {
  return stripSectionNumber(value).replace(/[\s：:、，,。.!！?？/／·—_-]+/g, "");
}

function isDedicatedRiskSection(section) {
  return dedicatedRiskTitles.has(normalizedSectionTitle(section?.title));
}

function splitDedicatedRiskSection(sections, risks) {
  const items = sections || [];
  if (!risks?.length) return { sections: items, riskSection: null };
  const index = items.findIndex(isDedicatedRiskSection);
  if (index < 0) return { sections: items, riskSection: null };
  return {
    sections: items.filter((_, itemIndex) => itemIndex !== index),
    riskSection: items[index],
  };
}

function normalizeRisk(risk, fallbackSourceIds = []) {
  if (typeof risk === "string") {
    return {
      title: risk.trim(),
      detail: "",
      severity: "medium",
      direction: "negative",
      next_metric: "下一期相关披露",
      source_ids: fallbackSourceIds,
      legacy: true,
    };
  }
  return {
    title: String(risk?.title || "").trim(),
    detail: String(risk?.detail || "").trim(),
    severity: ["high", "medium", "low"].includes(risk?.severity)
      ? risk.severity
      : "medium",
    direction: ["positive", "negative", "mixed"].includes(risk?.direction)
      ? risk.direction
      : "negative",
    next_metric: String(risk?.next_metric || risk?.watch_metric || "下一期相关披露").trim(),
    source_ids: Array.isArray(risk?.source_ids)
      ? risk.source_ids
      : fallbackSourceIds,
    legacy: false,
  };
}

function risksForRendering(risks, riskSection) {
  const fallbackSourceIds = riskSection?.source_ids || [];
  const normalized = (risks || [])
    .map((risk) => normalizeRisk(risk, fallbackSourceIds))
    .filter((risk) => risk.title || risk.detail);
  const containsLegacyRisk = normalized.some((risk) => risk.legacy);
  if (containsLegacyRisk && riskSection?.bullets?.length) {
    return riskSection.bullets
      .map((bullet) => normalizeRisk(bullet, fallbackSourceIds))
      .filter((risk) => risk.title);
  }
  return normalized;
}

function renderRisks(risks, sourceNumber, context, heading, riskSection) {
  if (!risks?.length) return "";
  const importanceLabel = { high: "高", medium: "中高", low: "中" };
  const directionLabel = { positive: "正面", negative: "负面", mixed: "双向" };
  const normalizedRisks = risksForRendering(risks, riskSection);
  if (!normalizedRisks.length) return "";
  const sectionHeading = registerAnalysisSection(context, riskSection?.title || heading);
  const rows = normalizedRisks
    .map(
      (risk) => `<tr>
        <th scope="row">${escapeHtml(risk.title)}</th>
        <td>${emphasizeNumbers(risk.detail || risk.title)}${sourceRefs(risk.source_ids, sourceNumber)}</td>
        <td class="risk-direction tone-${risk.direction === "positive" ? "positive" : risk.direction === "negative" ? "negative" : "warning"}">${directionLabel[risk.direction]}</td>
        <td class="risk-importance severity-${risk.severity}">${importanceLabel[risk.severity]}</td>
        <td>${escapeHtml(risk.next_metric)}</td>
      </tr>`,
    )
    .join("");
  const intro = riskSection
    ? `${
        riskSection.summary
          ? `<p class="section-lead">${emphasizeNumbers(riskSection.summary)}${sourceRefs(
              riskSection.source_ids,
              sourceNumber,
            )}</p>`
          : ""
      }${(riskSection.paragraphs || [])
        .map((paragraph) => `<p>${emphasizeNumbers(paragraph)}</p>`)
        .join("")}`
    : "";
  context.table += 1;
  return `<section class="report-section report-risk-section" data-layout="full"><h2 id="${sectionHeading.id}">${escapeHtml(
    sectionHeading.displayTitle,
  )}</h2>
    ${intro}
    <div class="table-figure risk-table-wrap">
      <table class="risk-table">
        <caption>表 ${context.table}　风险因素与验证指标</caption>
        <thead><tr><th>风险维度</th><th>关键证据或现状</th><th>方向</th><th>重要性</th><th>下一期需验证指标</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  </section>`;
}

function canBalanceDataGaps(items) {
  if (!Array.isArray(items) || items.length < 2 || items.length > 4) return false;
  const lengths = items.map((item) => String(item || "").trim().length);
  if (lengths.some((length) => length === 0 || length > 220)) return false;
  const shortest = Math.min(...lengths);
  const longest = Math.max(...lengths);
  return longest / shortest <= 1.6;
}

function renderDataGaps(items, context, heading, data) {
  const gaps = (items || []).filter((item) => String(item || "").trim());
  const scope = `本报告基于公司已披露的${data.company?.report_period || "本期"}正式报告与公开信息，未纳入报告日后尚未披露的经营变化；相关判断用于理解已披露信息，不构成投资建议。`;
  const detail = gaps.length ? ` 另需注意：${gaps.join("；")}。` : "";
  const sectionId = registerSection(context, heading);
  return `<section class="report-section report-data-gaps-section" data-layout="full"><h2 id="${sectionId}">${escapeHtml(
    heading,
  )}</h2>
    <p class="data-limit-note">${emphasizeNumbers(`${scope}${detail}`)}</p>
  </section>`;
}

function renderSources(sources, context) {
  const sectionTitle = "来源与证据索引";
  const sectionId = registerSection(context, sectionTitle);
  context.table += 1;
  const tableTitle = `表 ${context.table}　来源与证据索引`;
  const rows = sources
    .map((source, index) => {
      const number = index + 1;
      const url = safeUrl(source.url);
      const title = url
        ? `<a href="${escapeHtml(url)}">${escapeHtml(source.title)}</a>`
        : escapeHtml(source.title);
      const retrievalMethods = Array.isArray(source.retrieval_methods)
        ? source.retrieval_methods.filter(Boolean)
        : [];
      const retrieval = retrievalMethods.length ? retrievalMethods.join(" / ") : "官方直链";
      return `<tr id="source-${number}">
        <td>${number}</td>
        <td>${title}</td>
        <td>${escapeHtml(source.publisher)}</td>
        <td>${escapeHtml(source.date)}</td>
        <td>${escapeHtml(source.period)}</td>
        <td>${escapeHtml(source.location)}</td>
        <td><strong class="source-method">${escapeHtml(retrieval)}</strong><span class="source-level">${escapeHtml(source.level)}</span></td>
      </tr>`;
    })
    .join("");
  return `<section class="report-section report-appendix-section" data-layout="full"><h2 id="${sectionId}">${sectionTitle}</h2>
    <p class="source-intro">本报告内容基于公开财报及实际检索或工具返回的可核验信息整理；来源表仅保留支持正文判断的材料。</p>
    <details class="source-details" open>
      <summary><span class="source-table-heading">${tableTitle}</span><span class="source-toggle-button">查看或收起全部来源 · ${sources.length} 条</span></summary>
      <div class="source-details-content table-figure">
      <table class="source-table">
        <caption class="visually-hidden">${tableTitle}</caption>
        <thead><tr><th>#</th><th>材料</th><th>发布主体</th><th>日期</th><th>报告期</th><th>页码/章节</th><th>获取方式 / 层级</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      ${tableNotes("来源层级表示证据性质，不代表对信息质量的机械排序。", "")}
      </div>
    </details>
  </section>`;
}

function validateMinimumData(data) {
  const modes = ["brief", "standard", "deep", "preview", "update"];
  if (!modes.includes(data.mode)) fail(`Invalid mode: ${data.mode}`);
  if (!data.title || !data.headline) fail("title and headline are required");
  if (!data.company?.name || !data.company?.report_period) {
    fail("company.name and company.report_period are required");
  }
  for (const key of ["executive_summary", "key_metrics", "sections", "sources"]) {
    if (!Array.isArray(data[key]) || data[key].length === 0) {
      fail(`${key} must be a non-empty array`);
    }
  }
}

export function renderReportFile({
  input,
  output,
  template,
  style,
  data: providedData,
} = {}) {
  if ((!input && !providedData) || !output) {
    fail("Usage: node scripts/render-report.mjs --input report.json --output report.html");
  }

  const inputPath = input ? path.resolve(input) : path.resolve("report.json");
  const outputPath = path.resolve(output);
  const templatePath = path.resolve(
    template || path.join(skillDir, "assets", "report-template.html"),
  );
  const stylePath = path.resolve(
    style || path.join(skillDir, "assets", "report-style.css"),
  );
  const data =
    providedData || JSON.parse(fs.readFileSync(inputPath, "utf8"));
  validateMinimumData(data);

  const templateText = fs.readFileSync(templatePath, "utf8");
  const css = fs.readFileSync(stylePath, "utf8");
  const sourceNumber = new Map(
    data.sources.map((source, index) => [source.id, index + 1]),
  );
  const numbering = { table: 0, figure: 0, section: 0, analysisSection: 0, navigation: [] };
  const labels = modeSectionLabels(data.mode);
  const sectionPlan = splitDedicatedRiskSection(data.sections, data.risks);
  const generator = `earnings-interpretation@${readSkillVersion()}`;
  const marketSnapshot = renderMarketSnapshot(data.market_snapshot);
  const disclaimer =
    data.disclaimer ||
    "以上内容基于公开财报信息整理，仅供参考，不构成任何投资建议。投资有风险，决策需谨慎。";

  const executiveSummary = renderExecutiveSummary(
    data.executive_summary,
    sourceNumber,
    numbering,
    labels.executiveSummary,
  );
  const keyMetrics = renderMetrics(
    data.key_metrics,
    sourceNumber,
    numbering,
    labels.keyMetrics,
    data.key_metrics_summary,
  );
  const reportSections = renderSections(sectionPlan.sections, sourceNumber, numbering);
  const risks = renderRisks(
    data.risks,
    sourceNumber,
    numbering,
    labels.risks,
    sectionPlan.riskSection,
  );
  const dataGaps = renderDataGaps(data.data_gaps, numbering, labels.dataGaps, data);
  const sources = renderSources(data.sources, numbering);

  const replacements = {
    DOCUMENT_TITLE: escapeHtml(data.title),
    GENERATOR: generator,
    INLINE_CSS: css,
    MODE: escapeHtml(data.mode),
    COMPANY_IDENTITY: renderCompanyIdentity(data.company, inputPath),
    REPORT_TITLE: escapeHtml(data.title),
    REPORT_META: renderMeta(data),
    MARKET_SNAPSHOT: marketSnapshot,
    MARKET_SNAPSHOT_CLASS: marketSnapshot ? " has-market-snapshot" : "",
    HEADLINE: `${emphasizeNumbers(data.headline)}${sourceRefs(
      data.headline_source_ids,
      sourceNumber,
    )}`,
    NAVIGATION: renderNavigation(numbering),
    EXECUTIVE_SUMMARY: executiveSummary,
    KEY_METRICS: keyMetrics,
    REPORT_SECTIONS: reportSections,
    RISKS: risks,
    DATA_GAPS: dataGaps,
    SOURCES: sources,
    DISCLAIMER: escapeHtml(disclaimer),
    DATA_AS_OF: escapeHtml(data.company.data_as_of),
  };

  let html = templateText;
  for (const [key, value] of Object.entries(replacements)) {
    html = html.replaceAll(`{{${key}}}`, value);
  }

  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, html, "utf8");
  return {
    ok: true,
    output: outputPath,
    bytes: Buffer.byteLength(html),
    html,
  };
}

const isDirectRun =
  process.argv[1] &&
  import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;

if (isDirectRun) {
  try {
    const args = parseArgs(process.argv.slice(2));
    const result = renderReportFile({
      input: args.input,
      output: args.output,
      template: args.template,
      style: args.style,
    });
    process.stdout.write(
      `${JSON.stringify({
        ok: result.ok,
        output: result.output,
        bytes: result.bytes,
      })}\n`,
    );
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.exit(1);
  }
}
