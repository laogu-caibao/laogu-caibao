import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const disclosedModes = new Set(["brief", "standard", "deep", "update"]);
const listedMarkets = new Set(["A", "HK", "US"]);
const marketSnapshotGapId = "MARKET_SNAPSHOT";
const officialLevels = new Set(["监管披露", "公司披露"]);
const forbiddenPendingUses = new Set([
  "title",
  "headline",
  "executive_summary",
  "high_risk",
]);
const workflowStates = [
  "TARGET_DEFINED",
  "LOCATING",
  "VERIFIED",
  "READ_COMPLETE",
  "ANALYSIS_READY",
  "ENRICHMENT_DECISION",
  "DONE",
];
const workflowStateRank = new Map(
  workflowStates.map((state, index) => [state, index]),
);

function hostname(value) {
  if (!value) return "";
  try {
    const normalized = /^[a-z][a-z0-9+.-]*:\/\//i.test(value)
      ? value
      : `https://${value}`;
    return new URL(normalized).hostname.toLowerCase().replace(/\.$/, "");
  } catch {
    return "";
  }
}

function matchesDomain(host, domain) {
  return host === domain || host.endsWith(`.${domain}`);
}

function marketDomains(research) {
  const market = String(research.market || "").toUpperCase();
  const domains = [];
  if (market === "HK") {
    domains.push("hkexnews.hk", "hkex.com.hk", "todayir.com");
  } else if (market === "A") {
    domains.push("cninfo.com.cn", "sse.com.cn", "szse.cn", "bse.cn");
  } else if (market === "US") {
    domains.push("sec.gov");
  }
  const irDomain = hostname(research.company_ir_domain);
  if (irDomain) domains.push(irDomain);
  return [...new Set(domains)];
}

export function validateOfficialUrl(value, research, { allowFixture = false } = {}) {
  try {
    const url = new URL(value);
    if (!["http:", "https:"].includes(url.protocol)) {
      return { ok: false, reason: "URL must use http or https" };
    }
    const host = url.hostname.toLowerCase();
    if (allowFixture && host.endsWith(".test")) return { ok: true, host };
    if (
      host === "localhost" ||
      host.endsWith(".localhost") ||
      host.endsWith(".test") ||
      host.endsWith(".invalid")
    ) {
      return { ok: false, reason: "test or local URL is not allowed" };
    }
    if (
      ["example.com", "example.org", "example.net"].some(
        (domain) => host === domain || host.endsWith(`.${domain}`),
      )
    ) {
      return { ok: false, reason: "placeholder URL is not allowed" };
    }
    const allowed = marketDomains(research);
    if (!allowed.length) {
      return { ok: false, reason: "no official domain is configured for this market" };
    }
    if (!allowed.some((domain) => matchesDomain(host, domain))) {
      return {
        ok: false,
        reason: `domain ${host} is not in official whitelist: ${allowed.join(", ")}`,
      };
    }
    if (!url.pathname || url.pathname === "/") {
      return { ok: false, reason: "URL must point to a concrete official document or disclosure" };
    }
    return { ok: true, host };
  } catch {
    return { ok: false, reason: "invalid URL" };
  }
}

function isQuarterly(reportType) {
  return /quarter|季度|季报|一季|三季/i.test(String(reportType || ""));
}

