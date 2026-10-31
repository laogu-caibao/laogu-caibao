#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const marketSnapshotGapId = "MARKET_SNAPSHOT";
const listedMarkets = new Set(["A", "HK", "US"]);
const stateRank = new Map(
  [
    "TARGET_DEFINED",
    "LOCATING",
    "VERIFIED",
    "READ_COMPLETE",
    "ANALYSIS_READY",
    "ENRICHMENT_DECISION",
    "DONE",
  ].map((state, index) => [state, index]),
);

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

function requireText(value, label) {
  const text = String(value || "").trim();
  if (!text) throw new Error(`${label} is required`);
  return text;
}

function marketField(field, value, unit, asOf, provider) {
  return {
    field,
    data_gap_id: marketSnapshotGapId,
    status: "pending",
    value,
    unit,
    as_of: asOf,
    provider,
    official_source_ids: [],
    used_in: ["market_snapshot"],
  };
}

export function applyMarketSnapshot(researchInput, options = {}) {
  const research = structuredClone(researchInput);
  const market = String(research.market || "").toUpperCase();
  if (!listedMarkets.has(market)) {
    throw new Error("MARKET_SNAPSHOT only applies to A, HK, or US listed companies");
  }

  const currentState = research.workflow?.current_state;
  const currentRank = stateRank.get(currentState);
  if (
    currentRank === undefined ||
    currentRank < stateRank.get("ANALYSIS_READY") ||
    currentRank > stateRank.get("ENRICHMENT_DECISION")
  ) {
    throw new Error(
      "research.workflow.current_state must be ANALYSIS_READY or ENRICHMENT_DECISION",
    );
  }

  const decision = research.enrichment_decision;
  const gaps = Array.isArray(decision?.data_gaps) ? decision.data_gaps : [];
  const gap = gaps.find((item) => item.id === marketSnapshotGapId);
  if (!gap) throw new Error("research is missing MARKET_SNAPSHOT data gap");
  if (gap.source_type !== "financial") {
    throw new Error("MARKET_SNAPSHOT.source_type must be financial");
  }

  const status = String(options.status || "available").toLowerCase();
  if (!new Set(["available", "unavailable"]).has(status)) {
    throw new Error("status must be available or unavailable");
  }

  const provider = String(options.provider || "金融 MCP").trim();
  const tool = String(options.tool || "market quote tool").trim();
  const query = String(options.query || "当前价与当前总市值").trim();
  const target = `${provider} ${tool}: ${query}`;
  const retrievalLog = Array.isArray(research.retrieval_log)
    ? research.retrieval_log
    : [];
  const sequence = retrievalLog.length + 1;
  const commonLog = {
    sequence,
    channel: "financial_mcp",
    purpose: "enrich_data_gap",
    target,
    state_before: currentState,
    state_after: "ENRICHMENT_DECISION",
    data_gap_id: marketSnapshotGapId,
  };

  research.retrieval_log = retrievalLog;
  research.tool_usage = research.tool_usage || {};
  research.tool_usage.financial_mcp_count =
    Number(research.tool_usage.financial_mcp_count || 0) + 1;
  research.mcp_fields = (research.mcp_fields || []).filter(
    (field) => field.data_gap_id !== marketSnapshotGapId,
  );
  research.enrichment_decision.status = "completed";
  research.workflow.current_state = "ENRICHMENT_DECISION";

  if (status === "available") {
    const price = requireText(options.price, "price");
    const marketCap = requireText(options.marketCap, "market-cap");
    const asOf = requireText(options.asOf, "as-of");
    const priceUnit = String(options.priceUnit || "").trim();
    const marketCapUnit = String(options.marketCapUnit || "").trim();
    gap.status = "resolved";
    research.enrichment_decision.reason =
      "固定市场快照已通过一次金融 MCP 合并查询完成";
    research.retrieval_log.push({
      ...commonLog,
      result: "success",
      progress: true,
      note: `current_price=${price}${priceUnit}; market_cap=${marketCap}${marketCapUnit}; as_of=${asOf}`,
    });
    research.mcp_fields.push(
      marketField("current_price", price, priceUnit, asOf, provider),
      marketField("market_cap", marketCap, marketCapUnit, asOf, provider),
    );
  } else {
    const note = String(options.note || "金融 MCP 未返回有效市场快照").trim();
    gap.status = "unavailable";
    research.enrichment_decision.reason = note;
    research.retrieval_log.push({
      ...commonLog,
      result: "failed",
      progress: false,
      note,
    });
  }

  research.workflow.stop_reason =
    status === "available"
      ? "正式材料与固定市场快照均已完成，信息足以生成报告"
      : "正式材料已完成；市场快照不可用并已保留真实失败记录";
  return research;
}

function writeJsonAtomic(filePath, value) {
  const resolved = path.resolve(filePath);
  const temporary = `${resolved}.tmp-${process.pid}`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  fs.renameSync(temporary, resolved);
}

const isDirectRun =
  process.argv[1] &&
  import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;

if (isDirectRun) {
  try {
    const args = parseArgs(process.argv.slice(2));
    const researchPath = requireText(args.research, "research");
    const research = JSON.parse(fs.readFileSync(path.resolve(researchPath), "utf8"));
    const updated = applyMarketSnapshot(research, {
      status: args.status,
      price: args.price,
      priceUnit: args["price-unit"],
      marketCap: args["market-cap"],
      marketCapUnit: args["market-cap-unit"],
      asOf: args["as-of"],
      provider: args.provider,
      tool: args.tool,
      query: args.query,
      note: args.note,
    });
    writeJsonAtomic(researchPath, updated);
    process.stdout.write(
      `${JSON.stringify(
        {
          ok: true,
          research: path.resolve(researchPath),
          status: args.status || "available",
          financial_mcp_count: updated.tool_usage.financial_mcp_count,
          next_action:
            "Write report.json now if it was not written in the same tool turn, then run build-report once.",
        },
        null,
        2,
      )}\n`,
    );
  } catch (error) {
    process.stderr.write(
      `${JSON.stringify({ ok: false, errors: [error.message] }, null, 2)}\n`,
    );
    process.exit(1);
  }
}
