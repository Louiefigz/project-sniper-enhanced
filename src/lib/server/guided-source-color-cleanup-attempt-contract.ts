/** Pure exact record/clock/tool metadata joins, never current executable or retirement authority. */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { exactKeys, objectValue, sha256 } from "@/lib/producer/contracts/validation";
import { openingAbsolutePath } from "@/lib/producer/contracts/guided-opening-media-v1";
import { parseCurrentOpeningCleanupStdout } from "@/lib/producer/contracts/guided-opening-cleanup-v2";
import { strictGuidedTimestamp } from "./guided-cut-v2-store";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import type { SourceColorCleanupAttemptReadInput } from "./guided-source-color-cleanup-attempt-hold";
import type { openingChildTools, readStoppedOpeningProcess } from "./guided-opening-process";
import { assertSourceColorCleanupResult } from "./guided-source-color-cleanup-hold";

export interface CleanupAttemptRecords { start: Record<string, unknown>; invocation: Record<string, unknown>; output: Record<string, unknown> }
type Stopped = ReturnType<typeof readStoppedOpeningProcess>;
const START = ["schemaVersion", "kind", "cleanupAttemptId", "claimHash", "processOutcomeSha256", "beforeJournalHash", "clockHash",
  "generationStartedAt", "receivedAt", "startedAt", "budgetScope", "sourceColor", "archive"];
const INVOCATION = ["schemaVersion", "kind", "scope", "attemptId", "claimHash", "processOutcomeSha256", "sourceColor", "tools", "observedAt"];
const OUTPUT = ["schemaVersion", "kind", "stdout", "stderr", "mediaProcessGroupStopped", "cleanupProcessGroupStopped", "cleanupNestedOwnership",
  "observedAt", "elapsedMs", "invocationSha256", "ledger"];
const TOOLS = ["script", "scriptHash", "runnerScript", "runnerScriptHash", "python", "pythonResolved", "pythonHash", "venvRoot", "venvConfig", "venvConfigHash"];

function same(actual: unknown, expected: unknown, label: string): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error(`Cleanup attempt ${label} differs from original authority`);
}
function exact(value: unknown, keys: string[], label: string) {
  const row = objectValue(value, label); exactKeys(row, keys, keys, label); return row;
}

/** Historical Python spelling is checked, not resolved or hashed against today's tools. */
export function cleanupInvocationTools(value: unknown, input: SourceColorCleanupAttemptReadInput): ReturnType<typeof openingChildTools> {
  const row = exact(value, TOOLS, "cleanup invocation tools"), pipeline = input.held.job.ctx.pipeline;
  if (!pipeline || !Array.isArray(pipeline.files)) throw new Error("Cleanup invocation lacks original pipeline metadata");
  for (const name of TOOLS) {
    if (name.endsWith("Hash")) sha256(row[name], name); else openingAbsolutePath(row[name]);
  }
  const script = path.join(openingAbsolutePath(pipeline.snapshotRoot), "scripts/producer/guided_opening_cleanup.py");
  const runner = path.join(pipeline.snapshotRoot, "scripts/producer/headless/process_runner.py");
  if (row.script !== script || row.runnerScript !== runner || row.venvConfig !== path.join(String(row.venvRoot), "pyvenv.cfg")
      || path.dirname(path.dirname(String(row.python))) !== row.venvRoot
      || !pipeline.files.some(file => file.path === "scripts/producer/guided_opening_cleanup.py" && file.hash === row.scriptHash)
      || !pipeline.files.some(file => file.path === "scripts/producer/headless/process_runner.py" && file.hash === row.runnerScriptHash)) {
    throw new Error("Cleanup invocation lost original script/runner or Python metadata");
  }
  return row as unknown as ReturnType<typeof openingChildTools>;
}

