/** Original metadata expectations only; Python still owns admission and source observation.
 * The guard is followed by mutation-safe metadata/stat checks. Their final IO can
 * consume the remaining caller budget: this reader is NOT a hard deadline or
 * launch authority. The downstream owner must recheck its original remaining
 * budget at the phase boundary before work; the Python phase retains its hard
 * wall timer. A future separately held original cutoff must not renew its epoch.
 */
import fs from "node:fs";
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { assertGuidedSourceColorCoverage, SOURCE_COLOR_V2_PROFILE, type GuidedSourceColorV1,
  type SourceColorSelection } from "@/lib/producer/contracts/guided-source-color-v1";
import { exactKeys, objectValue, sha256 } from "@/lib/producer/contracts/validation";
import { parsePositiveRationalV1 } from "@/lib/producer/contracts/positive-rational";
import { requireSourceSetAdmission, type AssetManifest } from "@/lib/producer/types";
import type { observeGuidedOpeningMediaInput } from "./guided-opening-media-input";

type Json = Record<string, unknown>;
export interface SourceColorExpectation {
  readonly sourceId: string; readonly sourcePath: string; readonly sourceSha256: string;
  readonly sourceSizeBytes: number; readonly frameCount: number;
  readonly profile: SourceColorSelection["profile"]; readonly declaration: SourceColorSelection["declaration"];
  readonly admissionReceiptPath: string; readonly admissionReceiptSha256: string;
}
export interface SourceColorExpectationContext {
  opening: ReturnType<typeof observeGuidedOpeningMediaInput>; inputPath: string;
  selection: GuidedSourceColorV1; producerDir: string; guard: () => void;
}
export interface SourceColorFileRef { readonly path: string; readonly sha256: string; readonly sizeBytes: number }
export interface HeldSourceColorExpectations {
  readonly scope: "held-source-color-expectations-not-source-observation-or-approval";
  readonly sources: readonly SourceColorExpectation[];
  readonly parents: { readonly planSha256: string; readonly manifestSha256: string; readonly projectSha256: string };
  readonly files: readonly SourceColorFileRef[];
  /** Metadata lifetime only; the final stat sweep is not covered by a final time-only check. */
  assertCurrent(): void;
}
interface FileHold {
  file: string; expected?: string; maximum: number; group: "opening" | "color";
  identity: bigint[]; ancestry: Array<[string, bigint, bigint, bigint, bigint]>;
}
const MIB = 1024 * 1024;
const ENTRY_KEYS = ["lane", "originalPath", "snapshotPath", "sha256", "sizeBytes", "mediaKind", "admissionReceiptPath", "admissionReceiptSha256"];
const FACT_KEYS = ["mediaKind", "durationSeconds", "sizeBytes", "width", "height", "videoStreams", "audioStreams", "streamCount", "declaredFrames"];

function closed(value: unknown, keys: string[], label: string): Json {
  const row = objectValue(value, label); exactKeys(row, keys, keys, label); return row;
}
function integer(value: unknown, maximum: number, label: string): number {
  if (!Number.isSafeInteger(value) || Number(value) < 1 || Number(value) > maximum) throw new Error(`Source color ${label} is invalid`);
  return Number(value);
}
function canonical(file: unknown): string {
  if (typeof file !== "string" || !path.isAbsolute(file) || path.resolve(file) !== file || /[\\\u0000-\u001f]/u.test(file)) {
    throw new Error("Source color metadata path is not canonical");
  }
  return file;
}
function identity(file: string): bigint[] {
  const row = fs.lstatSync(file, { bigint: true });
  if (!row.isFile() || row.nlink !== BigInt(1)) throw new Error("Source color metadata is not a regular single-link file");
  return [row.dev, row.ino, row.mode, row.uid, row.nlink, row.size, row.mtimeNs, row.ctimeNs];
}
function ancestry(file: string): FileHold["ancestry"] {
  const result: FileHold["ancestry"] = []; let directory = path.dirname(file);
  if (fs.realpathSync(directory) !== directory) throw new Error("Source color metadata parent is aliased");
  for (;;) {
    const row = fs.lstatSync(directory, { bigint: true });
    if (!row.isDirectory()) throw new Error("Source color metadata parent is not a directory");
    result.push([directory, row.dev, row.ino, row.mode, row.uid]);
    if (path.dirname(directory) === directory) return result;
    directory = path.dirname(directory);
  }
}
function freeze<T>(value: T): T {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freeze); Object.freeze(value);
  }
  return value;
}

