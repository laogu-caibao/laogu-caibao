import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { renderReportFile } from "./render-report.mjs";
import { validateResearchGate } from "./validate-gates.mjs";
import {
  validateReportData,
  validateReportHtml,
} from "./validate-report.mjs";

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

function jsonLocation(text, error) {
  const match = String(error.message || "").match(/position\s+(\d+)/i);
  if (!match) return "";
  const position = Number(match[1]);
  const prefix = text.slice(0, position);
  const line = prefix.split("\n").length;
  const column = position - prefix.lastIndexOf("\n");
  return ` at line ${line}, column ${column}`;
}

function readJson(filePath, label) {
  const text = fs.readFileSync(filePath, "utf8");
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(
      `${label} is not valid JSON${jsonLocation(text, error)}. ` +
        "Fix the reported line in one edit; use Chinese brackets 「」 inside Chinese prose instead of raw double quotes. Do not read validator source.",
    );
  }
}

function normalizeResearch(research) {
  const normalized = structuredClone(research);
  const normalizations = [];
  const finalizableStates = new Set([
    "ANALYSIS_READY",
    "ENRICHMENT_DECISION",
    "DONE",
  ]);
  if (finalizableStates.has(normalized.workflow?.current_state)) {
    if (normalized.workflow.current_state !== "DONE") {
      normalized.workflow.current_state = "DONE";
      normalizations.push("workflow.current_state=DONE");
    }
  }
  const successfulDocuments = (normalized.official_documents || []).filter(
    (document) => document.read_status === "success",
  ).length;
  if (
    Number.isInteger(normalized.tool_usage?.official_documents_read) &&
    normalized.tool_usage.official_documents_read < successfulDocuments
  ) {
    normalized.tool_usage.official_documents_read = successfulDocuments;
    normalizations.push(
      `tool_usage.official_documents_read=${successfulDocuments}`,
    );
  }
  return { normalized, normalizations };
}

function unique(items) {
  return [...new Set(items)];
}

export function buildReport({
  research: researchInput,
  report: reportInput,
  output,
  allowFixture = false,
} = {}) {
  if (!researchInput || !reportInput || !output) {
    throw new Error(
      "Usage: node scripts/build-report.mjs --research research-gate.json --report report.json --output earnings-report.html",
    );
  }
  const researchPath = path.resolve(researchInput);
  const reportPath = path.resolve(reportInput);
  const outputPath = path.resolve(output);
  const rawResearch = readJson(researchPath, "research file");
  const report = readJson(reportPath, "report file");
  const { normalized: research, normalizations } =
    normalizeResearch(rawResearch);
  const data = { ...report, research };
  const errors = [];
  const warnings = [];

  const gate = validateResearchGate(research, {
    stage: "pre-report",
    allowFixture,
  });
  errors.push(...gate.errors.map((error) => `research: ${error}`));
  warnings.push(...gate.warnings.map((warning) => `research: ${warning}`));
  validateReportData(data, errors, warnings, { allowFixture });

  if (errors.length) {
    return {
      ok: false,
      stage: "preflight",
      errors: unique(errors).slice(0, 12),
      warning_count: unique(warnings).length,
      instruction:
        "Patch only the listed fields in one combined edit, then rerun build-report once. Do not read or grep validator, renderer, or schema source.",
    };
  }

  const rendered = renderReportFile({
    input: reportPath,
    output: outputPath,
    data,
  });
  validateReportHtml(rendered.html, errors);
  if (errors.length) {
    return {
      ok: false,
      stage: "rendered-html",
      errors: unique(errors).slice(0, 12),
      warning_count: unique(warnings).length,
      instruction:
        "Patch only the listed report fields in one combined edit, then rerun build-report once. Do not read renderer or validator source.",
    };
  }

  fs.writeFileSync(
    researchPath,
    `${JSON.stringify(research, null, 2)}\n`,
    "utf8",
  );
  return {
    ok: true,
    output: rendered.output,
    bytes: rendered.bytes,
    warning_count: unique(warnings).length,
    normalizations,
  };
}

const isDirectRun =
  process.argv[1] &&
  import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;

if (isDirectRun) {
  try {
    const args = parseArgs(process.argv.slice(2));
    const result = buildReport({
      research: args.research,
      report: args.report,
      output: args.output,
      allowFixture: args["allow-fixture"] === true,
    });
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    if (!result.ok) process.exit(1);
  } catch (error) {
    process.stderr.write(
      `${JSON.stringify(
        {
          ok: false,
          stage: "input",
          errors: [error.message],
          instruction:
            "Fix the reported input once and rerun build-report. Do not read validator, renderer, or schema source.",
        },
        null,
        2,
      )}\n`,
    );
    process.exit(1);
  }
}
