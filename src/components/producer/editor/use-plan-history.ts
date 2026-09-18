"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  emptyHistory,
  recordEdit,
  restorePlanContent,
  redoStep,
  undoStep,
  type History,
} from "@/lib/producer/plan-history";
import type { EditPlan } from "@/lib/producer/edit-plan";

const HISTORY_LIMIT = 20;

// The editor's in-memory plan + two-stack undo/redo, extracted from
// editor-view (300-line budget). Every plan edit funnels through mutatePlan:
// it pushes the pre-edit state onto the undo stack (last 20), CLEARS redo, and
// marks the plan dirty. `onAfterChange` runs after every mutation/undo/redo
// (editor-view resets the save state there) — held in a ref so it may close
// over hooks that initialize AFTER this one (usePlanActions' setSaveState).
export function usePlanHistory(initialPlan: EditPlan, onAfterChange?: () => void) {
  const [plan, setPlan] = useState<EditPlan>(initialPlan);
  const [hist, setHist] = useState<History<EditPlan>>(emptyHistory());
  const [dirty, setDirty] = useState(false);
  // Mirror refs for handler reads. Synced post-render for EXTERNAL setPlan
  // callers (use-plan-actions' save/reload) and written synchronously inside
  // mutatePlan/restore so same-tick reads never see a stale plan.
  const planRef = useRef(plan);
  const histRef = useRef(hist);
  const onAfterChangeRef = useRef(onAfterChange);
  useEffect(() => {
    planRef.current = plan;
    histRef.current = hist;
    onAfterChangeRef.current = onAfterChange;
  });

  const pushUndo = useCallback(
    (prev: EditPlan) => setHist((h) => recordEdit(h, prev, HISTORY_LIMIT)),
    [],
  );
  const clearHistory = useCallback(() => setHist(emptyHistory()), []);

  const mutatePlan = useCallback(
    (fn: (p: EditPlan) => EditPlan, opts?: { coalesce?: boolean }) => {
      const prev = planRef.current;
      if (opts?.coalesce) {
        // Continuation of an in-flight gesture (a held arrow key's auto-repeat
        // nudges): reuse the gesture's ONE undo entry — the gesture's first
        // event pushed it — but still clear redo like any other edit.
        setHist((h) => (h.future.length ? { ...h, future: [] } : h));
      } else {
        pushUndo(prev);
      }
      const next = fn(prev);
      planRef.current = next;
      setPlan(next);
      setDirty(true);
      onAfterChangeRef.current?.();
    },
    [pushUndo],
  );

  /** Apply an undo/redo step; true when a step existed (caller resets selection). */
  const restore = useCallback((step: { history: History<EditPlan>; plan: EditPlan } | null): boolean => {
    if (!step) return false;
    const restored = restorePlanContent(step.plan, planRef.current);
    histRef.current = step.history;
    planRef.current = restored;
    setHist(step.history);
    setPlan(restored);
    setDirty(true);
    onAfterChangeRef.current?.();
    return true;
  }, []);

  const undo = useCallback(
    () => restore(undoStep(histRef.current, planRef.current)),
    [restore],
  );
  const redo = useCallback(
    () => restore(redoStep(histRef.current, planRef.current)),
    [restore],
  );

  return {
    plan,
    setPlan,
    planRef,
    dirty,
    setDirty,
    canUndo: hist.past.length > 0,
    canRedo: hist.future.length > 0,
    pushUndo,
    clearHistory,
    mutatePlan,
    undo,
    redo,
  };
}