/** Capture every known original reference before the first caller callback. */
class ExpectationRead {
  readonly held = new Map<string, FileHold>();
  readonly values = new Map<string, { value: Json; ref: SourceColorFileRef }>();
  readonly spent = { opening: 0, color: 0 };
  private readonly original;
  private readonly fixed;
  constructor(readonly context: SourceColorExpectationContext) {
    this.original = { opening: context.opening, selection: context.selection, guard: context.guard };
    this.fixed = structuredClone(this.metadata());
  }
  private metadata() {
    const { opening } = this.context;
    return { inputPath: this.context.inputPath, producerDir: this.context.producerDir, selection: this.context.selection,
      input: opening.input, inputSha256: opening.inputSha256, authority: opening.authority,
      documents: Object.fromEntries(Object.entries(opening.documents).map(([key, row]) => [key,
        { sha256: row.sha256, sizeBytes: row.sizeBytes, value: row.value }])) };
  }
  private unchanged(): void {
    if (this.context.opening !== this.original.opening || this.context.selection !== this.original.selection
        || this.context.guard !== this.original.guard || !isDeepStrictEqual(this.metadata(), this.fixed)) {
      throw new Error("Source color original context or metadata changed");
    }
  }
  add(file: string, options: { expected?: string; maximum: number; group: FileHold["group"] }): void {
    canonical(file); if (options.expected !== undefined) sha256(options.expected, "source color original file SHA");
    const previous = this.held.get(file);
    if (previous) {
      if (options.expected !== undefined && previous.expected !== options.expected) throw new Error("Source color file references conflict");
      previous.maximum = Math.min(previous.maximum, options.maximum); return;
    }
    this.held.set(file, { file, ...options, identity: identity(file), ancestry: ancestry(file) });
  }
  check = (): void => {
    this.unchanged(); this.original.guard(); this.unchanged();
    for (const row of this.held.values()) {
      if (!isDeepStrictEqual(identity(row.file), row.identity) || !isDeepStrictEqual(ancestry(row.file), row.ancestry)) {
        throw new Error("Source color held metadata file or parent changed");
      }
    }
    this.unchanged();
  };
  read(file: string) {
    const cached = this.values.get(file); if (cached) return cached;
    const held = this.held.get(file); if (!held) throw new Error("Source color read lacks an original file hold");
    const observed = observeCutPreviewFile(file, Math.min(held.maximum, 64 * MIB - this.spent[held.group]), true, this.check);
    this.spent[held.group] += observed.sizeBytes;
    if (held.expected !== undefined && observed.sha256 !== held.expected) throw new Error("Source color original raw file SHA differs");
    const value = objectValue(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes)), "source color metadata");
    const result = { value, ref: { path: file, sha256: observed.sha256, sizeBytes: observed.sizeBytes } };
    this.values.set(file, result); this.check(); return result;
  }
}