function checkRetrievalLog(research, errors, warnings) {
  const log = research.retrieval_log;
  if (!Array.isArray(log)) {
    errors.push("research.retrieval_log must be an array");
    return;
  }

  const documents = new Map(
    (research.official_documents || []).map((document) => [document.id, document]),
  );
  const sequences = new Set();
  const fetchedTargets = new Set();
  const channelCounts = {
    web_search: 0,
    web_fetch: 0,
    official_locator: 0,
    shell_network: 0,
    browser_use: 0,
    financial_mcp: 0,
    news_mcp: 0,
  };
  const seenActions = new Set();
  const gapIds = new Set(
    (research.enrichment_decision?.data_gaps || []).map((gap) => gap.id),
  );
  let previousStateAfter = null;
  let consecutiveNoProgress = 0;

  for (const [index, entry] of log.entries()) {
    const prefix = `retrieval_log[${index}]`;
    if (!Number.isInteger(entry.sequence) || entry.sequence < 1) {
      errors.push(`${prefix}.sequence must be a positive integer`);
    } else {
      if (sequences.has(entry.sequence)) {
        errors.push(`duplicate retrieval sequence: ${entry.sequence}`);
      }
      sequences.add(entry.sequence);
    }
    if (!Object.hasOwn(channelCounts, entry.channel)) {
      errors.push(`${prefix}.channel is invalid`);
      continue;
    }
    channelCounts[entry.channel] += 1;
    if (
      ![
        "locate_official_document",
        "read_official_document",
        "enrich_data_gap",
      ].includes(entry.purpose)
    ) {
      errors.push(`${prefix}.purpose is invalid`);
    }
    if (!entry.target) errors.push(`${prefix}.target is required`);
    if (!["success", "failed"].includes(entry.result)) {
      errors.push(`${prefix}.result must be success or failed`);
    }
    if (typeof entry.progress !== "boolean") {
      errors.push(`${prefix}.progress must be boolean`);
    }

    const beforeRank = workflowStateRank.get(entry.state_before);
    const afterRank = workflowStateRank.get(entry.state_after);
    if (beforeRank === undefined) {
      errors.push(`${prefix}.state_before is invalid`);
    }
    if (afterRank === undefined) {
      errors.push(`${prefix}.state_after is invalid`);
    }
    if (
      beforeRank !== undefined &&
      afterRank !== undefined &&
      afterRank < beforeRank
    ) {
      errors.push(`${prefix}: workflow state must not move backwards`);
    }
    if (
      previousStateAfter &&
      beforeRank !== undefined &&
      workflowStateRank.get(previousStateAfter) > beforeRank
    ) {
      warnings.push(
        `${prefix}.state_before precedes previous state_after (${previousStateAfter}); allowed for parallel retrievals, keep later actions monotonic`,
      );
    }
    previousStateAfter = entry.state_after;

    const actionKey = `${entry.channel}\u0000${entry.purpose}\u0000${entry.target}`;
    if (seenActions.has(actionKey)) {
      errors.push(`${prefix}: duplicate retrieval action is not allowed`);
    }
    seenActions.add(actionKey);

    if (entry.progress) {
      consecutiveNoProgress = 0;
    } else {
      consecutiveNoProgress += 1;
      if (consecutiveNoProgress >= 2) {
        warnings.push(
          `${prefix}: ${consecutiveNoProgress} consecutive retrieval actions made no progress; change route or stop`,
        );
      }
    }

    if (
      entry.purpose === "locate_official_document" &&
      beforeRank !== undefined &&
      beforeRank >= workflowStateRank.get("READ_COMPLETE")
    ) {
      errors.push(
        `${prefix}: official document discovery must stop once required materials are read`,
      );
    }
    if (
      entry.purpose === "locate_official_document" &&
      entry.result === "success" &&
      (!entry.progress || !entry.candidate_url)
    ) {
      errors.push(
        `${prefix}: successful discovery requires progress=true and candidate_url`,
      );
    }
    if (entry.purpose === "read_official_document") {
      if (!entry.official_document_id) {
        errors.push(`${prefix}.official_document_id is required when reading a document`);
      } else {
        const document = documents.get(entry.official_document_id);
        if (!document) {
          errors.push(`${prefix} references unknown official document: ${entry.official_document_id}`);
        } else if (entry.target !== document.url) {
          errors.push(
            `${prefix}.target must exactly match official_documents URL for ${entry.official_document_id}`,
          );
        }
      }
      if (fetchedTargets.has(entry.target)) {
        errors.push(`${prefix}: duplicate official-document read is not allowed`);
      }
      fetchedTargets.add(entry.target);
    }
    if (entry.purpose === "enrich_data_gap") {
      if (
        beforeRank !== undefined &&
        beforeRank < workflowStateRank.get("ANALYSIS_READY")
      ) {
        errors.push(`${prefix}: enrichment is not allowed before ANALYSIS_READY`);
      }
      if (!entry.data_gap_id) {
        errors.push(`${prefix}.data_gap_id is required for enrichment`);
      } else if (!gapIds.has(entry.data_gap_id)) {
        errors.push(`${prefix} references unknown data gap: ${entry.data_gap_id}`);
      }
    }
  }

  if (sequences.size) {
    const ordered = [...sequences].sort((left, right) => left - right);
    for (let index = 0; index < ordered.length; index += 1) {
      if (ordered[index] !== index + 1) {
        errors.push("retrieval_log.sequence must be contiguous and start at 1");
        break;
      }
    }
  }

  const usage = research.tool_usage || {};
  const usageKeys = {
    web_search: "web_search_count",
    web_fetch: "web_fetch_count",
    official_locator: "official_locator_count",
    shell_network: "shell_network_count",
    browser_use: "browser_use_count",
    financial_mcp: "financial_mcp_count",
    news_mcp: "news_mcp_count",
  };
  for (const [channel, key] of Object.entries(usageKeys)) {
    if (Number.isInteger(usage[key]) && usage[key] !== channelCounts[channel]) {
      warnings.push(
        `tool_usage.${key}=${usage[key]} does not match retrieval_log count ${channelCounts[channel]}`,
      );
    }
  }

  const currentState = research.workflow?.current_state;
  const currentRank = workflowStateRank.get(currentState);
  if (previousStateAfter && currentRank !== undefined) {
    const lastRank = workflowStateRank.get(previousStateAfter);
    if (lastRank !== undefined && currentRank < lastRank) {
      errors.push("workflow.current_state must not precede the last retrieval state");
    }
  }
}

