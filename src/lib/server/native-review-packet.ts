/** Role packets from `context.py --role`: frozen instructions/artifacts, canonical paths and safe publication. */
import { createHash, randomUUID } from "node:crypto";
import { closeSync, constants, fstatSync, fsyncSync, linkSync, lstatSync, openSync, readSync, realpathSync,
  rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { assertCutPreviewDirectory, observeCutPreviewFile, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { objectValue, sha256, stringValue, type JsonRecord } from "@/lib/producer/contracts/validation";

export type NativeReviewRole = "plan-critic" | "motion-critic" | "final-critic";
const MEDIA_LIMIT = 4 * 1024 ** 3;
const STRICT_LIMIT = 256 * 1024 ** 2;
/** A staged native project or an export/preview attempt; review records never land inside one. */
const WORK_MARKERS = ["SHORT-PROJECT.json", "LONG-PROJECT.json", "PROJECT-MANIFEST.json", "export-request.json"];

export interface FrozenFile { key: string; path: string; sha256: string; observation: "strict" | "linked-media" }
/** Large media listed by the hash its receipt declares; the builder/exporter verifies those bytes. */
export interface DeclaredMedia { key: string; path: string; sha256: string }
export interface RolePacket {
  role: NativeReviewRole; path: string; sha256: string; authorSessionIds: string[]; resolvedAt: string;
  repository: string; subject: JsonRecord; artifacts: FrozenFile[]; instructions: FrozenFile[]; declaredMedia: DeclaredMedia[];
  /** Shared source evidence summary (unit B1); null when none is bound. */
  sharedEvidence: JsonRecord | null;
  /** The operator's given title/script and the engine's facts about the subject (unit B1); null when none is bound. */
  given: JsonRecord | null;
}

/** Engine roots whose pinned files feed the preview implementation digest (native_review_regions.region_packet). */
export function engineRoots(packet: RolePacket): string[] {
  const repositories = [...new Set([packet.repository, path.resolve(__dirname, "..", "..", "..")])];
  return repositories.flatMap(root => ["scripts", "src", "schemas", "templates/motion/.sniper-native-runtime"]
    .map(name => path.join(root, name)));
}

function lexists(file: string): boolean {
  try { lstatSync(file); return true; } catch { return false; }
}

/** Canonical real path of an existing input; symlinked ancestors such as /var resolve to /private/var. */
export function canonicalInput(file: string, label: string): string {
  if (!file || /[\0\r\n]/u.test(file)) throw new Error(`${label} path is invalid`);
  try { return realpathSync(path.resolve(file)); } catch {
    throw new Error(`${label} does not exist: ${path.resolve(file)}`);
  }
}

function subjectDirectories(subject: JsonRecord | undefined): string[] {
  if (!subject) return [];
  const exported = subject.export as JsonRecord | undefined, preview = subject.preview as JsonRecord | undefined;
  return [typeof subject.project === "string" ? subject.project : null,
    exported && typeof exported.directory === "string" ? exported.directory : null,
    preview && typeof preview.path === "string" ? path.dirname(preview.path) : null].filter((row): row is string => Boolean(row));
}

/** Refuse an output inside the subject's project or attempts, or inside any staged project/attempt directory. */
export function assertOutsideStagedWork(output: string, label: string, subject?: JsonRecord): void {
  const named = subjectDirectories(subject);
  for (let directory = path.dirname(output); ; directory = path.dirname(directory)) {
    if (named.includes(directory) || WORK_MARKERS.some(name => lexists(path.join(directory, name)))) {
      throw new Error(`${label} must stay outside the staged project or attempt ${directory}`);
    }
    if (path.dirname(directory) === directory) return;
  }
}

/** New output under its canonical real directory; an existing name (even a dangling link) is refused. */
export function canonicalOutput(file: string, label: string, subject?: JsonRecord): string {
  if (!file || /[\0\r\n]/u.test(file)) throw new Error(`${label} path is invalid`);
  const absolute = path.resolve(file);
  let directory: string;
  try { directory = realpathSync(path.dirname(absolute)); } catch {
    throw new Error(`${label} directory does not exist: ${path.dirname(absolute)}`);
  }
  assertCutPreviewDirectory(directory);
  const output = path.join(directory, path.basename(absolute));
  if (lexists(output)) throw new Error(`${label} already exists; records are never overwritten: ${output}`);
  assertOutsideStagedWork(output, label, subject);
  return output;
}

/** Hash delivered media that a handoff may have hard-linked; identity must stay stable while reading. */
export function observeLinkedMedia(file: string): { sha256: string; sizeBytes: number; links: number } {
  assertCutPreviewDirectory(path.dirname(file));
  const descriptor = openSync(file, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = fstatSync(descriptor, { bigint: true });
    if (!before.isFile() || before.size < BigInt(1) || before.size > BigInt(MEDIA_LIMIT)) throw new Error(`Delivered media is not bounded regular media: ${file}`);
    const hash = createHash("sha256"), buffer = Buffer.alloc(1024 * 1024);
    for (let remaining = Number(before.size); remaining > 0;) {
      const count = readSync(descriptor, buffer, 0, Math.min(remaining, buffer.length), null);
      if (!count) throw new Error(`Delivered media was truncated during observation: ${file}`);
      hash.update(buffer.subarray(0, count)); remaining -= count;
    }
    const after = lstatSync(file, { bigint: true });
    for (const field of ["dev", "ino", "size", "mtimeNs", "ctimeNs"] as const)
      if (before[field] !== after[field]) throw new Error(`Delivered media changed during observation: ${file}`);
    return { sha256: hash.digest("hex"), sizeBytes: Number(before.size), links: Number(before.nlink) };
  } finally { closeSync(descriptor); }
}

function frozenRows(value: unknown, label: string): FrozenFile[] {
  if (!Array.isArray(value) || !value.length || value.length > 4096) throw new Error(`Role packet ${label} are invalid`);
  return value.map((item, index) => {
    const row = objectValue(item, `role packet ${label}[${index}]`);
    const observation = row.observation === "linked-media" ? "linked-media" : "strict";
    const file = stringValue(row.path, `role packet ${label} path`, 4096);
    if (!path.isAbsolute(file) || path.resolve(file) !== file) throw new Error(`Role packet ${label} path is not canonical: ${file}`);
    return { key: typeof row.key === "string" ? row.key : path.basename(file), path: file,
      sha256: sha256(row.sha256, `role packet ${label} hash`), observation };
  });
}

function declaredRows(value: unknown): DeclaredMedia[] {
  if (!Array.isArray(value) || value.length > 4096) throw new Error("Role packet declaredMedia are invalid");
  return value.map((item, index) => {
    const row = objectValue(item, `role packet declaredMedia[${index}]`), file = stringValue(row.path, "declared media path", 4096);
    if (!path.isAbsolute(file) || path.resolve(file) !== file) throw new Error(`Role packet declared media path is not canonical: ${file}`);
    return { key: stringValue(row.key, "declared media key", 256), path: file,
      sha256: sha256(row.declaredSha256, "role packet declared media hash") };
  });
}

/** Read a packet for exactly one role under the shared no-follow, single-link artifact rule. */
export function readRolePacket(file: string, role: NativeReviewRole): RolePacket {
  const canonical = canonicalInput(file, "Role packet"), observed = readCutPreviewObject(canonical);
  const value = objectValue(observed.value, "role packet");
  if (value.schemaVersion !== 1 || value.kind !== "sniper-role-packet" || value.route !== "native-short") {
    throw new Error("Role packet is not a native-short sniper-role-packet v1");
  }
  if (value.role !== role) throw new Error(`Role packet is for ${String(value.role)}, not ${role}`);
  const authors = value.authorSessionIds;
  if (!Array.isArray(authors) || authors.some(name => typeof name !== "string" || !name.trim())) throw new Error("Role packet author identities are invalid");
  const resolvedAt = stringValue(value.resolvedAt, "role packet resolvedAt", 64);
  if (!Number.isFinite(Date.parse(resolvedAt))) throw new Error("Role packet resolvedAt is not a timestamp");
  const repository = stringValue(value.repository, "role packet repository", 4096);
  if (!path.isAbsolute(repository)) throw new Error("Role packet repository must be an absolute path");
  return { role, path: canonical, sha256: observed.sha256, authorSessionIds: authors as string[], resolvedAt, repository,
    subject: objectValue(value.subject, "role packet subject"),
    artifacts: frozenRows(value.artifacts, "artifacts"), instructions: frozenRows(value.instructions, "instructions"),
    declaredMedia: declaredRows(value.declaredMedia),
    sharedEvidence: value.sharedEvidence == null ? null : objectValue(value.sharedEvidence, "role packet sharedEvidence"),
    given: value.given == null ? null : objectValue(value.given, "role packet given") };
}

function currentHash(row: FrozenFile): string {
  try {
    return row.observation === "linked-media" ? observeLinkedMedia(row.path).sha256 : observeCutPreviewFile(row.path, STRICT_LIMIT).sha256;
  } catch (error) { return `unreadable (${error instanceof Error ? error.message : String(error)})`; }
}

/** Refuse when anything the critic was given changed since the packet was resolved; list every change. */
export function assertPacketCurrent(packet: RolePacket): void {
  const stale = [...packet.instructions, ...packet.artifacts].flatMap(row => {
    const now = currentHash(row);
    return now === row.sha256 ? [] : [`${row.key} ${row.path}: frozen ${row.sha256.slice(0, 12)}, now ${now.slice(0, 80)}`];
  });
  if (stale.length) {
    throw new Error(`Stale review inputs: ${stale.length} file(s) changed since the role packet was resolved; `
      + `re-resolve the packet and re-check the affected media. ${stale.slice(0, 12).join("; ")}`);
  }
}

/** The frozen row for one packet-listed path; the helper binds only what the critic was given. */
export function frozenArtifact(packet: RolePacket, file: string): FrozenFile {
  const row = packet.artifacts.find(item => item.path === file);
  if (!row) throw new Error(`Role packet does not freeze ${file}`);
  return row;
}

function fsyncDirectory(directory: string): void {
  const descriptor = openSync(directory, "r");
  try { fsyncSync(descriptor); } finally { closeSync(descriptor); }
}

/** Write a candidate beside the output, gate it with the real reader, then link it into place. */
export function publishValidatedJson<T>(output: string, value: unknown,
  validate: (candidate: string, digest: string) => T): { path: string; sha256: string; gate: T } {
  const bytes = Buffer.from(`${JSON.stringify(value, null, 2)}\n`), digest = createHash("sha256").update(bytes).digest("hex");
  const candidate = path.join(path.dirname(output), `.${path.basename(output)}.${process.pid}.${randomUUID()}.candidate`);
  let descriptor: number | undefined;
  try {
    descriptor = openSync(candidate, "wx", 0o644);
    writeFileSync(descriptor, bytes); fsyncSync(descriptor); closeSync(descriptor); descriptor = undefined;
    const gate = validate(candidate, digest);
    linkSync(candidate, output);
    fsyncDirectory(path.dirname(output));
    return { path: output, sha256: digest, gate };
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
    rmSync(candidate, { force: true });
  }
}

/** Wall-clock span from packet resolution to submission: the critic's inspection and writing time,
 * reported separately from the helper's own serialization timings (telemetry, not a gate). */
export function reviewSpan(packet: RolePacket) {
  const submittedAt = new Date();
  return { packetResolvedAt: packet.resolvedAt, submittedAt: submittedAt.toISOString(),
    packetToSubmissionSeconds: Math.round((submittedAt.getTime() - Date.parse(packet.resolvedAt)) / 100) / 10 };
}

/** Monotonic phase timings for the submission report. */
export function stopwatch() {
  const start = performance.now(), marks: Record<string, number> = {};
  let last = start;
  return { mark(name: string) { const now = performance.now(); marks[name] = Math.round(now - last); last = now; },
    report() { return { ...marks, totalMs: Math.round(performance.now() - start) }; } };
}