function startRecord(input: SourceColorCleanupAttemptReadInput, records: CleanupAttemptRecords, stopped: Stopped): void {
  const { held, fact } = input, start = exact(records.start, START, "cleanup start");
  const { receivedAt, startedAt } = start;
  same(start, { schemaVersion: 2, kind: "guided-opening-cleanup-start", cleanupAttemptId: fact.cleanupAttemptId,
    claimHash: held.claimHash, processOutcomeSha256: stopped.receiptSha256, beforeJournalHash: held.sha256,
    clockHash: held.claim.clockHash, generationStartedAt: held.claim.generationStartedAt, receivedAt, startedAt,
    budgetScope: "separate-protected-cleanup-not-render-allowance", sourceColor: stopped.sourceColor, archive: fact.archive }, "start bindings");
  same({ claimHash: fact.claimHash, executionId: fact.executionId, beforeJournalHash: fact.beforeJournalHash,
    processOutcomeSha256: fact.processOutcomeSha256, clockHash: fact.clockHash, generationStartedAt: fact.generationStartedAt,
    reservation: fact.reservation, sourceColorHash: fact.sourceColorHash },
  { claimHash: held.claimHash, executionId: held.claim.executionId, beforeJournalHash: held.sha256,
    processOutcomeSha256: stopped.receiptSha256, clockHash: held.claim.clockHash, generationStartedAt: held.claim.generationStartedAt,
    reservation: stopped.sourceColor!.reservation, sourceColorHash: stopped.sourceColor!.sourceColorHash }, "prepared fact bindings");
}
function invocationRecord(input: SourceColorCleanupAttemptReadInput, records: CleanupAttemptRecords, stopped: Stopped) {
  const row = exact(records.invocation, INVOCATION, "cleanup invocation"), { tools, observedAt } = row;
  same(row, { schemaVersion: 1, kind: "guided-source-color-cleanup-invocation", scope: "pinned-cleanup-invocation-not-completion-or-retirement",
    attemptId: input.fact.cleanupAttemptId, claimHash: input.held.claimHash, processOutcomeSha256: stopped.receiptSha256,
    sourceColor: stopped.sourceColor, tools, observedAt }, "invocation bindings");
  return cleanupInvocationTools(tools, input);
}
function outputRecord(input: SourceColorCleanupAttemptReadInput, records: CleanupAttemptRecords, stopped: Stopped): void {
  const row = exact(records.output, OUTPUT, "cleanup owned output"), ledger = exact(row.ledger, ["path", "sha256"], "cleanup ledger");
  const expected = path.join(path.dirname(input.held.claimPath), "cleanup-attempts", input.fact.cleanupAttemptId, "owned-process-ledger.cleanup.jsonl");
  if (row.schemaVersion !== 2 || row.kind !== "guided-opening-cleanup-owned-output" || row.mediaProcessGroupStopped !== true
      || row.cleanupProcessGroupStopped !== true || row.cleanupNestedOwnership !== "resolved-by-normal-return"
      || row.invocationSha256 !== input.fact.cleanupInvocationSha256 || ledger.path !== expected
      || typeof row.stdout !== "string" || typeof row.stderr !== "string" || Buffer.byteLength(row.stderr, "utf8") > 2 * 1024 * 1024
      || typeof row.elapsedMs !== "number" || !Number.isFinite(row.elapsedMs) || row.elapsedMs < 0 || row.elapsedMs > 300_000) {
    throw new Error("Cleanup owned output is incomplete or not the exact bounded attempt");
  }
  sha256(ledger.sha256, "cleanup ledger SHA");
  const stamps = [input.held.claim.generationStartedAt, stopped.receipt.finishedAt, records.start.receivedAt,
    records.start.startedAt, records.invocation.observedAt, row.observedAt, input.fact.createdAt].map(strictGuidedTimestamp);
  if (stamps.some((at, index) => index > 0 && at < stamps[index - 1])) throw new Error("Cleanup attempt original clocks are not chronological");
}

/** Join every record to the same original full request, actual stopped return and ordered archive names. */
export function validateCleanupAttemptRecords(input: SourceColorCleanupAttemptReadInput, records: CleanupAttemptRecords,
  stopped: Stopped, names: readonly string[]) {
  startRecord(input, records, stopped); const tools = invocationRecord(input, records, stopped); outputRecord(input, records, stopped);
  const result = parseCurrentOpeningCleanupStdout(String(records.output.stdout));
  if (result.schemaVersion !== 2 || !stopped.sourceColor) throw new Error("Cleanup history requires exact V2 result and V3 process reference");
  assertSourceColorCleanupResult(result, { held: input.held, reference: stopped.sourceColor }, names);
  if (result.elapsedMs > Number(records.output.elapsedMs) + 1 || canonicalJsonSha256(result) !== input.fact.cleanupResultHash) {
    throw new Error("Cleanup result differs from exact owned output or elapsed time");
  }
  return { tools, result };
}