function checkUsage(research, stage, errors, warnings) {
  const usage = research.tool_usage || {};
  const requiredCounts = [
    "web_search_count",
    "web_fetch_count",
    "official_locator_count",
    "shell_network_count",
    "browser_use_count",
    "package_install_count",
    "ad_hoc_retrieval_script_count",
    "official_documents_read",
    "financial_mcp_count",
    "news_mcp_count",
  ];
  for (const key of requiredCounts) {
    if (!Number.isInteger(usage[key]) || usage[key] < 0) {
      errors.push(`tool_usage.${key} must be a non-negative integer`);
    }
  }
  if (usage.web_search_count > 2) {
    warnings.push(
      `Web Search count is ${usage.web_search_count}; confirm each call produced a new official candidate`,
    );
  }
  if (usage.web_fetch_count > 2) {
    warnings.push(
      `WebFetch count is ${usage.web_fetch_count}; confirm calls stopped after required reports were read`,
    );
  }
  const externalRetrievalCount =
    (usage.web_search_count || 0) +
    (usage.web_fetch_count || 0) +
    (usage.official_locator_count || 0) +
    (usage.shell_network_count || 0) +
    (usage.browser_use_count || 0);
  const externalRetrievalMaximum = isQuarterly(research.report_type) ? 4 : 3;
  if (externalRetrievalCount > externalRetrievalMaximum) {
    warnings.push(
      `external retrieval count is ${externalRetrievalCount}; reference target is ${externalRetrievalMaximum}`,
    );
  }
  if (usage.shell_network_count > 0) {
    warnings.push(
      `shell network retrieval count is ${usage.shell_network_count}; prefer the bundled official locator`,
    );
  }
  if (usage.browser_use_count > 0) {
    warnings.push(
      `Browser Use count is ${usage.browser_use_count}; keep it only when official pages require interaction`,
    );
  }
  if (usage.package_install_count > 0) {
    warnings.push("runtime package installation was used; verify it was necessary");
  }
  if (usage.ad_hoc_retrieval_script_count > 0) {
    warnings.push(
      "ad hoc retrieval scripts were used; prefer the bundled official locator",
    );
  }
  if (stage === "pre-analysis" && usage.financial_mcp_count !== 0) {
    errors.push("financial MCP must be 0 before the pre-analysis gate passes");
  }
  if (stage === "pre-analysis" && usage.news_mcp_count !== 0) {
    errors.push("news MCP must be 0 before the pre-analysis gate passes");
  }
  if (stage === "pre-report" && usage.financial_mcp_count > 1) {
    warnings.push(
      `financial MCP count is ${usage.financial_mcp_count}; confirm every call maps to a data gap`,
    );
  }
  if (stage === "pre-report" && usage.news_mcp_count > 0) {
    warnings.push(
      `news MCP count is ${usage.news_mcp_count}; confirm every call maps to a user-relevant data gap`,
    );
  }

  const successfulDocuments = (research.official_documents || []).filter(
    (document) => document.read_status === "success",
  ).length;
  if (
    Number.isInteger(usage.official_documents_read) &&
    usage.official_documents_read < successfulDocuments
  ) {
    errors.push("tool_usage.official_documents_read is lower than successful document records");
  }

  if (research.mode === "brief") {
    const forbiddenFlags = [
      "todo_write_used",
      "company_profile_used",
      "market_valuation_used",
      "generic_news_search_used",
      "renderer_source_read",
    ];
    for (const flag of forbiddenFlags) {
      if (usage[flag] !== false) {
        errors.push(`brief mode requires tool_usage.${flag} = false`);
      }
    }
  }
  if (Number.isFinite(usage.elapsed_seconds) && usage.elapsed_seconds > 180) {
    warnings.push(`elapsed time ${usage.elapsed_seconds}s exceeds the 2–3 minute target`);
  }
}

