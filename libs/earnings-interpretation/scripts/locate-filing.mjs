#!/usr/bin/env node

import path from "node:path";
import { pathToFileURL } from "node:url";

const HKEX_STOCKS_URL =
  "https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_e.json";
const HKEX_SEARCH_URL = "https://www1.hkexnews.hk/search/titlesearch.xhtml";
const SEC_TICKERS_URL =
  "https://www.sec.gov/files/company_tickers_exchange.json";
const SEC_SUBMISSIONS_ROOT = "https://data.sec.gov/submissions";
const CNINFO_STOCKS_URL =
  "https://www.cninfo.com.cn/new/data/szse_stock.json";
const CNINFO_QUERY_URL =
  "https://www.cninfo.com.cn/new/hisAnnouncement/query";

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

function normalizeMarket(value) {
  const market = String(value || "").trim().toUpperCase();
  if (["HK", "HKG", "港股"].includes(market)) return "HK";
  if (["US", "USA", "美股"].includes(market)) return "US";
  if (["A", "CN", "CHINA", "A股"].includes(market)) return "A";
  throw new Error(`Unsupported market: ${value}. Use HK, US, or A.`);
}

function normalizeType(value) {
  const type = String(value || "").trim().toLowerCase();
  if (/annual|年报|年度/.test(type)) return "annual";
  if (/interim|half|半年|中报/.test(type)) return "interim";
  if (/quarter|季报|季度|q[1-4]/.test(type)) return "quarterly";
  if (/result|业绩|earnings/.test(type)) return "results";
  return type || "results";
}

function extractYear(value) {
  const match = String(value || "").match(/(?:19|20)\d{2}/);
  return match ? Number(match[0]) : null;
}

function quarterNumber(value) {
  const text = String(value || "").toLowerCase();
  const direct = text.match(/q([1-4])/);
  if (direct) return Number(direct[1]);
  if (/第一|一季|1st|first|three months|3 months/.test(text)) return 1;
  if (/第二|二季|2nd|second|six months|6 months|半年/.test(text)) return 2;
  if (/第三|三季|3rd|third|nine months|9 months/.test(text)) return 3;
  if (/第四|四季|4th|fourth|twelve months|12 months/.test(text)) return 4;
  return null;
}

