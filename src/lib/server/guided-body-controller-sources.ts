/** Current TS/snapshot equivalence only: no loaded-bundle, package, native, lease or launch authority. */
import fs from "node:fs";
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { exactKeys } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { BODY_DEADLINE_POLICY } from "./guided-body-deadline";
import { finiteDeadlineClock } from "./generation-attempt-clock";
import { assertBodyClaimSourceColorMetadata, type readGuidedBodyClaim } from "./guided-body-lineage";
import { pinnedPipelineSourceFile } from "./guided-proposal-evidence";
import { GUIDED_SOURCE_COLOR_TS_FILES } from "./guided-source-color-cleanup-pins";
import { snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";

type Admission = ReturnType<typeof readGuidedBodyClaim>;
interface SourceInput { admission: Admission; remainingMs: () => number }
interface SourcePin { readonly path: string; readonly sha256: string }
export interface HeldBodyControllerSources {
  readonly scope: "original-source2-controller-source-bytes-not-native-or-launch-authority";
  readonly pipelineDigest: string;
  readonly files: readonly SourcePin[];
  check(): void;
  assertMetadata(): void;
}
const actualSources = new WeakMap<HeldBodyControllerSources, BodyControllerSources>();
const MAX_SOURCE_BYTES = 32 * 1024 * 1024;
const MAX_FILE_BYTES = 2 * 1024 * 1024;
const MAX_LOCK_BYTES = 16 * 1024 * 1024;

/** Sources need not be private 0600 metadata; neither symlinks nor hardlinks are accepted. */
function fileIdentity(file: string, maximum: number): bigint[] {
  if (fs.realpathSync(file) !== file) throw new Error("Body controller source path is not canonical");
  const row = fs.lstatSync(file, { bigint: true });
  if (!row.isFile() || row.nlink !== BigInt(1)
      || row.size < BigInt(1) || row.size > BigInt(maximum)) throw new Error("Body controller source is not a bounded canonical regular file");
  return [row.dev, row.ino, row.mode, row.uid, row.nlink, row.size, row.mtimeNs, row.ctimeNs];
}
function directoryIdentity(directory: string): bigint[] {
  if (fs.realpathSync(directory) !== directory) throw new Error("Body controller source parent is not canonical");
  const row = fs.lstatSync(directory, { bigint: true });
  if (!row.isDirectory()) throw new Error("Body controller source parent is not a directory");
  return [row.dev, row.ino, row.mode, row.uid];
}
function same(actual: unknown, expected: unknown, label: string): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error(`Body controller original ${label} changed`);
}

/** One original finite inventory. The old admission's current-journal guard is initial-only. */
class BodyControllerSources {
  readonly #original;
  readonly #fixed;
  readonly #pipeline;
  readonly #root;
  readonly #now;
  readonly #began;
  readonly #files = new Map<string, { identity: bigint[]; maximum: number }>();
  readonly #parents = new Map<string, bigint[]>();
  readonly #pins: readonly SourcePin[];
  #previous;
  #end;
  #sampled = false;
  #busy = false;
  #invalid = false;

  constructor(readonly input: SourceInput) {
    this.#original = { ...input };
    this.#fixed = snapshotSourceColorMetadata(input.admission);
    const pipeline = input.admission.before.job.ctx.pipeline;
    if (!pipeline) throw new Error("Body controller original pipeline is unavailable");
    this.#pipeline = pipeline; this.#root = process.cwd(); this.#now = performance.now.bind(performance);
    this.#began = finiteDeadlineClock(this.#now()); this.#previous = this.#began;
    this.#end = this.#began + BODY_DEADLINE_POLICY.wholeAttemptMs;
    this.#unchanged();
    assertBodyClaimSourceColorMetadata(input.admission);
    this.#unchanged();
    if (input.admission.input.row.schemaVersion !== 2 || input.admission.input.input.schemaVersion !== 2
        || typeof input.remainingMs !== "function") throw new Error("Body controller sources require an actual source2 admission and original remainder");
    if (pipeline.schemaVersion !== 1 || !Array.isArray(pipeline.files) || pipeline.files.length > 16384
        || canonicalJsonSha256(pipeline.files) !== pipeline.digest) throw new Error("Body controller original pipeline is malformed");
    this.#pins = this.#requiredPins();
    this.#captureAll(); this.#metadata(); this.#sample();
    assertBodyClaimSourceColorMetadata(input.admission); this.#qualify();
    assertBodyClaimSourceColorMetadata(input.admission); this.check();
  }

