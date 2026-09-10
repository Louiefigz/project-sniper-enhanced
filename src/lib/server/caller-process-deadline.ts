import { AsyncLocalStorage } from "node:async_hooks";

/** Internal caller-owned allowance, not a new clock or request-level policy override. */
export interface CallerProcessDeadline {
  remainingMs: () => number;
  maxChildMs: number;
  signal?: AbortSignal;
}

interface Scope {
  input: CallerProcessDeadline;
  parent?: Scope;
  controller: AbortController;
  previous: number;
  closed: boolean;
  failed: boolean;
}

const active = new AsyncLocalStorage<Scope>();

function positive(value: number): number {
  if (!Number.isSafeInteger(value) || value < 1) throw new Error("Caller process deadline is expired or invalid");
  return value;
}

function observe(scope: Scope): number {
  if (scope.closed || scope.failed) throw new Error("Caller process deadline scope is closed or failed");
  try {
    if (scope.input.signal?.aborted) throw new Error("Caller process deadline was cancelled");
    const remaining = positive(scope.input.remainingMs());
    if (remaining > scope.previous) throw new Error("Caller process deadline cannot regain time");
    scope.previous = remaining;
    return Math.min(remaining, scope.input.maxChildMs);
  } catch (error) { scope.failed = true; scope.controller.abort(error); throw error; }
}

/** Read all live ancestors; neither a nested scope nor an escaped callback grants fresh time. */
export function currentCallerProcessDeadline(): { timeoutMs: number; signal: AbortSignal } | null {
  let scope = active.getStore();
  if (!scope) return null;
  let timeoutMs = Number.MAX_SAFE_INTEGER;
  const signals: AbortSignal[] = [];
  while (scope) {
    timeoutMs = Math.min(timeoutMs, observe(scope));
    signals.push(scope.controller.signal);
    if (scope.input.signal) signals.push(scope.input.signal);
    scope = scope.parent;
  }
  return { timeoutMs, signal: AbortSignal.any(signals) };
}

/** Await actual caller work. Closing cancels escaped children but does not claim their cleanup. */
export async function withCallerProcessDeadline<T>(input: CallerProcessDeadline, run: () => Promise<T>): Promise<T> {
  positive(input.maxChildMs);
  currentCallerProcessDeadline();
  const scope: Scope = { input: { ...input }, parent: active.getStore(), controller: new AbortController(),
    previous: Number.MAX_SAFE_INTEGER, closed: false, failed: false };
  return active.run(scope, async () => {
    try {
      currentCallerProcessDeadline();
      const result = await run();
      currentCallerProcessDeadline();
      return result;
    } finally { scope.closed = true; scope.controller.abort(new Error("Caller process deadline scope closed")); }
  });
}