function decodeHtml(value) {
  return String(value || "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&nbsp;/gi, " ")
    .replace(/&#(\d+);/g, (_, code) => String.fromCodePoint(Number(code)))
    .replace(/\s+/g, " ")
    .trim();
}

async function fetchOrThrow(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    signal: AbortSignal.timeout(25_000),
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${url}`);
  }
  return response;
}

function classifyTitle(title) {
  const text = title.toLowerCase();
  if (/annual report|年度报告|年報/.test(text)) return "annual_report";
  if (/interim report|半年度报告|中期報告|中报/.test(text)) {
    return "interim_report";
  }
  if (/quarter|季度报告|季報|three months|nine months/.test(text)) {
    return "quarterly_report";
  }
  return "results_announcement";
}

function scoreCandidate(candidate, { period, type }) {
  const title = candidate.title.toLowerCase();
  const year = extractYear(period);
  const quarter = quarterNumber(period);
  let score = 0;
  if (year && title.includes(String(year))) score += 8;
  if (year && candidate.report_date?.startsWith(String(year))) score += 8;
  if (year && candidate.publication_date?.startsWith(String(year))) score += 2;
  if (/report|results|业绩|業績|报告|報告/.test(title)) score += 3;
  if (/摘要|summary/.test(title)) score -= 4;
  if (/monthly return|share scheme|next day disclosure|翌日披露|月报表/.test(title)) {
    score -= 30;
  }
  if (type === "annual" && /annual|年度|年報/.test(title)) score += 10;
  if (
    type === "annual" &&
    ["10-K", "20-F", "40-F"].includes(candidate.form)
  ) {
    score += 10;
  }
  if (type === "interim" && /interim|半年度|中期|半年|six months/.test(title)) {
    score += 10;
  }
  if (
    type === "quarterly" &&
    /quarter|季度|季報|three months|nine months/.test(title)
  ) {
    score += 10;
  }
  if (type === "results" && /results|业绩|業績/.test(title)) score += 8;
  if (quarter === 1 && /first quarter|q1|第一季度|一季|three months/.test(title)) {
    score += 8;
  }
  if (quarter === 2 && /second quarter|q2|第二季度|二季|six months/.test(title)) {
    score += 8;
  }
  if (quarter === 3 && /third quarter|q3|第三季度|三季|nine months/.test(title)) {
    score += 8;
  }
  if (quarter === 4 && /fourth quarter|q4|第四季度|四季|annual/.test(title)) {
    score += 8;
  }
  return score;
}

function rankCandidates(candidates, request, limit = 10) {
  return candidates
    .map((candidate) => ({
      ...candidate,
      score: scoreCandidate(candidate, request),
    }))
    .filter((candidate) => candidate.score > 0)
    .sort(
      (left, right) =>
        right.score - left.score ||
        String(right.publication_date).localeCompare(
          String(left.publication_date),
        ),
    )
    .slice(0, limit);
}

function parseHkexRows(html) {
  const candidates = [];
  for (const match of html.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
    const row = match[1];
    const dateMatch = row.match(
      /class="[^"]*release-time[^"]*"[^>]*>[\s\S]*?(\d{2})\/(\d{2})\/(\d{4})\s+\d{2}:\d{2}/i,
    );
    const linkMatch = row.match(
      /<div class="doc-link">[\s\S]*?<a href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/i,
    );
    if (!dateMatch || !linkMatch) continue;
    const [, day, month, year] = dateMatch;
    const title = decodeHtml(linkMatch[2]);
    candidates.push({
      title,
      url: new URL(linkMatch[1], HKEX_SEARCH_URL).href,
      publication_date: `${year}-${month}-${day}`,
      document_type: classifyTitle(title),
      source: "HKEX",
    });
  }
  return candidates;
}

async function locateHkex(request) {
  const code = String(request.ticker).replace(/\D/g, "").padStart(5, "0");
  const stockResponse = await fetchOrThrow(HKEX_STOCKS_URL);
  const stocks = await stockResponse.json();
  const stock = stocks.find((item) => String(item.c).padStart(5, "0") === code);
  if (!stock) throw new Error(`HKEX stock code not found: ${code}`);

  const searchUrl = new URL(HKEX_SEARCH_URL);
  searchUrl.searchParams.set("category", "0");
  searchUrl.searchParams.set("market", "SEHK");
  searchUrl.searchParams.set("stockId", String(stock.i));
  const html = await (await fetchOrThrow(searchUrl)).text();
  const allCandidates = parseHkexRows(html);
  const current = rankCandidates(allCandidates, request);
  const comparison =
    request.type === "quarterly"
      ? rankCandidates(
          allCandidates.filter((candidate) =>
            /annual report|annual results|年度|全年|年報/i.test(candidate.title),
          ),
          {
            ...request,
            type: "annual",
            period: String((extractYear(request.period) || new Date().getFullYear()) - 1),
          },
          5,
        )
      : [];

  return {
    resolved_company: {
      name: stock.n,
      ticker: code,
      exchange_id: stock.i,
    },
    official_index_url: searchUrl.href,
    candidates: current.map((candidate) => ({
      ...candidate,
      role: "current",
    })),
    comparison_candidates: comparison.map((candidate) => ({
      ...candidate,
      role: "comparison",
    })),
  };
}

function secRecentRows(recent, cik) {
  const rows = [];
  for (let index = 0; index < (recent.form || []).length; index += 1) {
    const accession = recent.accessionNumber?.[index];
    const primaryDocument = recent.primaryDocument?.[index];
    if (!accession || !primaryDocument) continue;
    const accessionPath = accession.replace(/-/g, "");
    rows.push({
      title:
        recent.primaryDocDescription?.[index] ||
        `${recent.form[index]} filing for ${recent.reportDate?.[index] || recent.filingDate?.[index]}`,
      url: `https://www.sec.gov/Archives/edgar/data/${Number(cik)}/${accessionPath}/${primaryDocument}`,
      publication_date: recent.filingDate?.[index] || "",
      report_date: recent.reportDate?.[index] || "",
      form: recent.form[index],
      document_type: ["10-K", "20-F", "40-F"].includes(recent.form[index])
        ? "annual_report"
        : ["10-Q"].includes(recent.form[index])
          ? "quarterly_report"
          : "results_announcement",
      source: "SEC EDGAR",
    });
  }
  return rows;
}

