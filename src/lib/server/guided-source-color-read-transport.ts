/** Explicit cold read transport from genuine final cleanup and actual completion.
 * No resource ownership, new clock, native execution, selection or approval is granted.
 */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { exactKeys, objectValue, sha256 } from "@/lib/producer/contracts/validation";
import { openingAbsolutePath } from "@/lib/producer/contracts/guided-opening-media-v1";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { assertOpeningCleanupMetadata, type readCommittedOpeningCleanup, type readHistoricalOpeningCleanup } from "./guided-opening-cleanup-store";
import { assertSourceColorOpeningResultMetadata, sourceColorOpeningReadbackReceiptArguments,
  type HeldSourceColorOpeningResult } from "./guided-source-color-opening-result";
import type { HeldOpeningClaim, openingChildTools } from "./guided-opening-process";

interface SourceColorReadContext {
  cleanup: ReturnType<typeof readCommittedOpeningCleanup> | ReturnType<typeof readHistoricalOpeningCleanup>;
  selected: HeldSourceColorOpeningResult;
}
export interface SourceColorReadInvocation {
  readonly kind: "final-cleanup-bound-source-color-read";
  readonly args: readonly string[];
  readonly environment: Readonly<Partial<NodeJS.ProcessEnv>>;
}
const reads = new WeakMap<object, { held: HeldOpeningClaim; check: () => void; tools: Readonly<Record<string, unknown>> }>();

function same(actual: unknown, expected: unknown, label: string): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error(`Source-color cold read ${label} differs from original evidence`);
}

/** Preserve the actual original interpreter/runner; change only the pinned worker's read role. */
export function sourceColorOpeningReadTools(held: HeldOpeningClaim, selected: HeldSourceColorOpeningResult): Readonly<Record<string, unknown>> {
  assertSourceColorOpeningResultMetadata(selected, held);
  const intent = readCutPreviewObject(path.join(path.dirname(held.claimPath), "media-process-intent.json"));
  if (canonicalJsonSha256(intent.value) !== selected.process.intentHash) throw new Error("Source-color read lost its original tool intent");
  const pipeline = held.job.ctx.pipeline!, relative = "scripts/producer/guided_opening_read.py";
  const entries = pipeline.files.filter(row => row.path === relative);
  if (entries.length !== 1) throw new Error("Source-color read requires one exact original pinned read worker");
  const original = objectValue(intent.value.tools, "original source-color process tools");
  const tools = Object.freeze({ ...structuredClone(original), script: path.join(pipeline.snapshotRoot, relative), scriptHash: entries[0].hash });
  assertSourceColorOpeningResultMetadata(selected, held); return tools;
}

/** Current pinned media tool paths only; Python separately authenticates their bytes before native readback. */
function toolPath(selected: HeldSourceColorOpeningResult): string {
  const pipeline = objectValue(selected.record.value.pipeline, "source-color executed pipeline");
  const tools = objectValue(pipeline.tools, "source-color executed tools");
  exactKeys(tools, ["python", "ffmpeg", "ffprobe"], ["python", "ffmpeg", "ffprobe"], "source-color executed tools");
  const directories = ["ffmpeg", "ffprobe", "python"].map(name => {
    const tool = objectValue(tools[name], name); exactKeys(tool, ["path", "sha256"], ["path", "sha256"], name);
    sha256(tool.sha256, `${name} SHA`); return path.dirname(openingAbsolutePath(tool.path));
  });
  return [...new Set(directories)].join(path.delimiter);
}

/** Suppress retired Docker controls and ambient tool fallback. This is not image/runtime admission. */
function environment(selected: HeldSourceColorOpeningResult): Readonly<Partial<NodeJS.ProcessEnv>> {
  return Object.freeze({ PATH: toolPath(selected), SNIPER_DOCKER_PATH: undefined, SNIPER_DOCKER_SOCKET: undefined,
    SNIPER_RENDER_IMAGE_ID: undefined, SNIPER_RENDER_UID_GID: undefined, SNIPER_RUNTIME_REPO_ROOT: undefined,
    DOCKER_HOST: undefined, DOCKER_CONTEXT: undefined, DOCKER_CONFIG: undefined,
    DOCKER_TLS_VERIFY: undefined, DOCKER_CERT_PATH: undefined });
}

/** Build all four source-color flags only from the independently authenticated stopped/final chain. */
export function holdSourceColorReadInvocation(input: SourceColorReadContext): SourceColorReadInvocation {
  const cleanup = input.cleanup, selected = input.selected, held = cleanup.held;
  const check = () => {
    if (input.cleanup !== cleanup || input.selected !== selected) throw new Error("Source-color cold read original caller changed");
    assertOpeningCleanupMetadata(cleanup); assertSourceColorOpeningResultMetadata(selected, held);
    assertOpeningCleanupMetadata(cleanup);
  };
  check();
  if (!("pending" in cleanup) || cleanup.receipt.phase !== "retired" || cleanup.receipt.claimRetained !== false) {
    throw new Error("Source-color cold read requires actual final reservation retirement");
  }
  const stop = cleanup.evidence.stop, source = stop.sourceColor, fact = cleanup.pending.fact;
  if (stop.receipt.schemaVersion !== 3 || !source || stop.receipt.status !== "complete"
      || stop.nestedOwnership !== "resolved-by-normal-return" || stop.receipt.forcedStop !== false) {
    throw new Error("Source-color cold read requires actual successfully settled V3 output");
  }
  same(selected.process, stop, "stopped process"); same(source.reservation, fact.reservation, "original reservation");
  same(source.sourceColorHash, fact.sourceColorHash, "full color request");
  same([fact.archive.sha256, fact.archive.sizeBytes], [source.reservation.sha256, source.reservation.sizeBytes], "archived raw bytes");
  same(fact.archive.path, path.join(path.dirname(held.claimPath), "cleanup-attempts", fact.cleanupAttemptId, "reservation.json"), "archive path");
  const args = Object.freeze([...sourceColorOpeningReadbackReceiptArguments(selected),
    "--source-color-input", source.input.path, "--source-color-input-sha256", source.input.sha256,
    "--source-color-reservation-archive", fact.archive.path, "--source-color-reservation-archive-sha256", fact.archive.sha256]);
  const value = Object.freeze({ kind: "final-cleanup-bound-source-color-read" as const, args, environment: environment(selected) });
  const tools = sourceColorOpeningReadTools(held, selected);
  check(); reads.set(value, { held, check, tools }); return value;
}

/** Finite metadata only, including exact original held claim; DTOs cannot select the cold environment. */
export function assertSourceColorReadInvocation(value: SourceColorReadInvocation, held: HeldOpeningClaim): void {
  const original = reads.get(value);
  if (!original || original.held !== held) throw new Error("Source-color cold read needs its actual original final-bound invocation");
  original.check();
}

/** A genuine read capability cannot authorize another script, interpreter, runner or venv. */
export function assertSourceColorReadTools(value: SourceColorReadInvocation, held: HeldOpeningClaim,
  tools: ReturnType<typeof openingChildTools>): void {
  assertSourceColorReadInvocation(value, held);
  same(tools, reads.get(value)!.tools, "original pinned read tools");
}
