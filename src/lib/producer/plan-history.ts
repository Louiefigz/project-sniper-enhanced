// Two-stack undo/redo over the editor's in-memory plan. Pure functions —
// editor-view holds ONE `History<EditPlan>` state and applies these, so the
// transitions are unit-testable and StrictMode-safe (no side effects in
// updaters). Contract: a new mutation clears redo; a base rebuild clears both
// (undo snapshots are only valid against the base they were taken on).
import type { EditPlan } from "./edit-plan";

export interface History<T> {
  past: T[];
  future: T[];
}

export function emptyHistory<T>(): History<T> {
  return { past: [], future: [] };
}

/** A new mutation: push the pre-edit state onto past (bounded), clear redo. */
export function recordEdit<T>(h: History<T>, current: T, limit: number): History<T> {
  return { past: [...h.past.slice(-(limit - 1)), current], future: [] };
}

/** Undo: move `current` onto future, restore the last past state. */
export function undoStep<T>(h: History<T>, current: T): { history: History<T>; plan: T } | null {
  if (!h.past.length) return null;
  return {
    history: { past: h.past.slice(0, -1), future: [...h.future, current] },
    plan: h.past[h.past.length - 1],
  };
}

/** Redo: move `current` back onto past, restore the last undone state. */
export function redoStep<T>(h: History<T>, current: T): { history: History<T>; plan: T } | null {
  if (!h.future.length) return null;
  return {
    history: { past: [...h.past, current], future: h.future.slice(0, -1) },
    plan: h.future[h.future.length - 1],
  };
}

/** Undo changes content, not the live saved-version compare-and-swap authority. */
export function restorePlanContent(snapshot: EditPlan, current: EditPlan): EditPlan {
  const version = current.planVersion;
  if (version !== undefined && (!Number.isSafeInteger(version) || version < 0)) {
    throw new Error("Cannot restore history without valid current plan-version authority");
  }
  const restored = { ...snapshot };
  if (version === undefined) delete restored.planVersion;
  else restored.planVersion = version;
  return restored;
}
