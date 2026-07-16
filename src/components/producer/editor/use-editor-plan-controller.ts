"use client";

import { useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import type { EditPlan } from "@/lib/producer/edit-plan";
import type { EditorPaths } from "./editor-state";
import { usePlanActions, type ReState } from "./use-plan-actions";
import { usePlanHistory } from "./use-plan-history";

interface Args {
  initialPlan: EditPlan;
  paths: EditorPaths;
  title?: string;
  aiBusy: boolean;
  externalLockReason: string | null;
  palmierLockReason: string | null;
  setSelected: Dispatch<SetStateAction<string | null>>;
}

function saveBlockReason(reState: ReState, aiBusy: boolean, mutationLockReason: string | null): string | null {
  if (mutationLockReason) return mutationLockReason;
  if (reState === "running") {
    return "re-render is running — it may rewrite edit_plan.json (refit); wait for it to finish";
  }
  if (aiBusy) return "AI editor is editing edit_plan.json — saving now would clobber its edit";
  return null;
}

export function useEditorPlanController(args: Args) {
  const afterChangeRef = useRef<() => void>(() => {});
  const history = usePlanHistory(args.initialPlan, () => afterChangeRef.current());
  const actions = usePlanActions({
    base: args.paths.base,
    planPath: args.paths.planPath,
    videoPath: args.paths.videoPath,
    title: args.title,
    dirty: history.dirty,
    planRef: history.planRef,
    setPlan: history.setPlan,
    setDirty: history.setDirty,
    pushUndo: history.pushUndo,
    clearHistory: history.clearHistory,
  });
  const { setSaveState } = actions;
  useEffect(() => {
    afterChangeRef.current = () => setSaveState("idle");
  }, [setSaveState]);

  const histUndo = history.undo;
  const histRedo = history.redo;
  const { setSelected } = args;
  const undo = useCallback(() => {
    if (histUndo()) setSelected(null);
  }, [histUndo, setSelected]);
  const redo = useCallback(() => {
    if (histRedo()) setSelected(null);
  }, [histRedo, setSelected]);
  const mutationLockReason = args.externalLockReason ?? args.palmierLockReason;
  const editingLocked = actions.reState === "running" || args.aiBusy || mutationLockReason != null;

  return {
    history,
    actions,
    undo,
    redo,
    editingLocked,
    externalLockReason: args.externalLockReason,
    palmierLockReason: args.palmierLockReason,
    mutationLockReason,
    saveBlocked: saveBlockReason(actions.reState, args.aiBusy, mutationLockReason),
  };
}
