import { lstatSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";

/** The Python process runner (headless/process_runner.py) appends a row for every child it starts in a NEW session
 * when this environment variable names the ledger: `intent` before the fork, `spawned` with the pid, `reaped` after.
 * Those sessions sit outside the controller's owned process group, so after an external kill of the worker they are
 * the only exact record of what may still be running. Each child invocation kind gets its own ledger file. */
export const OWNED_PROCESS_LEDGER_ENV = "SNIPER_OWNED_PROCESS_LEDGER";
export type OwnedLedgerKind = "media" | "cleanup" | "read";
const MAX_ROWS = 100_000;
const MAX_BYTES = 32 * 1024 * 1024;
/** A child can never have started earlier than the worker recorded spawning it (beyond clock skew). */
const OLDER_THAN_SPAWN_S = 60;

export interface OwnedProcessRow { event: "intent" | "spawned" | "reaped" | "worker-started" | "worker-finished"; pid: number | null; argv0: string; at: number }
export interface LiveDescendant { pid: number; argv0: string; recordedAt: number }
export interface UnknownDescendant { pid: number; argv0: string; reason: string }
export interface DescendantObservation { live: LiveDescendant[]; unknown: UnknownDescendant[]; unrecordedSpawns: string[] }
/** Three-state liveness of ONE pid. "unknown" (probe failure, timeout, unparseable output) is never absence:
 * an unresolved observation must keep ownership, exactly like a live child would. */
export type ProcessObservation = { state: "running"; elapsedS: number; command: string } | { state: "absent" } | { state: "unknown"; reason: string };
export type ProcessProbe = (pid: number) => ProcessObservation;

export function ownedProcessLedgerPath(root: string, kind: OwnedLedgerKind): string {
  return path.join(root, `owned-process-ledger.${kind}.jsonl`);
}

function parseRow(line: string): OwnedProcessRow {
  let row: Record<string, unknown>;
  try { row = JSON.parse(line) as Record<string, unknown>; } catch { throw new Error("owned process ledger row is torn"); }
  const event = row?.event;
  const pidOk = event === "intent" ? row.pid === null : Number.isSafeInteger(row.pid) && Number(row.pid) > 0;
  if (!row || typeof row !== "object" || !["intent", "spawned", "reaped", "worker-started", "worker-finished"].includes(String(event)) || !pidOk
      || typeof row.argv0 !== "string" || !path.isAbsolute(row.argv0) || typeof row.at !== "number" || !Number.isFinite(row.at)) {
    throw new Error("owned process ledger row is malformed");
  }
  return { event: event as OwnedProcessRow["event"], pid: event === "intent" ? null : Number(row.pid), argv0: row.argv0, at: row.at };
}

/** Missing media evidence cannot prove no child started; preserve ownership even before the first recorded spawn. */
export function readOwnedProcessLedger(root: string, kind: OwnedLedgerKind): OwnedProcessRow[] {
  const file = ownedProcessLedgerPath(root, kind);
  try { lstatSync(file); } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT" && kind !== "media") return [];
    if ((error as NodeJS.ErrnoException).code === "ENOENT") throw new Error("Opening media process ledger is missing; nested ownership is unproved and requires manual recovery");
    throw error;
  }
  const bytes = observeCutPreviewFile(file, MAX_BYTES, true).bytes;
  const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  if (!text.endsWith("\n")) throw new Error("owned process ledger has an incomplete final row");
  const lines = text.slice(0, -1).split("\n");
  if (lines.length > MAX_ROWS || lines.some((line) => !line)) throw new Error("owned process ledger row bounds are invalid");
  const rows = lines.map(parseRow);
  if (rows.some((row) => row.event.startsWith("worker-"))) assertWorkerLifecycle(rows, rows[0].argv0);
  return rows;
}

function assertWorkerLifecycle(rows: OwnedProcessRow[], script: string): void {
  const first = rows[0], last = rows.at(-1);
  if (rows.length < 2 || first.event !== "worker-started" || last?.event !== "worker-finished"
      || first.pid !== last.pid || first.argv0 !== script || last.argv0 !== script
      || rows.slice(1, -1).some((row) => row.event.startsWith("worker-"))
      || rows.some((row, index) => row.at <= 0 || (index > 0 && row.at < rows[index - 1].at))) {
    throw new Error("Opening owned worker lifecycle is missing, incomplete or changed");
  }
  const balance = new Map<string, number>();
  for (const row of rows) {
    if (row.event === "intent") balance.set(row.argv0, (balance.get(row.argv0) ?? 0) + 1);
    if (row.event === "spawned") balance.set(row.argv0, (balance.get(row.argv0) ?? 0) - 1);
    if ((balance.get(row.argv0) ?? 0) < 0) throw new Error("Opening worker ledger spawned without a prior intent");
  }
}

/** A real new-only wrapper lifecycle, separately byte-bound by the actual owned outcome, permits zero helper calls. */
export function observeOwnedWorkerLedger(root: string, kind: OwnedLedgerKind, script: string, expectedSha256?: string): string {
  const file = ownedProcessLedgerPath(root, kind), before = observeCutPreviewFile(file, MAX_BYTES, true);
  if (expectedSha256 && before.sha256 !== expectedSha256) throw new Error("Opening returned process ledger bytes changed");
  assertWorkerLifecycle(readOwnedProcessLedger(root, kind), script);
  if (observeCutPreviewFile(file, MAX_BYTES).sha256 !== before.sha256) throw new Error("Opening returned process ledger bytes changed");
  return before.sha256;
}

