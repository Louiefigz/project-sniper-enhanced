/** Fresh bounded scheduling history; not a lease, clock, launch or approval capability. */
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { exactKeys, objectValue, sha256, uuid } from "@/lib/producer/contracts/validation";
import { canonicalJson, canonicalJsonSha256 } from "./auto-edit-hash";

const LIMIT = 512, MAXIMUM = 64 * 1024;
const KEYS = ["schemaVersion", "kind", "clockHash", "generationStartedAt", "executionId", "observedAt"];
type Origin = { clockHash: string; startedAt: string };
type Identity = bigint[];
interface Entry { name: string; identity: Identity; value?: Record<string, unknown> }
interface State {
  directory: string; origin: Origin; entries: Entry[];
  ancestry: Array<[string, ...bigint[]]>; temporary?: { name: string; identity: Identity };
}
export interface HeldGenerationClockHistory {
  readonly highWater: string; readonly names: readonly string[];
  assertCurrent(ignoreTemp?: string): void;
  observedAtForExecution(executionId: string): string | undefined;
}
const histories = new WeakMap<HeldGenerationClockHistory, State>();

function stamp(value: unknown): string {
  if (typeof value !== "string" || !Number.isSafeInteger(Date.parse(value)) || new Date(value).toISOString() !== value) {
    throw new Error("Generation clock observation is malformed");
  }
  return value;
}
function statIdentity(row: fs.BigIntStats): Identity {
  if (!row.isFile() || row.nlink !== BigInt(1)) throw new Error("Generation clock history requires a single-link regular file");
  return [row.dev, row.ino, row.mode, row.uid, row.gid, row.nlink, row.size, row.mtimeNs, row.ctimeNs];
}
function fileIdentity(file: string): Identity { return statIdentity(fs.lstatSync(file, { bigint: true })); }
function ancestry(directory: string): State["ancestry"] {
  if (!path.isAbsolute(directory) || path.resolve(directory) !== directory || fs.realpathSync(directory) !== directory) {
    throw new Error("Generation clock history directory is not canonical");
  }
  const result: State["ancestry"] = [];
  for (;;) {
    const row = fs.lstatSync(directory, { bigint: true });
    if (!row.isDirectory()) throw new Error("Generation clock history parent is not a directory");
    result.push([directory, row.dev, row.ino, row.mode, row.uid, row.gid]);
    const parent = path.dirname(directory); if (parent === directory) return result;
    directory = parent;
  }
}
function record(value: unknown, origin: Origin): Record<string, unknown> {
  const row = objectValue(value, "generation clock history"), rolling = row.schemaVersion === 2;
  exactKeys(row, rolling ? [...KEYS, "watermarkHash"] : KEYS, rolling ? [...KEYS, "watermarkHash"] : KEYS, "generation clock history");
  uuid(row.executionId, "executionId"); const at = stamp(row.observedAt);
  if (row.schemaVersion !== (rolling ? 2 : 1) || row.kind !== (rolling ? "generation-wall-clock-watermark" : "generation-wall-clock-observation")
      || row.clockHash !== origin.clockHash || row.generationStartedAt !== origin.startedAt || at < origin.startedAt) {
    throw new Error("Generation clock history changed or belongs to another original request");
  }
  if (rolling) {
    const { watermarkHash, ...body } = row;
    if (sha256(watermarkHash, "watermarkHash") !== canonicalJsonSha256(body)) throw new Error("Generation watermark hash changed");
  }
  return row;
}
function entryName(row: Record<string, unknown>): string {
  return `${row.schemaVersion === 1 ? canonicalJsonSha256(row) : row.executionId}.json`;
}
function readEntry(state: State, entry: Entry): Record<string, unknown> {
  const observed = observeCutPreviewFile(path.join(state.directory, entry.name), MAXIMUM, true);
  const row = record(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes)), state.origin);
  if (entryName(row) !== entry.name || canonicalJsonSha256(row) !== observed.sha256) throw new Error("Generation history raw bytes/name are not canonical");
  if (!isDeepStrictEqual(fileIdentity(path.join(state.directory, entry.name)), entry.identity)) throw new Error("Generation history file changed during read");
  return row;
}
function assertState(state: State, entries: Entry[], ignoreTemp?: string): void {
  if (ignoreTemp !== undefined && (ignoreTemp !== state.temporary?.name
      || !isDeepStrictEqual(fileIdentity(path.join(state.directory, ignoreTemp)), state.temporary.identity))) {
    throw new Error("Generation clock history cannot ignore an unowned temporary file");
  }
  const names = fs.readdirSync(state.directory).filter(name => name !== ignoreTemp).sort();
  if (!isDeepStrictEqual(names, entries.map(row => row.name).sort()) || !isDeepStrictEqual(ancestry(state.directory), state.ancestry)) {
    throw new Error("Generation clock history entry set or ancestry changed");
  }
  for (const entry of entries) {
    if (!isDeepStrictEqual(fileIdentity(path.join(state.directory, entry.name)), entry.identity)) throw new Error("Generation clock history file changed");
  }
}