  #requiredPins(): readonly SourcePin[] {
    if (GUIDED_SOURCE_COLOR_TS_FILES.length > 512) throw new Error("Body controller source inventory exceeds its finite bound");
    return Object.freeze(GUIDED_SOURCE_COLOR_TS_FILES.map(relative => {
      const rows = this.#pipeline.files.filter(row => row.path === relative);
      if (rows.length !== 1 || !/^[a-f0-9]{64}$/u.test(rows[0].hash)) throw new Error(`Body pipeline predates or repeats required controller source: ${relative}`);
      return Object.freeze({ path: relative, sha256: rows[0].hash });
    }));
  }
  #capture(file: string, maximum = MAX_FILE_BYTES): number {
    for (let parent = path.dirname(file); !this.#parents.has(parent); parent = path.dirname(parent)) {
      this.#parents.set(parent, directoryIdentity(parent));
    }
    const identity = fileIdentity(file, maximum); this.#files.set(file, { identity, maximum }); return Number(identity[5]);
  }
  #captureAll(): void {
    let total = 0;
    for (const pin of this.#pins) {
      total += this.#capture(path.join(this.#root, pin.path));
      total += this.#capture(path.join(this.#pipeline.snapshotRoot, pin.path));
      if (total > 2 * MAX_SOURCE_BYTES) throw new Error("Body controller source inventory exceeds its aggregate byte bound");
    }
    this.#capture(this.#pipeline.lockPath, MAX_LOCK_BYTES);
  }
  #unchanged(): void {
    same(process.cwd(), this.#root, "source root");
    if (this.input.admission !== this.#original.admission || this.input.remainingMs !== this.#original.remainingMs) {
      throw new Error("Body controller original caller identity changed");
    }
    same(this.input.admission, this.#fixed, "admission metadata");
    if (this.input.admission.before.job.ctx.pipeline !== this.#pipeline) throw new Error("Body controller original pipeline identity changed");
  }
  #ancestry(): void {
    for (const [directory, identity] of this.#parents) same(directoryIdentity(directory), identity, "source parent");
  }
  #metadata(): void {
    this.#unchanged(); this.#ancestry();
    for (const [file, original] of this.#files) same(fileIdentity(file, original.maximum), original.identity, "source file");
    this.#ancestry(); this.#unchanged(); this.#time();
  }
  #time = (): number => {
    if (this.#invalid) throw new Error("Body controller original budget or metadata is invalid");
    const now = finiteDeadlineClock(this.#now());
    if (now < this.#previous || now >= this.#end) {
      this.#invalid = true; throw new Error("Body controller original monotonic budget expired or moved backwards");
    }
    this.#previous = now; return now;
  };
  #sample(): void {
    const before = this.#time(); let remaining: number, failed = false;
    try { remaining = finiteDeadlineClock(this.#original.remainingMs()); }
    catch (error) { failed = true; throw error; }
    finally { this.#afterSample(failed); }
    if (remaining < 1 || remaining > BODY_DEADLINE_POLICY.wholeAttemptMs) throw new Error("Body controller original remaining budget is invalid");
    // First capture is deliberately charged conservatively; later samples can only shorten this end.
    this.#end = Math.min(this.#end, (this.#sampled ? before : this.#began) + remaining);
    this.#sampled = true; this.#metadata();
  }
  #afterSample(primaryFailed: boolean): void {
    try { this.#time(); }
    catch (error) { this.#invalid = true; if (!primaryFailed) throw error; }
  }
  #lock(): void {
    const observed = observeCutPreviewFile(this.#pipeline.lockPath, MAX_LOCK_BYTES, true, this.#time);
    const value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes));
    const keys = ["schemaVersion", "state", "runId", "digest", "files"];
    exactKeys(value, keys, keys, "body controller pipeline lock");
    same(value, { schemaVersion: 1, state: "pinned", runId: this.#pipeline.runId,
      digest: this.#pipeline.digest, files: this.#pipeline.files }, "pipeline lock");
  }
  #qualify(): void {
    this.#lock();
    for (const pin of this.#pins) {
      const observed = pinnedPipelineSourceFile(this.#pipeline, pin.path, { current: true, guard: this.#time });
      same(observed.sha256, pin.sha256, "source SHA"); this.#unchanged();
    }
    this.#metadata();
  }
  #run(callback: () => void): void {
    if (this.#busy || this.#invalid) {
      this.#invalid = true; throw new Error("Body controller source check cannot reenter or revive an invalid hold");
    }
    this.#busy = true;
    try { callback(); }
    catch (error) { this.#invalid = true; throw error; }
    finally { this.#busy = false; }
  }
  check = (): void => { this.#run(() => { this.#metadata(); this.#sample(); }); };
  assertMetadata = (): void => { this.#run(() => { this.#metadata(); }); };
  result(): HeldBodyControllerSources {
    return Object.freeze({ scope: "original-source2-controller-source-bytes-not-native-or-launch-authority" as const,
      pipelineDigest: this.#pipeline.digest, files: this.#pins, check: this.check, assertMetadata: this.assertMetadata });
  }
  assertAdmission(admission?: Admission): void {
    if (admission !== undefined && admission !== this.#original.admission) throw new Error("Body controller source hold belongs to another original admission");
  }
}

/** Authenticate an actual source2 admission once, without starting or renewing its original body clock. */
export function holdBodyControllerSources(input: SourceInput): HeldBodyControllerSources {
  const held = new BodyControllerSources(input), result = held.result();
  held.assertMetadata(); actualSources.set(result, held); return result;
}

/** No caller callback, current journal re-read, hash/decode or lease authority; copies cannot substitute. */
export function assertBodyControllerSourcesMetadata(value: HeldBodyControllerSources, admission?: Admission): void {
  const held = actualSources.get(value);
  if (!held) throw new Error("Body controller sources require their actual original private holder");
  held.assertAdmission(admission); held.assertMetadata();
}