/** A reap closes only its exact earlier spawn, never a mismatched or out-of-order row. */
export function unreapedRows(rows: OwnedProcessRow[]): OwnedProcessRow[] {
  const open = new Map<number, OwnedProcessRow>();
  for (const row of rows) {
    if (row.event === "intent" || row.event.startsWith("worker-")) continue;
    const prior = open.get(row.pid!);
    if (row.event === "spawned" && prior) throw new Error("owned process ledger repeats an unreaped pid");
    if (row.event === "reaped" && (!prior || row.argv0 !== prior.argv0 || row.at < prior.at)) throw new Error("owned process ledger reap does not match its earlier spawn");
    if (row.event === "spawned") open.set(row.pid!, row);
    if (row.event === "reaped") open.delete(row.pid!);
  }
  return [...open.values()];
}

/** Programs with more intents than spawned rows: a child may exist whose pid was never recorded. */
export function unrecordedSpawns(rows: OwnedProcessRow[]): string[] {
  const balance = new Map<string, number>();
  for (const row of rows) {
    if (row.event === "intent") balance.set(row.argv0, (balance.get(row.argv0) ?? 0) + 1);
    if (row.event === "spawned") balance.set(row.argv0, (balance.get(row.argv0) ?? 0) - 1);
  }
  return [...balance].filter(([, count]) => count > 0).map(([argv0]) => argv0);
}

/** ps(1) etime: [[dd-]hh:]mm:ss → seconds. */
export function parseEtime(text: string): number {
  const match = /^(?:(\d+)-)?(?:(\d{1,2}):)?(\d{1,2}):(\d{2})$/.exec(text.trim());
  if (!match) throw new Error(`unparseable process elapsed time ${JSON.stringify(text)}`);
  const [days, hours, minutes, seconds] = [match[1], match[2], match[3], match[4]].map((part) => Number(part ?? 0));
  const total = ((days * 24 + hours) * 60 + minutes) * 60 + seconds;
  if (hours > 23 || minutes > 59 || seconds > 59 || !Number.isSafeInteger(total)) throw new Error("process elapsed fields are invalid");
  return total;
}

/** A ps no-match alone can be an observation failure; signal 0 observes existence without signalling the process. */
function confirmAbsent(pid: number): ProcessObservation {
  try { process.kill(pid, 0); } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ESRCH") return { state: "absent" };
    return { state: "unknown", reason: `process absence could not be confirmed: ${String(error)}` };
  }
  return { state: "unknown", reason: "ps returned no row but the recorded pid still exists" };
}

function psProbe(pid: number): ProcessObservation {
  const result = spawnSync("/bin/ps", ["-p", String(pid), "-o", "etime=,args="], { encoding: "utf8", timeout: 5_000 });
  if (result.error) return { state: "unknown", reason: `ps did not run: ${result.error.message}` };
  const line = (result.stdout ?? "").trim();
  if (result.signal || (result.stderr ?? "").trim()) return { state: "unknown", reason: "ps was interrupted or reported a diagnostic" };
  if (result.status === 1 && !line) return confirmAbsent(pid);
  if (result.status !== 0 || !line) return { state: "unknown", reason: `ps exited ${result.status ?? "by signal"} without a row` };
  const match = /^(\S+)[ \t]+([^\r\n]+)$/.exec(line);
  if (!match) return { state: "unknown", reason: "ps did not return exactly one elapsed-time and command row" };
  try { return { state: "running", elapsedS: parseEtime(match[1]), command: match[2] }; }
  catch (error) { return { state: "unknown", reason: String(error) }; }
}

/** Boundary-safe argv[0] match: paths may contain spaces, so compare the whole recorded argv[0] plus a separator. */
function sameProgram(command: string, argv0: string): boolean {
  return command === argv0 || command.startsWith(`${argv0} `);
}

function observePid(row: OwnedProcessRow, probe: ProcessProbe, nowS: number): ProcessObservation {
  try {
    const observed = probe(row.pid!);
    if (observed?.state === "absent") return observed;
    if (observed?.state === "unknown" && typeof observed.reason === "string" && observed.reason) return observed;
    if (observed?.state !== "running" || !Number.isSafeInteger(observed.elapsedS) || observed.elapsedS < 0
        || typeof observed.command !== "string" || !observed.command || /[\r\n]/.test(observed.command)) {
      return { state: "unknown", reason: "process probe returned malformed evidence" };
    }
    if (!sameProgram(observed.command, row.argv0) || !Number.isFinite(nowS) || nowS - observed.elapsedS < row.at - OLDER_THAN_SPAWN_S) {
      return { state: "unknown", reason: "recorded process identity or start clock cannot be corroborated" };
    }
    return observed;
  } catch (error) { return { state: "unknown", reason: `process observation threw: ${String(error).slice(0, 2000)}` }; }
}

/** An exec/clock mismatch is not proof a recorded process disappeared. Only explicit absence clears that pid. */
export function liveRecordedDescendants(root: string, kind: OwnedLedgerKind, probe: ProcessProbe = psProbe,
  nowS = Date.now() / 1000): DescendantObservation {
  const rows = readOwnedProcessLedger(root, kind);
  const live: LiveDescendant[] = [], unknown: UnknownDescendant[] = [];
  for (const row of unreapedRows(rows)) {
    const observed = observePid(row, probe, nowS);
    if (observed.state === "unknown") { unknown.push({ pid: row.pid!, argv0: row.argv0, reason: observed.reason }); continue; }
    if (observed.state === "absent") continue;
    live.push({ pid: row.pid!, argv0: row.argv0, recordedAt: row.at });
  }
  return { live, unknown, unrecordedSpawns: unrecordedSpawns(rows) };
}
