import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseBodyCleanupResult } from "@/lib/producer/contracts/guided-body-result-v1";
import { parseCurrentBodyMediaCompletion, parseCurrentBodyMediaReadback } from "@/lib/producer/contracts/guided-body-result-v2";
import { objectValue, exactKeys, sha256 } from "@/lib/producer/contracts/validation";
import { bodyTimestamp } from "@/lib/producer/contracts/guided-body-activation-v1";
import { canonicalJsonSha256 as hash } from "./auto-edit-hash";
import { assertOpeningFailureAbsent } from "./guided-opening-process-activation";
import { readStoppedBodyProcess } from "./guided-body-process";
import { readHistoricalBodyPhase, type readBodyPhase } from "./guided-body-phase";
import { bodyChildTools } from "./guided-body-process-tools";
import { liveRecordedDescendants, observeOwnedWorkerLedger } from "./guided-opening-process-ledger";
import { BodySourceColorResultHold } from "./guided-body-source-color-result-hold";
import { bodyAdmissionInputVersion } from "./guided-body-lineage";
import { observeGuidedBodyMediaInput } from "./guided-body-input";
import { snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";

/** TEST may replace only actual stopped native/OS provenance; original admission and raw joins remain hardwired. */
export const bodyResultReads = { stopped: readStoppedBodyProcess };
const sourceResults = new WeakMap<object, BodySourceColorResultHold>();

function sourceHold(process: ReturnType<typeof readBodyPhase>): BodySourceColorResultHold | undefined {
  const fixed = snapshotSourceColorMetadata(process);
  const version = bodyAdmissionInputVersion(process.held.admission);
  const source = version === 2 ? new BodySourceColorResultHold(process) : undefined;
  const original = observeGuidedBodyMediaInput(process.held.activation.inputPath, process.held.activation.inputSha256);
  if (version !== original.input.schemaVersion || version !== process.held.invocation.input.schemaVersion) {
    throw new Error("Body result cannot downgrade its original input version");
  }
  source?.metadata();
  if (!isDeepStrictEqual(process, fixed)) throw new Error("Body original process phase changed during result entry");
  return source;
}

/** Actual durable completion-bound receipt bytes only; no decoded/current-source proof inferred here. */
export function readHeldBodyResult(process: ReturnType<typeof readBodyPhase>) {
  const source = sourceHold(process), readStopped = bodyResultReads.stopped;
  const stopped = readStopped(process) as ReturnType<typeof readStoppedBodyProcess> & { held: typeof process.held };
  const { held } = stopped, a = held.activation;
  if (held !== process.held || bodyResultReads.stopped !== readStopped) throw new Error("Body stopped reader replaced its original held invocation");
  source?.retain(stopped); source?.metadata();
  if (stopped.receipt.status !== "complete") throw new Error("Body media process failed; no candidate may be selected");
  const completion = parseCurrentBodyMediaCompletion(String(stopped.receipt.stdout));
  source?.retain(completion);
  const receiptPath = path.join(a.outputRoot, "body-result.json");
  if (completion.executionId !== a.executionId || completion.inputSha256 !== a.inputSha256
      || completion.executionActivationSha256 !== held.activationSha256 || completion.receiptPath !== receiptPath
      || completion.schemaVersion !== held.invocation.input.schemaVersion) {
    throw new Error("Body completion differs from its actual owned invocation");
  }
  assertOpeningFailureAbsent(path.join(a.outputRoot, "body-failed.json"));
  const record = readCutPreviewObject(receiptPath);
  source?.retain(record);
  const { receiptHash, ...body } = record.value;
  if (record.sha256 !== completion.receiptSha256 || receiptHash !== completion.receiptHash || hash(body) !== receiptHash) {
    throw new Error("Body result bytes differ from actual held worker return");
  }
  if (completion.schemaVersion === 2) {
    if (!source) throw new Error("Body source result lacks its genuine original hold");
    source.receipt(record, completion);
  }
  const result = { stopped, completion, record, sourceBytesObserved: false as const, mediaBytesObserved: false as const };
  if (source) { source.retain(result); source.metadata(); sourceResults.set(result, source); }
  return result;
}

/** Callback-free source2 metadata lifetime only, not current source/media observation or a renewed body clock. */
export function assertHeldBodyResultMetadata(selected: ReturnType<typeof readHeldBodyResult>): void {
  const source = sourceResults.get(selected);
  if (source) { source.metadata(); return; }
  if (selected.completion.schemaVersion !== 1 || selected.record.value.schemaVersion !== 1
      || selected.stopped.held.invocation.input.schemaVersion !== 1
      || bodyAdmissionInputVersion(selected.stopped.held.admission) !== 1) throw new Error("Body source result requires its actual private metadata hold");
  const held = selected.stopped.held;
  if (observeGuidedBodyMediaInput(held.activation.inputPath, held.activation.inputSha256).input.schemaVersion !== 1) {
    throw new Error("Body source result cannot discard its original version");
  }
}

/** Match only a just-returned strong reader, not a directory-selected success object. */
export function assertBodyReadbackIdentity(stdout: string, selected: ReturnType<typeof readHeldBodyResult>) {
  assertHeldBodyResultMetadata(selected); const row = parseCurrentBodyMediaReadback(stdout);
  if (row.schemaVersion !== selected.completion.schemaVersion) throw new Error("Body readback changed its original input/result version");
  for (const key of ["executionId", "inputSha256", "executionActivationSha256", "receiptPath", "receiptSha256", "receiptHash"] as const) {
    if (row[key] !== selected.completion[key]) throw new Error("Body current readback returned a different held result");
  }
  if (row.schemaVersion === 2 && selected.completion.schemaVersion === 2
      && (!isDeepStrictEqual(row.sourceColorReplay, selected.completion.sourceColorReplay)
      || !isDeepStrictEqual(row.sourceColorReadback, selected.completion.sourceColorReadback))) throw new Error("Body readback changed its original completed replay evidence");
  assertHeldBodyResultMetadata(selected);
  return row;
}

/** Re-read exact owned cleanup provenance. Historic absence is not today's source/media freshness. */
export function readHeldBodyCleanup(phase: ReturnType<typeof readBodyPhase>) {
  if (phase.fact.phase !== "cleanup") throw new Error("Body cleanup requires the exact cleanup phase");
  const { held, fact } = phase, dir = held.admission.before.job.ctx.dir;
  const process = readHistoricalBodyPhase(dir, "process", fact.beforeJournalHash), stopped = readStoppedBodyProcess(process);
  const start = readCutPreviewObject(fact.references.start.path), output = readCutPreviewObject(fact.references.output.path);
  const directory = path.dirname(fact.references.start.path), relative = path.relative(path.join(path.dirname(held.activationPath), "body-cleanup-attempts"), directory);
  if (!/^[a-f0-9-]{36}$/u.test(relative) || fact.references.start.path !== path.join(directory, "start.json")
      || fact.references.output.path !== path.join(directory, "output.json") || start.sha256 !== fact.references.start.sha256
      || output.sha256 !== fact.references.output.sha256) throw new Error("Body cleanup records changed identity or role");
  assertOpeningFailureAbsent(path.join(directory, "failure.json"));
  const startKeys = ["schemaVersion", "kind", "beforeJournalHash", "activationHash", "processFactHash", "processOutcomeSha256", "tools",
    "clockHash", "generationStartedAt", "startedAt", "budgetScope"];
  exactKeys(start.value, startKeys, startKeys, "body cleanup start");
  const outputKeys = ["schemaVersion", "kind", "stdout", "stderr", "groupStopped", "forcedStop", "ledgerSha256", "observedAt", "elapsedMs"];
  exactKeys(output.value, outputKeys, outputKeys, "body cleanup owned output");
  const tools = bodyChildTools(held, "cleanup");
  if (start.value.kind !== "guided-body-cleanup-start" || start.value.schemaVersion !== 1 || start.value.activationHash !== held.activationHash
      || start.value.beforeJournalHash !== process.current.sha256 || start.value.processFactHash !== process.factHash
      || start.value.processOutcomeSha256 !== stopped.output.sha256 || hash(start.value.tools) !== hash(tools)
      || start.value.clockHash !== held.activation.clockHash || start.value.generationStartedAt !== held.activation.generationStartedAt
      || start.value.budgetScope !== "protected-cleanup-counted-in-original-request-no-render-credit") throw new Error("Body cleanup lost its owned start/process binding");
  assertBodyOwnedOutput(output.value, { kind: "guided-body-cleanup-owned-output", startedAt: String(start.value.startedAt), createdAt: fact.createdAt, limit: 300_000 });
  observeOwnedWorkerLedger(directory, "cleanup", tools.script, sha256(output.value.ledgerSha256, "cleanup ledger SHA"));
  const nested = liveRecordedDescendants(directory, "cleanup");
  if (nested.live.length || nested.unknown.length || nested.unrecordedSpawns.length) throw new Error("Body cleanup nested ownership is unresolved");
  const result = parseBodyCleanupResult(String(output.value.stdout));
  if (result.activationPath !== held.activationPath || result.activationSha256 !== held.activationSha256 || result.inputSha256 !== held.activation.inputSha256
      || result.outputRoot !== held.activation.outputRoot || result.executionId !== held.activation.executionId
      || hash(result.graphics.map((row) => row.order)) !== hash(held.activation.selectedGraphicOrders)) throw new Error("Body cleanup names another owned invocation");
  return { phase, process, stopped, start, output, result };
}

export function assertBodyOwnedOutput(value: unknown, input: { kind: string; startedAt: string; createdAt: string; limit: number }): void {
  const row = objectValue(value, "body owned output"), observedAt = bodyTimestamp(row.observedAt);
  const keys = ["schemaVersion", "kind", "stdout", "stderr", "groupStopped", "forcedStop", "ledgerSha256", "observedAt", "elapsedMs"];
  exactKeys(row, keys, keys, "body owned output");
  if (row.schemaVersion !== 1 || row.kind !== input.kind || row.groupStopped !== true || row.forcedStop !== false
      || observedAt < bodyTimestamp(input.startedAt) || observedAt > bodyTimestamp(input.createdAt)
      || typeof row.elapsedMs !== "number" || !Number.isFinite(row.elapsedMs) || row.elapsedMs < 0 || row.elapsedMs > input.limit
      || [row.stdout, row.stderr].some((value) => typeof value !== "string" || Buffer.byteLength(value, "utf8") > 2 * 1024 * 1024)) {
    throw new Error("Body output lacks actual bounded normal-return ownership");
  }
}
