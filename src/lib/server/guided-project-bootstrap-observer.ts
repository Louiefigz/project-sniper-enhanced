/** Opt-in lifetime observation over existing owned-group APIs, not another process launcher. */
import { AsyncLocalStorage } from "node:async_hooks";
import type { ChildProcess } from "node:child_process";
import { groupAlive, stopGroup, CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { withTrackedProcessObserver } from "@/app/api/_lib/child-process-lifecycle";

export interface Observation { clean: boolean; forced: boolean }
interface Tracked { child: ChildProcess; observation?: Promise<Observation> }
const activeScope = new AsyncLocalStorage<BootstrapTreeScope>();

async function observe(record: Tracked): Promise<Observation> {
  const pid = record.child.pid;
  // A failed spawn without a PID owns no process group.
  if (!pid) return { clean: true, forced: false };
  try {
    if (!groupAlive(pid)) return { clean: true, forced: false };
    return { clean: await stopGroup(pid), forced: true };
  } catch { return { clean: false, forced: false }; }
}

class BootstrapTreeScope {
  private records: Tracked[] = [];
  private state: "open" | "settling" | "closed" = "open";
  private poisoned = false;
  private persistenceFailed = false;
  constructor(private readonly onLate: () => void) {}
  hadRegisteredWork(): boolean { return this.records.length > 0; }

  track = (child: ChildProcess): void => {
    const record = { child } as Tracked;
    this.records.push(record);
    child.once("close", () => { record.observation ??= observe(record); });
    if (this.state === "open") return;
    this.poisoned = true;
    try { this.onLate(); } catch { this.persistenceFailed = true; }
    // Already-spawned work must be reconciled even though its registration invalidates PAUSE.
    record.observation ??= observe(record);
  };

  async settle(final: boolean): Promise<Observation> {
    if (this.state === "settling") throw new BootstrapCleanupError("Concurrent bootstrap drain", { clean: false, forced: false });
    const reopen = !final && this.state === "open";
    this.state = "settling";
    const results: Observation[] = [];
    let cursor = 0;
    // Registrations during await are poisoned, but every registered child is still observed.
    for (let drain = 0; drain < 4 && cursor < this.records.length; drain += 1) {
      const batch = this.records.slice(cursor); cursor = this.records.length;
      results.push(...await Promise.all(batch.map((record) => record.observation ??= observe(record))));
    }
    this.state = reopen && !this.poisoned ? "open" : "closed";
    return { clean: cursor === this.records.length && !this.persistenceFailed && results.every((row) => row.clean),
      forced: this.poisoned || results.some((row) => row.forced) };
  }

  async guard(final = false): Promise<void> {
    const result = await this.settle(final);
    if (!result.clean || result.forced) throw new BootstrapCleanupError("Existing-cut subprocess quiescence was not clean", result);
  }
}

export class BootstrapCleanupError extends Error {
  constructor(message: string, readonly observation: Observation, readonly original?: unknown,
    readonly nestedUncertain = false) { super(message); }
}

/** Cannot be opted into by a JSON boolean; only the held worker's runtime scope activates it. */
export async function assertBootstrapQuiescent(final = false): Promise<void> {
  const scope = activeScope.getStore();
  if (!scope) throw new Error("Existing-cut review lacks its owned process observation scope");
  await scope.guard(final);
}

export async function withBootstrapProcessScope<T>(run: () => Promise<T>, onLate: () => void): Promise<T> {
  const scope = new BootstrapTreeScope(onLate);
  return activeScope.run(scope, () => withTrackedProcessObserver(scope.track, async () => {
    try {
      const result = await run();
      await scope.guard(true);
      return result;
    } catch (error) {
      const observation = await scope.settle(true);
      // Existing gate verdict conversion can discard nested forced-stop facts. Do not infer those from group absence.
      const uncertain = scope.hadRegisteredWork() && !(error instanceof CutPreviewProcessError);
      if (!observation.clean || observation.forced || uncertain) throw new BootstrapCleanupError(String(error), observation, error, uncertain);
      throw error;
    }
  }));
}