function usedSources(context: SourceColorExpectationContext): string[] {
  const docs = context.opening.documents, cuts = docs.acceptedPlan.value.cutTrack;
  if (!Array.isArray(cuts) || !cuts.length || cuts.length > 10000 || !isDeepStrictEqual(cuts, docs.candidatePlan.value.cutTrack)) {
    throw new Error("Source color requires the unchanged nonempty accepted cut");
  }
  const ids = [...new Set(cuts.map(row => objectValue(row, "source color kept cut").sourceId))] as string[];
  assertGuidedSourceColorCoverage(context.selection, ids); return ids;
}
/** Match the existing Python exact-rate parser, without deriving an FPS from duration. */
function sourceRate(value: unknown) {
  if (typeof value !== "string" || value.length > 64) throw new Error("Source color source rate is invalid");
  const parts = value.split("/");
  if (parts.length > 2) throw new Error("Source color source rate is invalid");
  const rate = parsePositiveRationalV1({ numerator: parts[0], denominator: parts[1] ?? "1" });
  if (![rate.numerator, rate.denominator].every(item => Number.isSafeInteger(Number(item)))) {
    throw new Error("Source color source rate exceeds safe integer components");
  }
  const numerator = BigInt(rate.numerator), denominator = BigInt(rate.denominator);
  const token = denominator === BigInt(1) ? rate.numerator : `${rate.numerator}/${rate.denominator}`;
  if (token.length > 24 || numerator < denominator || numerator > BigInt(60) * denominator) {
    throw new Error("Source color source rate exceeds the existing exact 1..60 grade class");
  }
  return { numerator, denominator };
}
function selectedSources(context: SourceColorExpectationContext, ids: string[]): Json[] {
  const sources = context.opening.documents.manifest.value.sources;
  if (!Array.isArray(sources)) throw new Error("Source color original manifest has no sources");
  return ids.map(id => {
    const matches = sources.filter(value => objectValue(value, "source color manifest row").id === id);
    if (matches.length !== 1) throw new Error("Source color selected source is missing or duplicated");
    const row = objectValue(matches[0], "source color selected row");
    if (row.vfr !== false || typeof row.frameRate !== "string") {
      throw new Error("Source color requires an explicit non-VFR source rate");
    }
    sourceRate(row.frameRate); return row;
  });
}
function receiptPath(producer: string, value: unknown, sha: unknown): string {
  const relative = `.sniper-external-media/receipts/${sha256(sha, "source admission receipt")}.json`;
  if (value !== relative) throw new Error("Source color receipt path differs from its exact hash");
  return path.join(producer, relative);
}
function addOriginalFiles(read: ExpectationRead, sources: Json[], setPath: string): void {
  const { context } = read;
  read.add(context.inputPath, { expected: context.opening.inputSha256, maximum: 128 * 1024, group: "opening" });
  for (const ref of Object.values(context.opening.input.documents)) {
    read.add(ref.path, { expected: ref.sha256, maximum: 16 * MIB, group: "opening" });
  }
  for (const file of ["edit_plan.json", "asset_manifest.json", "../project.json"]) {
    const target = path.resolve(context.producerDir, file), prior = read.held.get(target);
    read.add(target, { expected: prior?.expected, maximum: 2 * MIB, group: "color" });
  }
  const binding = objectValue(context.opening.documents.manifest.value.sourceSetAdmission, "source set");
  read.add(setPath, { expected: String(binding.receiptSha256), maximum: 64 * MIB, group: "color" });
  sources.forEach(row => read.add(receiptPath(context.producerDir, row.admissionReceiptPath, row.admissionReceiptSha256),
    { expected: String(row.admissionReceiptSha256), maximum: 4 * MIB, group: "color" }));
}
function originalParents(read: ExpectationRead) {
  const { context } = read, opening = context.opening;
  if (!isDeepStrictEqual(read.read(context.inputPath).value, opening.input)) throw new Error("Source color original input projection differs");
  for (const [key, ref] of Object.entries(opening.input.documents)) {
    const actual = read.read(ref.path), original = opening.documents[key as keyof typeof opening.documents];
    if (actual.ref.sha256 !== original.sha256 || actual.ref.sizeBytes !== original.sizeBytes || !isDeepStrictEqual(actual.value, original.value)) {
      throw new Error("Source color original document projection differs");
    }
  }
  const plan = read.read(path.join(context.producerDir, "edit_plan.json")), manifest = read.read(path.join(context.producerDir, "asset_manifest.json"));
  const project = read.read(path.join(path.dirname(context.producerDir), "project.json"));
  if (!isDeepStrictEqual(plan.value.cutTrack, opening.documents.acceptedPlan.value.cutTrack)
      || manifest.ref.sha256 !== opening.documents.manifest.sha256) throw new Error("Source color saved parents differ from original opening");
  return { planSha256: plan.ref.sha256, manifestSha256: manifest.ref.sha256, projectSha256: project.ref.sha256 };
}
function sourceSet(read: ExpectationRead, file: string): Json[] {
  const binding = objectValue(read.context.opening.documents.manifest.value.sourceSetAdmission, "source set binding");
  const row = closed(read.read(file).value, ["schemaVersion", "policy", "entries", "sourceSetDigest"], "source set receipt");
  if (row.schemaVersion !== 1 || row.policy !== "sniper-producer-source-set-v1" || !Array.isArray(row.entries)
      || row.entries.length !== binding.entryCount || row.sourceSetDigest !== binding.sourceSetDigest
      || row.sourceSetDigest !== read.context.opening.authority.sourceSetDigest) throw new Error("Source color source-set metadata differs");
  const entries = row.entries.map(value => closed(value, ENTRY_KEYS, "source set entry"));
  if (new Set(entries.map(value => canonical(value.originalPath))).size !== entries.length) throw new Error("Source color source-set repeats an ingress path");
  return entries;
}
function sourceEntry(source: Json, entries: Json[], producer: string): Json {
  const matches = entries.filter(row => row.originalPath === source.originalPath);
  if (matches.length !== 1 || matches[0].lane !== "source") throw new Error("Source color source is absent from its admitted source lane");
  const entry = matches[0], sha = sha256(entry.sha256, "source snapshot SHA"), snapshot = path.join(producer, ".sniper-external-media", `${sha}.media`);
  if (entry.snapshotPath !== snapshot || source.path !== snapshot || source.sourceSha256 !== sha
      || entry.sizeBytes !== source.sourceSizeBytes || entry.mediaKind !== "timed-media"
      || entry.admissionReceiptPath !== source.admissionReceiptPath || entry.admissionReceiptSha256 !== source.admissionReceiptSha256) {
    throw new Error("Source color manifest, source-set and snapshot expectation differ");
  }
  return entry;
}
/** Existing profile ceilings are cheap metadata rejection, not decoded frame/EOF proof. */
function factBudget(facts: Json, v2: boolean, count: number): void {
  const width = integer(facts.width, v2 ? 3840 : 8192, "source width"), height = integer(facts.height, v2 ? 2160 : 8192, "source height");
  const streams = integer(facts.streamCount, 32, "stream count"), audio = facts.audioStreams;
  if (width < 2 || height < 2 || width % 2 || height % 2 || width * height * count > (v2 ? 199065600000 : 37324800000)
      || !Number.isSafeInteger(audio) || Number(audio) < 0 || Number(audio) + 1 > streams
      || typeof facts.durationSeconds !== "number" || !Number.isFinite(facts.durationSeconds) || facts.durationSeconds <= 0) {
    throw new Error("Source color admission scalar/frame/pixel expectation exceeds its profile");
  }
}
function expectation(read: ExpectationRead, source: Json, entry: Json): SourceColorExpectation {
  const sourceId = String(source.id), selected = read.context.selection.declarations[sourceId], v2 = selected.profile === SOURCE_COLOR_V2_PROFILE;
  const file = receiptPath(read.context.producerDir, entry.admissionReceiptPath, entry.admissionReceiptSha256);
  const row = closed(read.read(file).value, ["schemaVersion", "policy", "snapshot", "limits", "image", "isolation", "network", "decoded"], "admission receipt");
  const snapshot = closed(row.snapshot, ["path", "sha256", "sizeBytes"], "admission snapshot");
  const decoded = closed(row.decoded, ["schemaVersion", "ok", "decoded", "facts"], "admission decoded metadata"), facts = closed(decoded.facts, FACT_KEYS, "admission facts");
  const size = integer(entry.sizeBytes, (v2 ? 16 : 8) * 1024 ** 3, "source bytes");
  const count = integer(facts.declaredFrames, v2 ? 24000 : 1296000, "declared frame expectation");
  const rate = sourceRate(source.frameRate);
  if (BigInt(count) * rate.denominator > BigInt(21600) * rate.numerator) throw new Error("Source color source exceeds the existing six-hour grade class");
  factBudget(facts, v2, count);
  if (row.schemaVersion !== 1 || row.policy !== "sniper-external-media-probe-v2" || decoded.schemaVersion !== 1
      || decoded.ok !== true || decoded.decoded !== true || facts.mediaKind !== "timed-media" || facts.videoStreams !== 1
      || facts.sizeBytes !== size || snapshot.path !== entry.snapshotPath || snapshot.sha256 !== entry.sha256 || snapshot.sizeBytes !== size
      || selected.declaration.lightingGroups.at(-1)?.endFrame !== count) throw new Error("Source color admission count/snapshot/declaration expectation differs");
  return { sourceId, sourcePath: String(entry.snapshotPath), sourceSha256: String(entry.sha256), sourceSizeBytes: size,
    frameCount: count, profile: selected.profile, declaration: structuredClone(selected.declaration),
    admissionReceiptPath: file, admissionReceiptSha256: String(entry.admissionReceiptSha256) };
}

/** No source bytes, jobs, clock, decoder or authority are created by this projection. */
export function sourceColorExpectations(context: SourceColorExpectationContext): HeldSourceColorExpectations {
  const read = new ExpectationRead(context), ids = usedSources(context), sources = selectedSources(context, ids);
  canonical(context.producerDir); canonical(context.inputPath);
  const manifest = context.opening.documents.manifest.value;
  const binding = requireSourceSetAdmission(manifest as unknown as AssetManifest);
  closed(binding, ["schemaVersion", "receiptPath", "receiptSha256", "sourceSetDigest", "entryCount"], "source set binding");
  const setPath = path.join(context.producerDir, binding.receiptPath);
  addOriginalFiles(read, sources, setPath); read.check();
  const parents = originalParents(read), entries = sourceSet(read, setPath);
  const rows = sources.map(source => expectation(read, source, sourceEntry(source, entries, context.producerDir)));
  const result = freeze({ scope: "held-source-color-expectations-not-source-observation-or-approval" as const,
    sources: rows, parents, files: [...read.values.values()].map(row => row.ref), assertCurrent: read.check });
  read.check(); return result;
}
