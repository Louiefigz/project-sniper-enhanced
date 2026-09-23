"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import type { CompCatalogEntry } from "@/lib/producer/comps-catalog";
import { requireCatalogKind } from "@/lib/producer/visual-source-policy";
import type { CutRange } from "./script-words";
import {
  addSourceRange,
  cutOutputRange,
  newGraphicId,
  removeSourceRange,
  splitSegmentAt,
  type CutSegment,
  type EditPlan,
  type GraphicEntry,
} from "@/lib/producer/edit-plan";
import { moveWindow, type Win } from "@/lib/producer/timeline-scale";

// Every direct-manipulation plan edit the editor exposes, extracted from
// editor-view (300-line budget): graphic patch/remove/add/duplicate/nudge,
// the drag-commit, cut-track surgery (strike-to-cut, restore, range cut,
// split-at-playhead), and the pending-insert window the ruler's "Add graphic
// here" hands to the ELEMENTS panel. All of it funnels through mutatePlan —
// one call = one undo step. Pure track surgery runs BEFORE mutatePlan so a
// refused edit (loud throw) never pushes a phantom undo step.

interface Args {
  mutatePlan: (fn: (p: EditPlan) => EditPlan, opts?: { coalesce?: boolean }) => void;
  planRef: RefObject<EditPlan>;
  timeRef: RefObject<number>; // live playhead (refs — stable callbacks)
  durationRef: RefObject<number>;
  selected: string | null; // the selected graphic's stable id (never an index)
  setSelected: (id: string | null) => void;
}

const round2 = (n: number): number => Math.round(n * 100) / 100;
const round3 = (n: number): number => Math.round(n * 1000) / 1000; // keeps ±1-frame nudges exact