function checkWorkflow(research, stage, errors) {
  const workflow = research.workflow;
  if (!workflow || typeof workflow !== "object" || Array.isArray(workflow)) {
    errors.push("research.workflow is required");
    return;
  }
  const stateRank = workflowStateRank.get(workflow.current_state);
  if (stateRank === undefined) {
    errors.push(`invalid workflow.current_state: ${workflow.current_state}`);
    return;
  }
  for (const key of ["company_name", "security_code", "report_period"]) {
    if (!workflow.target?.[key]) {
      errors.push(`workflow.target.${key} is required`);
    }
  }
  if (
    stage === "pre-analysis" &&
    stateRank < workflowStateRank.get("ANALYSIS_READY")
  ) {
    errors.push("pre-analysis requires workflow.current_state >= ANALYSIS_READY");
  }
  if (stage === "pre-report" && workflow.current_state !== "DONE") {
    errors.push("pre-report requires workflow.current_state = DONE");
  }
}

function checkEnrichmentDecision(research, stage, errors) {
  const decision = research.enrichment_decision;
  if (!decision || typeof decision !== "object" || Array.isArray(decision)) {
    errors.push("research.enrichment_decision is required");
    return;
  }
  if (!["not_needed", "needed", "completed"].includes(decision.status)) {
    errors.push(`invalid enrichment_decision.status: ${decision.status}`);
  }
  if (!decision.reason) {
    errors.push("enrichment_decision.reason is required");
  }
  const gaps = Array.isArray(decision.data_gaps) ? decision.data_gaps : [];
  const ids = new Set();
  for (const [index, gap] of gaps.entries()) {
    const prefix = `enrichment_decision.data_gaps[${index}]`;
    if (!gap.id) errors.push(`${prefix}.id is required`);
    if (gap.id && ids.has(gap.id)) errors.push(`duplicate data gap id: ${gap.id}`);
    if (gap.id) ids.add(gap.id);
    if (!gap.description) errors.push(`${prefix}.description is required`);
    if (!["financial", "news", "official", "other"].includes(gap.source_type)) {
      errors.push(`${prefix}.source_type is invalid`);
    }
    if (!["open", "resolved", "unavailable"].includes(gap.status)) {
      errors.push(`${prefix}.status is invalid`);
    }
  }
  if (decision.status === "not_needed" && gaps.length > 0) {
    errors.push("not_needed enrichment decision must not contain data gaps");
  }
  if (decision.status === "needed" && gaps.length === 0) {
    errors.push("needed enrichment decision requires at least one data gap");
  }
  if (
    decision.status === "completed" &&
    gaps.some((gap) => gap.status === "open")
  ) {
    errors.push("completed enrichment decision cannot contain open data gaps");
  }

  const usage = research.tool_usage || {};
  const mcpCount =
    (usage.financial_mcp_count || 0) + (usage.news_mcp_count || 0);
  if (stage === "pre-report" && mcpCount > 0) {
    if (decision.status !== "completed") {
      errors.push("MCP use requires enrichment_decision.status = completed");
    }
    if (gaps.length === 0) {
      errors.push("MCP use requires at least one explicit data gap");
    }
    const successfulFinancialMcp = (research.retrieval_log || []).filter(
      (entry) =>
        entry.channel === "financial_mcp" &&
        entry.purpose === "enrich_data_gap" &&
        entry.result === "success" &&
        entry.progress === true,
    ).length;
    if (successfulFinancialMcp > 0 && (research.mcp_fields || []).length === 0) {
      errors.push("financial MCP use requires at least one recorded mcp_field");
    }
    const loggedMcpGaps = new Set(
      (research.retrieval_log || [])
        .filter(
          (entry) =>
            entry.purpose === "enrich_data_gap" &&
            ["financial_mcp", "news_mcp"].includes(entry.channel),
        )
        .map((entry) => entry.data_gap_id),
    );
    for (const channel of ["financial_mcp", "news_mcp"]) {
      const countKey =
        channel === "financial_mcp"
          ? "financial_mcp_count"
          : "news_mcp_count";
      if ((usage[countKey] || 0) > 0) {
        const sourceType = channel === "financial_mcp" ? "financial" : "news";
        const matching = gaps.some(
          (gap) => gap.source_type === sourceType && loggedMcpGaps.has(gap.id),
        );
        if (!matching) {
          errors.push(`${channel} use is not tied to a matching data gap`);
        }
      }
    }
  }
  if (stage === "pre-report" && mcpCount === 0 && decision.status === "needed") {
    errors.push(
      "needed enrichment must be completed, marked unavailable, or changed to not_needed before reporting",
    );
  }
}