function secFormsFor(type) {
  if (type === "annual") return new Set(["10-K", "20-F", "40-F"]);
  if (type === "quarterly") return new Set(["10-Q", "6-K"]);
  if (type === "interim") return new Set(["6-K"]);
  return new Set(["10-Q", "10-K", "20-F", "40-F", "6-K", "8-K"]);
}

async function locateSec(request) {
  const userAgent =
    request.userAgent ||
    process.env.SEC_USER_AGENT ||
    "earnings-interpretation/9.5 contact=not-provided";
  const headers = { "User-Agent": userAgent, Accept: "application/json" };
  const tickerPayload = await (
    await fetchOrThrow(SEC_TICKERS_URL, { headers })
  ).json();
  const fields = tickerPayload.fields;
  const tickerIndex = fields.indexOf("ticker");
  const cikIndex = fields.indexOf("cik");
  const nameIndex = fields.indexOf("name");
  const exchangeIndex = fields.indexOf("exchange");
  const ticker = String(request.ticker).trim().toUpperCase();
  const company = tickerPayload.data.find(
    (row) => String(row[tickerIndex]).toUpperCase() === ticker,
  );
  if (!company) throw new Error(`SEC ticker not found: ${ticker}`);
  const cik = String(company[cikIndex]).padStart(10, "0");
  const submissionsUrl = `${SEC_SUBMISSIONS_ROOT}/CIK${cik}.json`;
  const submissions = await (
    await fetchOrThrow(submissionsUrl, { headers })
  ).json();
  const all = secRecentRows(submissions.filings.recent, cik);
  const forms = secFormsFor(request.type);
  const current = rankCandidates(
    all.filter((candidate) => forms.has(candidate.form)),
    request,
  );
  const comparison =
    request.type === "quarterly"
      ? rankCandidates(
          all.filter((candidate) =>
            ["10-K", "20-F", "40-F"].includes(candidate.form),
          ),
          {
            ...request,
            type: "annual",
            period: String((extractYear(request.period) || new Date().getFullYear()) - 1),
          },
          5,
        )
      : [];
  return {
    resolved_company: {
      name: company[nameIndex],
      ticker,
      cik,
      exchange: company[exchangeIndex],
    },
    official_index_url: submissionsUrl,
    candidates: current.map((candidate) => ({
      ...candidate,
      role: "current",
    })),
    comparison_candidates: comparison.map((candidate) => ({
      ...candidate,
      role: "comparison",
    })),
  };
}

function cninfoSearchKey(request) {
  const year = extractYear(request.period);
  const quarter = quarterNumber(request.period);
  if (request.type === "annual") return year ? `${year}年年度报告` : "年度报告";
  if (request.type === "interim") {
    return year ? `${year}年半年度报告` : "半年度报告";
  }
  if (request.type === "quarterly") {
    if ([1, 3].includes(quarter)) return "";
    const quarterText = { 1: "第一季度", 2: "半年度", 3: "第三季度", 4: "年度" }[
      quarter
    ];
    return `${year ? `${year}年` : ""}${quarterText || "季度"}报告`;
  }
  return year ? `${year}年业绩` : "业绩";
}

function cninfoCategory(request) {
  if (request.type === "annual") return "category_ndbg_szsh";
  if (request.type === "interim") return "category_bndbg_szsh";
  if (request.type === "quarterly") {
    const quarter = quarterNumber(request.period);
    if (quarter === 1) return "category_yjdbg_szsh";
    if (quarter === 2) return "category_bndbg_szsh";
    if (quarter === 3) return "category_sjdbg_szsh";
    if (quarter === 4) return "category_ndbg_szsh";
  }
  return "";
}

