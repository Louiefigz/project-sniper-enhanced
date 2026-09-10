/** Finite original pending-journal metadata lifetime; no lease, retirement or timer authority. */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { openingAbsolutePath } from "@/lib/producer/contracts/guided-opening-media-v1";
import { fileIdentity, directoryIdentity } from "./guided-source-color-cleanup-attempt-hold";
import { snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";

export interface SourceColorCleanupPendingReadInput { dir: string; guard: () => void; remainingMs: () => number }

/** Preserve Buffer-bearing actual read returns before any subsequent callback or filesystem helper. */
export class CleanupPendingReadHold {
  private readonly original;
  private readonly files = new Map<string, bigint[]>();
  private readonly parents = new Map<string, bigint[]>();
  private readonly returns: { value: unknown; fixed: unknown }[] = [];
  private budget: { started: number; remaining: number } | undefined;
  private awaitingCapture = false;
  constructor(readonly input: SourceColorCleanupPendingReadInput) {
    this.original = { ...input }; openingAbsolutePath(input.dir);
  }
  private capture(file: string): void {
    openingAbsolutePath(file);
    const previous = this.files.get(file), actual = fileIdentity(file);
    if (previous && !isDeepStrictEqual(previous, actual)) throw new Error("Cleanup pending original file changed before read");
    this.files.set(file, actual);
    for (let directory = path.dirname(file);;) {
      const identity = directoryIdentity(directory), prior = this.parents.get(directory);
      if (prior && !isDeepStrictEqual(prior, identity)) throw new Error("Cleanup pending original parent changed before read");
      this.parents.set(directory, identity);
      const parent = path.dirname(directory); if (parent === directory) break;
      directory = parent;
    }
  }
  /** Actual bounded reader remains responsible for raw SHA/schema; capture its exact return immediately. */
  observe<T>(file: string, read: () => T): T {
    this.capture(file); this.metadata(); const value = read();
    this.returns.push({ value, fixed: snapshotSourceColorMetadata(value) }); this.metadata(); return value;
  }
  /** Retain original parsed reader output without freezing the reader's own objects or Buffer. */
  retain<T>(read: () => T): T {
    this.metadata(); const value = read(); this.returns.push({ value, fixed: snapshotSourceColorMetadata(value) });
    this.metadata(); return value;
  }
  /** Finite callback-free sweep only. The caller separately owns protected clock and any resource lease. */
  metadata = (): void => {
    if (this.input.dir !== this.original.dir || this.input.guard !== this.original.guard || this.input.remainingMs !== this.original.remainingMs) {
      throw new Error("Cleanup pending original caller identity changed");
    }
    for (const [file, identity] of this.files) {
      if (!isDeepStrictEqual(fileIdentity(file), identity)) throw new Error("Cleanup pending original file identity changed");
    }
    for (const [directory, identity] of this.parents) {
      if (!isDeepStrictEqual(directoryIdentity(directory), identity)) throw new Error("Cleanup pending original parent identity changed");
    }
    for (const row of this.returns) {
      if (!isDeepStrictEqual(row.value, row.fixed)) throw new Error("Cleanup pending original returned metadata changed");
    }
  };
  remaining = (): number => {
    if (!this.budget) throw new Error("Cleanup pending read has no original active remainder");
    const elapsed = performance.now() - this.budget.started, remaining = this.budget.remaining - elapsed;
    if (!Number.isFinite(elapsed) || elapsed < 0 || remaining <= 0) throw new Error("Cleanup pending original protected deadline expired");
    return remaining;
  };
  check = (): void => { this.metadata(); this.remaining(); };
  private admit(): void {
    this.budget = { started: performance.now(), remaining: 0 };
    this.original.guard(); const remaining = this.original.remainingMs();
    if (!Number.isFinite(remaining) || remaining <= 0 || remaining > 300_000) throw new Error("Cleanup pending protected remainder is invalid");
    this.budget.remaining = remaining; this.check();
  }
  /** Actual child invokes this only after capturing its own records/media; never grants an independent lifetime. */
  enterAfterCapture = (): void => {
    if (this.budget) { this.check(); return; }
    if (!this.awaitingCapture) throw new Error("Cleanup pending child has no original active capture lifetime");
    this.metadata(); this.admit();
  };
  /** Defer caller admission until the actual child has captured its complete original record inventory. */
  runAfterCapture<T>(operation: () => T): T {
    if (this.budget || this.awaitingCapture) throw new Error("Cleanup pending read cannot reenter its original lifetime");
    this.metadata(); this.awaitingCapture = true;
    try { const result = operation(); this.check(); return result; }
    finally { this.awaitingCapture = false; this.budget = undefined; }
  }
  /** Reuses the original callback; nested readers receive the already-active finite remainder, not a fresh clock. */
  run<T>(operation: () => T): T {
    if (this.budget || this.awaitingCapture) throw new Error("Cleanup pending read cannot reenter its original lifetime");
    this.metadata();
    try {
      this.admit(); const result = operation(); this.check(); return result;
    } finally { this.budget = undefined; }
  }
}