function checkMarketSnapshotEnrichment(research, stage, errors) {
  if (!listedMarkets.has(String(research.market || "").toUpperCase())) return;

  const decision = research.enrichment_decision || {};
  const gaps = Array.isArray(decision.data_gaps) ? decision.data_gaps : [];
  const gap = gaps.find((item) => item.id === marketSnapshotGapId);
  if (!gap) {
    errors.push(
      `listed-company reports require the fixed ${marketSnapshotGapId} financial data gap`,
    );
    return;
  }
  if (gap.source_type !== "financial") {
    errors.push(`${marketSnapshotGapId}.source_type must be financial`);
  }

  if (stage === "pre-analysis") {
    if (decision.status !== "needed") {
      errors.push(
        `pre-analysis requires enrichment_decision.status = needed for ${marketSnapshotGapId}`,
      );
    }
    if (gap.status !== "open") {
      errors.push(`pre-analysis requires ${marketSnapshotGapId}.status = open`);
    }
    return;
  }

  if (decision.status !== "completed") {
    errors.push(
      `pre-report requires enrichment_decision.status = completed for ${marketSnapshotGapId}`,
    );
  }
  if (!["resolved", "unavailable"].includes(gap.status)) {
    errors.push(
      `pre-report requires ${marketSnapshotGapId}.status = resolved or unavailable`,
    );
  }

  const marketLogs = (research.retrieval_log || []).filter(
    (entry) =>
      entry.channel === "financial_mcp" &&
      entry.purpose === "enrich_data_gap" &&
      entry.data_gap_id === marketSnapshotGapId,
  );
  if ((research.tool_usage?.financial_mcp_count || 0) < 1) {
    errors.push(`${marketSnapshotGapId} requires tool_usage.financial_mcp_count >= 1`);
  }
  if (marketLogs.length === 0) {
    errors.push(
      `${marketSnapshotGapId} requires one recorded financial MCP attempt after pre-analysis`,
    );
    return;
  }

  if (gap.status === "resolved") {
    if (!marketLogs.some((entry) => entry.result === "success" && entry.progress === true)) {
      errors.push(`${marketSnapshotGapId} is resolved without a successful financial MCP log`);
    }
    const fields = new Map(
      (research.mcp_fields || [])
        .filter((field) => field.data_gap_id === marketSnapshotGapId)
        .map((field) => [field.field, field]),
    );
    for (const fieldName of ["current_price", "market_cap"]) {
      const field = fields.get(fieldName);
      if (!field) {
        errors.push(`${marketSnapshotGapId} missing mcp_field: ${fieldName}`);
      } else if (!Array.isArray(field.used_in) || !field.used_in.includes("market_snapshot")) {
        errors.push(`${marketSnapshotGapId} ${fieldName} must be used_in market_snapshot`);
      }
    }
  }

  if (gap.status === "unavailable") {
    if (!marketLogs.some((entry) => entry.result === "failed")) {
      errors.push(`${marketSnapshotGapId} is unavailable without a failed financial MCP log`);
    }
  }
}