export function useGraphicEdits(a: Args) {
  const { mutatePlan, planRef, timeRef, durationRef, selected, setSelected } = a;
  const [pendingInsert, setPendingInsert] = useState<Win | null>(null);
  const selRef = useRef(selected);
  useEffect(() => {
    selRef.current = selected; // keyboard handlers read the latest selection
  });

  // Resolve a graphic by its STABLE id. A gesture captures the id at
  // pointerdown; by commit time the plan may have been replaced under it
  // (AI-edit reload / post-render refit rewrite) or the entry removed. Id
  // addressing means a surviving entry is found wherever it moved to, and a
  // vanished one resolves to -1 → the edit is dropped (loud), never mis-applied
  // to whatever slid into that index.
  const indexOfId = useCallback(
    (id: string, op: string): number => {
      const i = planRef.current.graphicsTrack?.findIndex((g) => g.id === id) ?? -1;
      if (i < 0) console.warn(`${op}: no graphic with id ${id} — plan changed mid-gesture, edit dropped`);
      return i;
    },
    [planRef],
  );

  const updateGraphic = useCallback(
    (id: string, patch: Partial<GraphicEntry>, coalesce = false) => {
      const index = indexOfId(id, "updateGraphic");
      if (index < 0) return;
      requireCatalogKind(patch.kind ?? planRef.current.graphicsTrack?.[index].kind);
      mutatePlan(
        (p) => {
          const track = [...(p.graphicsTrack ?? [])];
          track[index] = { ...track[index], ...patch };
          return { ...p, graphicsTrack: track };
        },
        { coalesce },
      );
    },
    [mutatePlan, indexOfId, planRef],
  );

  const removeGraphic = useCallback(
    (id: string) => {
      if (indexOfId(id, "removeGraphic") < 0) return;
      mutatePlan((p) => ({
        ...p,
        graphicsTrack: (p.graphicsTrack ?? []).filter((g) => g.id !== id),
      }));
      setSelected(null);
    },
    [mutatePlan, setSelected, indexOfId],
  );

  /** Drag/trim release + duration chips — ONE mutatePlan per gesture. */
  const commitGraphicWindow = useCallback(
    (id: string, start: number, end: number) =>
      updateGraphic(id, { outStart: round2(start), outEnd: round2(end) }),
    [updateGraphic],
  );

  // ELEMENTS: insert a catalog comp — into the ruler-selected pending window
  // when one is armed (then cleared), else 4s at the playhead (kept INSIDE the
  // video: near the end the window slides back rather than spilling past
  // duration; degenerate/unknown durations skip the clamp) — and select it so
  // the properties panel opens for text editing.
  const addGraphic = useCallback(
    (entry: CompCatalogEntry) => {
      requireCatalogKind(entry.kind);
      const t = round2(timeRef.current);
      const dur = durationRef.current;
      const win =
        pendingInsert ??
        (dur >= 4 ? moveWindow({ start: t, end: t + 4 }, 0, dur) : { start: t, end: round2(t + 4) });
      const id = newGraphicId();
      const g: GraphicEntry = {
        id,
        outStart: round2(win.start),
        outEnd: round2(win.end),
        kind: entry.kind,
        anchor: entry.ownScreen ? "own-screen" : "free-band",
        spec: { ...entry.defaultSpec },
        reason: "operator",
      };
      mutatePlan((p) => ({ ...p, graphicsTrack: [...(p.graphicsTrack ?? []), g] }));
      setSelected(id);
      setPendingInsert(null);
    },
    [pendingInsert, mutatePlan, setSelected, timeRef, durationRef],
  );

  /** ⌘D — duplicate the selected graphic at the playhead (same length). */
  const duplicateSelected = useCallback(() => {
    const id = selRef.current;
    const g = id != null ? planRef.current.graphicsTrack?.find((x) => x.id === id) : undefined;
    if (!g || !(g.outEnd > g.outStart)) return;
    requireCatalogKind(g.kind);
    const t = timeRef.current;
    const win = moveWindow({ start: t, end: t + (g.outEnd - g.outStart) }, 0, durationRef.current);
    // A copy is a NEW entry — mint its own id (never share the source's).
    const copyId = newGraphicId();
    const copy: GraphicEntry = { ...g, id: copyId, spec: { ...(g.spec ?? {}) }, outStart: round2(win.start), outEnd: round2(win.end) };
    mutatePlan((p) => ({ ...p, graphicsTrack: [...(p.graphicsTrack ?? []), copy] }));
    setSelected(copyId);
  }, [mutatePlan, setSelected, planRef, timeRef, durationRef]);

  /**
   * Arrow keys — move the selected block ±deltaS, clamped, length preserved.
   * `coalesce` = the keydown is an auto-repeat (a HELD key): the whole held
   * gesture stays ONE undo entry instead of spamming the 20-step history.
   */
  const nudgeSelected = useCallback(
    (deltaS: number, coalesce = false) => {
      const id = selRef.current;
      const g = id != null ? planRef.current.graphicsTrack?.find((x) => x.id === id) : undefined;
      if (!g || !(g.outEnd > g.outStart)) return;
      const win = moveWindow({ start: g.outStart, end: g.outEnd }, deltaS, durationRef.current);
      updateGraphic(id as string, { outStart: round3(win.start), outEnd: round3(win.end) }, coalesce);
    },
    [updateGraphic, planRef, durationRef],
  );

  /** S key / Split button — split the cut segment at the playhead's source time. */
  const splitAtPlayhead = useCallback(() => {
    const next = splitSegmentAt(planRef.current.cutTrack ?? [], timeRef.current);
    if (!next) return; // seam / outside the cut — nothing to split, no phantom undo
    mutatePlan((p) => ({ ...p, cutTrack: next }));
  }, [mutatePlan, planRef, timeRef]);

  /** Ruler "Cut section" — output span → per-source sub-ranges → strike-to-cut. */
  const cutRange = useCallback(
    (outStart: number, outEnd: number) => {
      try {
        const next = cutOutputRange(planRef.current.cutTrack ?? [], outStart, outEnd);
        mutatePlan((p) => ({ ...p, cutTrack: next }));
      } catch (e) {
        window.alert(e instanceof Error ? e.message : "cut failed");
      }
    },
    [mutatePlan, planRef],
  );

  // Script mode strike-to-cut: remove the selected SOURCE ranges from cutTrack.
  const cutRanges = useCallback(
    (ranges: CutRange[]) => {
      mutatePlan((p) => ({
        ...p,
        cutTrack: ranges.reduce(
          (ct, r) => removeSourceRange(ct, r.sourceId, r.start, r.end),
          p.cutTrack ?? [],
        ),
      }));
    },
    [mutatePlan],
  );

  // Script mode un-cut: RESTORE struck SOURCE ranges into cutTrack. The pure
  // union runs BEFORE mutatePlan so a refused restore (mixed-speed span fails
  // loudly) never pushes a phantom undo step.
  const restoreRanges = useCallback(
    (ranges: CutRange[]) => {
      try {
        const next = ranges.reduce(
          (ct, r) => addSourceRange(ct, r.sourceId, r.start, r.end),
          planRef.current.cutTrack ?? [],
        );
        mutatePlan((p) => ({ ...p, cutTrack: next }));
      } catch (e) {
        window.alert(e instanceof Error ? e.message : "restore failed");
      }
    },
    [mutatePlan, planRef],
  );

  const applyCutTrack = useCallback(
    (cutTrack: CutSegment[]) => mutatePlan((p) => ({ ...p, cutTrack })),
    [mutatePlan],
  );

  return {
    updateGraphic,
    removeGraphic,
    commitGraphicWindow,
    addGraphic,
    duplicateSelected,
    nudgeSelected,
    splitAtPlayhead,
    cutRange,
    cutRanges,
    restoreRanges,
    applyCutTrack,
    pendingInsert,
    setPendingInsert,
  };
}
