import { spawn } from "child_process";
import { existsSync } from "fs";
import path from "path";
import {
  shouldDetachProcessGroup,
  terminateProcessTree,
  trackProcessTree,
} from "./child-process-lifecycle";
import { pythonInterpreter, SCRIPTS_DIR } from "./spawn-python";

// AUDIT B as a route-side gate — the ONE helper all three UI lanes (assemble,
// render, auto-edit) run after a successful assemble. render.py's own
// audit_stage only fires on monolithic renders; every editor lane goes through
// assemble.py (which has no audit), so QC lives here. Mirrors audit_stage's
// invocation: audit/audit_render.py <outDir>, PYTHONPATH=scripts/producer,
// verdict = the last parsable NDJSON line on stdout.

const PRODUCER_DIR = path.join(SCRIPTS_DIR, "producer");
const AUDIT_RENDER = path.join(PRODUCER_DIR, "audit", "audit_render.py");
export const AUDIT_TIMEOUT_MS = 10 * 60 * 1_000;

function timeoutLabel(timeoutMs: number): string {
  return timeoutMs % 60_000 === 0 ? `${timeoutMs / 60_000} min` : `${timeoutMs} ms`;
}

interface AuditSummary {
  status?: string;
  overall?: string;
  passed?: number;
  warnings?: number;
  failed?: number;
  report?: string;
  machine?: string;
  error?: string;
}

export function validAuditSummary(summary: AuditSummary | null): string | null {
  if (!summary) return "audit produced no parsable verdict";
  if (summary.status !== "done") return "audit final verdict is not a done event";
  if (!["pass", "warn", "fail"].includes(String(summary.overall))) {
    return `audit reported unknown overall status ${String(summary.overall)}`;
  }
  if (!Number.isInteger(summary.failed) || Number(summary.failed) < 0) {
    return "audit verdict has no valid failed-check count";
  }
  if (typeof summary.report !== "string" || typeof summary.machine !== "string"
      || !existsSync(summary.report) || !existsSync(summary.machine)) {
    return "audit report evidence is missing from disk";
  }
  return null;
}

interface AuditExit {
  code: number;
  summary: AuditSummary | null;
  errTail: string;
  timedOut: boolean;
}

export interface AuditGateOutcome {
  /** The 'audit' SSE event payload each lane forwards verbatim. */
  event: Record<string, unknown>;
  /** Operator-readable QC failure, or null when the deliverable passed. */
  failure: string | null;
}

/** Spawn audit_render.py and parse its final NDJSON verdict line. */
function spawnAudit(outDir: string, timeoutMs: number): Promise<AuditExit> {
  const env: NodeJS.ProcessEnv = { ...process.env };
  env.PYTHONPATH = env.PYTHONPATH ? `${PRODUCER_DIR}:${env.PYTHONPATH}` : PRODUCER_DIR;
  return new Promise((resolve) => {
    const proc = trackProcessTree(spawn(pythonInterpreter(), [AUDIT_RENDER, outDir], {
      env,
      detached: shouldDetachProcessGroup(),
    }));
    let stdout = "";
    let errTail = "";
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      terminateProcessTree(proc);
    }, timeoutMs);
    proc.stdout.on("data", (d: Buffer) => (stdout += d.toString()));
    proc.stderr.on("data", (d: Buffer) => {
      errTail = (errTail + d.toString()).slice(-800);
      process.stderr.write(d);
    });
    proc.on("close", (code) => {
      clearTimeout(timer);
      let summary: AuditSummary | null = null;
      for (const line of stdout.trim().split("\n").reverse()) {
        try {
          summary = JSON.parse(line) as AuditSummary;
          break;
        } catch {
          continue;
        }
      }
      resolve({ code: code ?? 1, summary, errTail, timedOut });
    });
    proc.on("error", (err) => {
      clearTimeout(timer);
      resolve({ code: 1, summary: null, errTail: err.message, timedOut });
    });
  });
}

/**
 * Audit B over a finished render dir. Never throws — by the time it runs the
 * deliverable already exists (outputs event fired), so the caller forwards
 * `event`, then surfaces `failure` through its lane's own error convention.
 * A hung audit is SIGTERMed (process group) after `timeoutMs` and reported
 * as a failed audit, never left running unbounded.
 */
export async function runAuditGate(
  outDir: string,
  timeoutMs = AUDIT_TIMEOUT_MS,
): Promise<AuditGateOutcome> {
  const { code, summary, errTail, timedOut } = await spawnAudit(outDir, timeoutMs);
  if (timedOut) {
    const message = `audit timed out after ${timeoutLabel(timeoutMs)}`;
    return {
      event: { event: "audit", overall: "error", message },
      failure: `Audit B contract failed: ${message}. ${errTail.slice(-300)}`,
    };
  }
  const invalid = validAuditSummary(summary);
  if (invalid) {
    return {
      event: { event: "audit", overall: "error", message: `${invalid} (exit ${code})` },
      failure: `Audit B contract failed: ${invalid} (exit ${code}). ${errTail.slice(-300)}`,
    };
  }
  const verdict = summary!;
  const event: Record<string, unknown> = {
    event: "audit",
    overall: verdict.overall,
    passed: verdict.passed,
    warnings: verdict.warnings,
    failed: verdict.failed,
    report: verdict.report,
    machine: verdict.machine,
    ...(verdict.error !== undefined ? { error: verdict.error } : {}),
  };
  if (code !== 0 || verdict.overall === "fail" || verdict.failed !== 0) {
    const detail =
      verdict.error ?? `${verdict.failed} check(s) FAILED — see ${verdict.report}`;
    return { event, failure: `final.mp4 rendered but failed Audit B QC: ${detail}` };
  }
  return { event, failure: null };
}
