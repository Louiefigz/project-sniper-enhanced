"use client";

import { useCallback, type Dispatch, type SetStateAction } from "react";
import type { EditPlan, GraphicEntry } from "@/lib/producer/edit-plan";
import type { ContentBBox, Placement } from "@/lib/producer/placement-geometry";
import { fmtMmSs, type Win } from "@/lib/producer/timeline-scale";
import type { StreamEvent } from "@/lib/producer/types";
import { editorPaths, useEditorPlayback, useEditorUiState } from "./editor-state";
import { useEditorPlanController } from "./use-editor-plan-controller";
import { useEditorShortcuts, useUnsavedGuard } from "./use-editor-shortcuts";
import { useGraphicEdits } from "./use-graphic-edits";

interface Args {
  initialPlan: EditPlan;
  dir: string;
  title?: string;
  externalLockReason: string | null;
  palmierLockReason: string | null;
}

interface RangeArgs {
  setAskPrefill: Dispatch<SetStateAction<{ text: string; nonce: number } | null>>;
  setRailRequest: Dispatch<SetStateAction<{ id: "elements"; nonce: number } | null>>;
  setPendingInsert: Dispatch<SetStateAction<Win | null>>;
}

function useRangeActions(args: RangeArgs) {
  const { setAskPrefill, setRailRequest, setPendingInsert } = args;
  const ask = useCallback((start: number, end: number) => {
    setAskPrefill({ text: `[${fmtMmSs(start)}–${fmtMmSs(end)}] `, nonce: Date.now() });
  }, [setAskPrefill]);
  const add = useCallback((start: number, end: number) => {
    setPendingInsert({ start, end });
    setRailRequest({ id: "elements", nonce: Date.now() });
  }, [setPendingInsert, setRailRequest]);
  return { ask, add };
}

interface PlacementArgs {
  selected: string | null;
  kind?: string;
  updateGraphic: (id: string, patch: Partial<GraphicEntry>) => void;
  addWarningEvent: (event: StreamEvent) => void;
  locked: boolean;
}

function usePlacementCommit(args: PlacementArgs) {
  const { selected, kind, updateGraphic, addWarningEvent, locked } = args;
  return useCallback((
    placement: (Placement & { scale?: number }) | null,
    unsafe: boolean,
    contentBBox?: ContentBBox | null,
  ) => {
    if (selected == null || locked) return;
    // Stamp the preview-measured content bbox WITH the placement (geometry
    // contract v3 item #6e) — the plan lint's SAFE_BOX check reads it and is
    // point-degenerate without. Reset-to-auto clears it alongside placement;
    // an unmeasured commit (null bbox) leaves any previous stamp untouched.
    const patch: Partial<GraphicEntry> = { placement: placement ?? undefined };
    if (!placement) patch.contentBBox = undefined;
    else if (contentBBox) patch.contentBBox = contentBBox;
    updateGraphic(selected, patch);
    if (!unsafe || !placement) return;
    addWarningEvent({
      status: "placement_unsafe",
      graphic: `${kind}#${selected}`,
      note: "outside platform-safe area (SAFE_BOX)",
    });
  }, [selected, kind, updateGraphic, addWarningEvent, locked]);
}

export function useEditorController({
  initialPlan, dir, title, externalLockReason, palmierLockReason,
}: Args) {
  const paths = editorPaths(dir);
  const playback = useEditorPlayback(initialPlan);
  const ui = useEditorUiState();
  const planState = useEditorPlanController({
    initialPlan, paths, title, aiBusy: ui.aiBusy,
    externalLockReason, palmierLockReason, setSelected: ui.setSelected,
  });
  const graphics = useGraphicEdits({
    mutatePlan: planState.history.mutatePlan, planRef: planState.history.planRef,
    timeRef: playback.timeRef, durationRef: playback.durationRef,
    selected: ui.selected, setSelected: ui.setSelected,
  });
  useEditorShortcuts({
    videoRef: playback.videoRef, onTime: playback.onTime,
    undo: planState.undo, redo: planState.redo, hasBlock: ui.selected != null,
    onNudgeBlock: graphics.nudgeSelected, onDeselectBlock: () => ui.setSelected(null),
    onDeleteBlock: () => ui.selected != null && graphics.removeGraphic(ui.selected),
    onDuplicateBlock: graphics.duplicateSelected, onSplit: graphics.splitAtPlayhead,
    locked: planState.editingLocked,
  });
  useUnsavedGuard(planState.history.dirty);
  const ranges = useRangeActions({
    setAskPrefill: ui.setAskPrefill, setRailRequest: ui.setRailRequest,
    setPendingInsert: graphics.setPendingInsert,
  });
  const selectedGraphic = ui.selected == null
    ? undefined
    : planState.history.plan.graphicsTrack?.find((graphic) => graphic.id === ui.selected);
  const selectedGraphicLive = selectedGraphic && ui.dragWindow?.id === ui.selected
    ? { ...selectedGraphic, outStart: ui.dragWindow.start, outEnd: ui.dragWindow.end }
    : selectedGraphic;
  const commitPlacement = usePlacementCommit({
    selected: ui.selected, kind: selectedGraphicLive?.kind,
    updateGraphic: graphics.updateGraphic, addWarningEvent: planState.actions.addWarningEvent,
    locked: planState.editingLocked,
  });

  return { paths, playback, ui, planState, graphics, ranges, selectedGraphic, selectedGraphicLive, commitPlacement };
}

export type EditorController = ReturnType<typeof useEditorController>;