/** Read EVERY current record on every call; no cross-checkpoint or cross-execution cache. */
export function readGenerationClockHistory(directory: string, origin: Origin): HeldGenerationClockHistory {
  const fixed = Object.freeze({ clockHash: sha256(origin.clockHash, "clockHash"), startedAt: stamp(origin.startedAt) });
  const parents = ancestry(directory), names = fs.readdirSync(directory).sort();
  if (names.length > LIMIT) throw new Error("Generation clock history exceeds its read budget");
  const entries = names.map(name => {
    if (!/^(?:[0-9a-f]{64}|[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\.json$/u.test(name)) {
      throw new Error("Generation clock history contains an unknown file");
    }
    return { name, identity: fileIdentity(path.join(directory, name)) } as Entry;
  });
  const state: State = { directory, origin: fixed, entries, ancestry: parents };
  entries.forEach(entry => { entry.value = Object.freeze(readEntry(state, entry)); });
  assertState(state, entries);
  if (!isDeepStrictEqual(origin, fixed)) throw new Error("Generation history original origin changed during read");
  const highWater = entries.reduce((at, row) => String(row.value!.observedAt) > at ? String(row.value!.observedAt) : at, fixed.startedAt);
  const result: HeldGenerationClockHistory = Object.freeze({ highWater, names: Object.freeze([...names]),
    assertCurrent: (ignoreTemp?: string) => assertState(state, entries, ignoreTemp),
    observedAtForExecution: (executionId: string) => {
      uuid(executionId, "executionId");
      return entries.find(row => row.name === `${executionId}.json`)?.value?.observedAt as string | undefined;
    } });
  histories.set(result, state); return result;
}

function writeAll(fd: number, bytes: Buffer): void {
  let offset = 0;
  while (offset < bytes.length) {
    const count = fs.writeSync(fd, bytes, offset, bytes.length - offset);
    if (count <= 0) throw new Error("Generation watermark temporary write was short");
    offset += count;
  }
}
function writeTemporary(state: State, bytes: Buffer): void {
  const name = `.generation-watermark-${randomUUID()}.tmp`, file = path.join(state.directory, name);
  const fd = fs.openSync(file, fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_WRONLY | fs.constants.O_NOFOLLOW, 0o600);
  try {
    state.temporary = { name, identity: statIdentity(fs.fstatSync(fd, { bigint: true })) };
    if (!isDeepStrictEqual(fileIdentity(file), state.temporary.identity)) throw new Error("Generation watermark temporary path changed");
    writeAll(fd, bytes); fs.fsyncSync(fd);
    const current = statIdentity(fs.fstatSync(fd, { bigint: true })), identity = fileIdentity(file);
    if (!isDeepStrictEqual(identity, current)) throw new Error("Generation watermark temporary path changed");
    state.temporary.identity = identity;
  } finally { fs.closeSync(fd); }
}
function removeTemporary(state: State): void {
  const held = state.temporary; if (!held) return;
  const file = path.join(state.directory, held.name);
  let row: fs.BigIntStats;
  try { row = fs.lstatSync(file, { bigint: true }); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return; throw error; }
  if (!row.isFile() || row.dev !== held.identity[0] || row.ino !== held.identity[1] || row.uid !== held.identity[3]) {
    throw new Error("Generation watermark temporary ownership changed; retained");
  }
  fs.unlinkSync(file);
}
function finishTemporary(state: State, failure: unknown[]): void {
  try { removeTemporary(state); }
  catch (cleanupError) {
    if (failure.length) throw new AggregateError([...failure, cleanupError], "Generation watermark failure retained; temporary cleanup uncertain");
    throw cleanupError;
  } finally { state.temporary = undefined; }
}
function syncDirectory(directory: string): void {
  const fd = fs.openSync(directory, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  try { fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
}
function publish(state: State, name: string): Entry[] {
  const temporary = path.join(state.directory, state.temporary!.name), target = path.join(state.directory, name);
  if (state.entries.some(row => row.name === name)) fs.renameSync(temporary, target);
  else fs.linkSync(temporary, target);
  removeTemporary(state); syncDirectory(state.directory);
  return [...state.entries.filter(row => row.name !== name), { name, identity: fileIdentity(target) }];
}

/** The actual enclosing project lease serializes writers, not a lock-free filesystem CAS.
 * Replace only this execution's schema2 record. Advanced records survive postwrite
 * failures; old schema1 observations are never replaced or deleted.
 */
export function publishGenerationClockWatermark(history: HeldGenerationClockHistory, value: unknown, guard: () => void): void {
  const state = histories.get(history); if (!state) throw new Error("Generation history lacks its original live read");
  const fixed = Object.freeze({ ...record(value, state.origin) }), name = entryName(fixed), bytes = Buffer.from(canonicalJson(fixed));
  if (fixed.schemaVersion !== 2 || String(fixed.observedAt) < history.highWater || bytes.length > MAXIMUM) throw new Error("Generation watermark cannot move backwards or change class");
  if (!state.entries.some(row => row.name === name) && state.entries.length === LIMIT) throw new Error("Generation clock history capacity exhausted; no automatic reset");
  const unchanged = () => { if (!isDeepStrictEqual(value, fixed)) throw new Error("Generation watermark original value changed"); };
  const failure: unknown[] = [];
  try {
    unchanged(); history.assertCurrent(); writeTemporary(state, bytes);
    guard(); unchanged(); history.assertCurrent(state.temporary!.name);
    const entries = publish(state, name);
    guard(); unchanged(); assertState(state, entries);
    const published = entries.find(row => row.name === name)!;
    if (!isDeepStrictEqual(readEntry(state, published), fixed)) throw new Error("Generation watermark published bytes differ");
    assertState(state, entries);
  } catch (error) { failure.push(error); throw error; }
  finally { finishTemporary(state, failure); }
}