async function locateCninfo(request) {
  const stockPayload = await (await fetchOrThrow(CNINFO_STOCKS_URL)).json();
  const ticker = String(request.ticker).replace(/\D/g, "").padStart(6, "0");
  const stock = stockPayload.stockList.find((item) => item.code === ticker);
  if (!stock) throw new Error(`CNInfo stock code not found: ${ticker}`);
  const year = extractYear(request.period) || new Date().getFullYear();
  async function queryAnnouncements(queryRequest, queryYear) {
    const body = new URLSearchParams({
      pageNum: "1",
      pageSize: "50",
      column: "szse",
      tabName: "fulltext",
      plate: "",
      stock: `${ticker},${stock.orgId}`,
      searchkey: cninfoSearchKey(queryRequest),
      category: cninfoCategory(queryRequest),
      seDate: `${queryYear - 1}-01-01~${queryYear + 1}-12-31`,
      sortName: "time",
      sortType: "desc",
      isHLtitle: "true",
    });
    return (
      await fetchOrThrow(CNINFO_QUERY_URL, {
        method: "POST",
        headers: {
          "User-Agent": "Mozilla/5.0 earnings-interpretation/9.5",
          Referer:
            "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
          "X-Requested-With": "XMLHttpRequest",
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        },
        body,
      })
    ).json();
  }

  function normalizeAnnouncements(payload) {
    return (payload.announcements || []).map((item) => ({
      title: decodeHtml(item.announcementTitle),
      url: new URL(item.adjunctUrl, "https://static.cninfo.com.cn/").href,
      publication_date:
        item.adjunctUrl.match(/(\d{4}-\d{2}-\d{2})/)?.[1] ||
        new Intl.DateTimeFormat("en-CA", {
          timeZone: "Asia/Shanghai",
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
        }).format(new Date(item.announcementTime)),
      document_type: classifyTitle(item.announcementTitle),
      source: "CNInfo",
    }));
  }

  const payload = await queryAnnouncements(request, year);
  const all = normalizeAnnouncements(payload);
  const current = rankCandidates(all, request);
  let comparison = [];
  if (request.type === "quarterly") {
    const comparisonRequest = {
      ...request,
      type: "annual",
      period: String(year - 1),
    };
    const comparisonPayload = await queryAnnouncements(
      comparisonRequest,
      year - 1,
    );
    comparison = rankCandidates(
      normalizeAnnouncements(comparisonPayload),
      comparisonRequest,
      5,
    );
  }
  return {
    resolved_company: {
      name: stock.zwjc,
      ticker,
      organization_id: stock.orgId,
    },
    official_index_url:
      "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
    candidates: current.map((candidate) => ({
      ...candidate,
      role: "current",
    })),
    comparison_candidates: comparison.map((candidate) => ({
      ...candidate,
      role: "comparison",
    })),
  };
}

export async function locateFiling(input) {
  const request = {
    market: normalizeMarket(input.market),
    ticker: input.ticker,
    period: input.period,
    type: normalizeType(input.type),
    userAgent: input.userAgent,
  };
  if (!request.ticker) throw new Error("--ticker is required");
  if (!request.period) throw new Error("--period is required");

  const located =
    request.market === "HK"
      ? await locateHkex(request)
      : request.market === "US"
        ? await locateSec(request)
        : await locateCninfo(request);
  const hasCandidate = located.candidates.length > 0;
  return {
    locator_version: "1.0.0",
    request: {
      market: request.market,
      ticker: request.ticker,
      period: request.period,
      type: request.type,
    },
    ...located,
    retrieval_log_entry: {
      channel: "official_locator",
      purpose: "locate_official_document",
      target: located.official_index_url,
      result: hasCandidate ? "success" : "failed",
      progress: hasCandidate,
      candidate_url: located.candidates[0]?.url || "",
      state_before: "LOCATING",
      state_after: hasCandidate ? "VERIFIED" : "LOCATING",
    },
    next_action: hasCandidate
      ? "Verify company, period and report type, then read the selected official document. Stop discovery after all required documents are read."
      : "Use one targeted official-domain Web Search fallback. Do not substitute news commentary for the filing.",
  };
}

const isDirectRun =
  process.argv[1] &&
  import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;

if (isDirectRun) {
  try {
    const args = parseArgs(process.argv.slice(2));
    const result = await locateFiling({
      market: args.market,
      ticker: args.ticker,
      period: args.period,
      type: args.type,
      userAgent: args["user-agent"],
    });
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    if (!result.candidates.length) process.exitCode = 2;
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  }
}