function checkDocuments(research, errors, options) {
  if (!disclosedModes.has(research.mode)) return;
  if (!Array.isArray(research.official_documents) || research.official_documents.length === 0) {
    errors.push("at least one official report document is required");
    return;
  }
  const ids = new Set();
  for (const [index, document] of research.official_documents.entries()) {
    const prefix = `official_documents[${index}]`;
    for (const key of [
      "id",
      "title",
      "url",
      "document_type",
      "role",
      "report_period",
      "publication_date",
      "read_status",
    ]) {
      if (!document[key]) errors.push(`${prefix}.${key} is required`);
    }
    if (document.id) {
      if (ids.has(document.id)) errors.push(`duplicate official document id: ${document.id}`);
      ids.add(document.id);
    }
    if (document.url) {
      const result = validateOfficialUrl(document.url, research, options);
      if (!result.ok) errors.push(`${prefix}.url: ${result.reason}`);
    }
  }
  const successful = research.official_documents.filter(
    (document) => document.read_status === "success",
  );
  if (!successful.some((document) => document.role === "current")) {
    errors.push("a successfully read current official report is required before analysis");
  }
  if (
    isQuarterly(research.report_type) &&
    !successful.some(
      (document) =>
        document.role === "comparison" && document.document_type === "annual_report",
    )
  ) {
    errors.push("latest quarterly report requires a successfully read comparison annual report");
  }

  const policy = research.comparison_policy || {};
  if (policy.income_statement !== "official_native_comparative") {
    errors.push("income statement comparison must use official_native_comparative");
  }
  if (policy.balance_sheet !== "official_report_opening") {
    errors.push("balance sheet opening must use official_report_opening");
  }
}

function checkMcpFields(research, errors) {
  const officialIds = new Set(
    (research.official_documents || [])
      .filter((document) => document.read_status === "success")
      .map((document) => document.id),
  );
  for (const [index, field] of (research.mcp_fields || []).entries()) {
    const prefix = `mcp_fields[${index}]`;
    if (!field.field) errors.push(`${prefix}.field is required`);
    if (!field.data_gap_id) {
      errors.push(`${prefix}.data_gap_id is required`);
    } else if (
      !(research.enrichment_decision?.data_gaps || []).some(
        (gap) => gap.id === field.data_gap_id,
      )
    ) {
      errors.push(`${prefix} references unknown data gap: ${field.data_gap_id}`);
    }
    if (!["official_verified", "pending"].includes(field.status)) {
      errors.push(`${prefix}.status must be official_verified or pending`);
    }
    const uses = Array.isArray(field.used_in) ? field.used_in : [];
    if (field.status === "pending") {
      for (const use of uses) {
        if (forbiddenPendingUses.has(use)) {
          errors.push(`pending MCP field ${field.field || index} cannot be used in ${use}`);
        }
      }
    }
    if (field.status === "official_verified") {
      const sourceIds = Array.isArray(field.official_source_ids)
        ? field.official_source_ids
        : [];
      if (!sourceIds.length) {
        errors.push(`${prefix}.official_source_ids is required for official_verified fields`);
      }
      for (const id of sourceIds) {
        if (!officialIds.has(id)) {
          errors.push(`${prefix} references non-official or unread source: ${id}`);
        }
      }
    }
  }
}

function checkReconciliations(research, errors) {
  if (!disclosedModes.has(research.mode)) return;
  const successfulOfficialIds = new Set(
    (research.official_documents || [])
      .filter((document) => document.read_status === "success")
      .map((document) => document.id),
  );
  const records = new Map(
    (research.reconciliations || []).map((record) => [record.name, record]),
  );
  for (const name of [
    "income_statement_comparative",
    "balance_sheet_opening",
    "cash_closing_balance",
  ]) {
    const record = records.get(name);
    if (!record) {
      errors.push(`missing reconciliation: ${name}`);
      continue;
    }
    if (record.status !== "pass") errors.push(`reconciliation ${name} must pass`);
    if (!Array.isArray(record.source_ids) || record.source_ids.length === 0) {
      errors.push(`reconciliation ${name} requires source_ids`);
    } else {
      for (const id of record.source_ids) {
        if (!successfulOfficialIds.has(id)) {
          errors.push(`reconciliation ${name} references unread official source: ${id}`);
        }
      }
    }
  }
  if (
    records.get("income_statement_comparative")?.basis !==
    "official_native_comparative"
  ) {
    errors.push("income_statement_comparative must use official_native_comparative");
  }
  if (
    records.get("balance_sheet_opening")?.basis !== "official_report_opening"
  ) {
    errors.push("balance_sheet_opening must use official_report_opening");
  }
  const cash = records.get("cash_closing_balance");
  if (cash) {
    for (const key of ["left_value", "right_value", "tolerance"]) {
      if (!Number.isFinite(cash[key])) errors.push(`cash_closing_balance.${key} must be numeric`);
    }
    if (
      Number.isFinite(cash.left_value) &&
      Number.isFinite(cash.right_value) &&
      Number.isFinite(cash.tolerance) &&
      Math.abs(cash.left_value - cash.right_value) > cash.tolerance
    ) {
      errors.push("cash_closing_balance difference exceeds tolerance");
    }
  }
}

export function validateResearchGate(
  research,
  { stage = "pre-report", allowFixture = false } = {},
) {
  const errors = [];
  const warnings = [];
  if (!research || typeof research !== "object" || Array.isArray(research)) {
    return { ok: false, stage, errors: ["research gate object is required"], warnings };
  }
  if (!["pre-analysis", "pre-report"].includes(stage)) {
    errors.push(`invalid stage: ${stage}`);
  }
  if (!["brief", "standard", "deep", "preview", "update"].includes(research.mode)) {
    errors.push(`invalid research mode: ${research.mode}`);
  }
  if (!["A", "HK", "US", "OTHER"].includes(String(research.market || "").toUpperCase())) {
    errors.push(`invalid market: ${research.market}`);
  }
  if (!research.report_type) errors.push("research.report_type is required");
  checkWorkflow(research, stage, errors);
  checkDocuments(research, errors, { allowFixture });
  checkRetrievalLog(research, errors, warnings);
  checkUsage(research, stage, errors, warnings);
  checkEnrichmentDecision(research, stage, errors);
  checkMarketSnapshotEnrichment(research, stage, errors);
  if (stage === "pre-report") {
    checkMcpFields(research, errors);
    checkReconciliations(research, errors);
  }
  return { ok: errors.length === 0, stage, errors, warnings };
}

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

const isDirectRun =
  process.argv[1] &&
  import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;

if (isDirectRun) {
  const args = parseArgs(process.argv.slice(2));
  if (!args.input) {
    process.stderr.write(
      "Usage: node scripts/validate-gates.mjs --input research.json --stage pre-analysis|pre-report\n",
    );
    process.exit(1);
  }
  const payload = JSON.parse(fs.readFileSync(path.resolve(args.input), "utf8"));
  const research = payload.research || payload;
  const result = validateResearchGate(research, {
    stage: args.stage || "pre-report",
    allowFixture: args["allow-fixture"] === true,
  });
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  if (!result.ok) process.exit(1);
}

export { officialLevels };
