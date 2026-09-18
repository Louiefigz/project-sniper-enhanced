"use client";

// The editor's persistence + re-render engine, extracted from editor-view
// (300-line budget): Save (edit_plan.json write + snapshot count), the smart
// re-render stream (assemble --auto-base) with warning collection + the
// already-running 409 UX, plan reload from disk, Reveal, and the PROJECT
// BROWSER upsert when a dir opens. State that belongs to the streams
// (saveState/reState/reMsg/vVersion/warnings/snapshots) lives here.

import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { readEventStream, summarizeEvent } from "@/lib/producer/sse";
import { collectWarnings, type WarningItem } from "@/lib/producer/warnings";
import type { StreamEvent } from "@/lib/producer/types";
import { reconcileGraphicIds, type EditPlan } from "@/lib/producer/edit-plan";
import {
  approvedOutputEvent,
  effectivePreviewAuthority,
  type PreviewAuthority,
} from "@/lib/producer/editor-preview-authority";
import { streamProgressMessage } from "@/lib/producer/project-state";
import {
  editorBrainLabel,
  launchAutoEditFromHyperframes,
  useEditorRuntime,
} from "../use-editor-runtime";

export type SaveState = "idle" | "saving" | "saved" | "error";
export type ReState = "idle" | "running" | "error";

interface ReProgress {
  refits: number;
  baseRebuilt: boolean; // a rebuild invalidates undo/redo (old timebase)
}

/** Fold one reviewed-render event into the progress line / video authority. */
function foldRenderReviewEvent(
  ev: StreamEvent,
  prog: ReProgress,
  setReMsg: (m: string) => void,
  approveVideo: () => void,
): void {
  if (ev.event === "error") throw new Error(String(ev.message));
  if (approvedOutputEvent(ev)) {
    approveVideo();
    return;
  }
  if (ev.status === "base_rebuild_start") {
    setReMsg("Rebuilding the base; elapsed time is tracked with this run…");
    return;
  }
  if (ev.status === "refit") {
    prog.baseRebuilt = true;
    prog.refits += 1;
    setReMsg(`refit: ${prog.refits} window${prog.refits === 1 ? "" : "s"} remapped`);
    return;
  }
  if (
    ev.status === "base_rebuilt" ||
    (typeof ev.status === "string" && ev.status.startsWith("refit"))
  ) {
    prog.baseRebuilt = true;
  }
  setReMsg(streamProgressMessage(ev) ?? summarizeEvent(ev));
}

interface Args {
  base: string; // render out dir, no trailing slash
  planPath: string;
  videoPath: string;
  title?: string;
  dirty: boolean;
  planRef: React.RefObject<EditPlan>;
  setPlan: Dispatch<SetStateAction<EditPlan>>;
  setDirty: (d: boolean) => void;
  pushUndo: (prev: EditPlan) => void;
  clearHistory: () => void;
}

export function usePlanActions(a: Args) {
  const runtime = useEditorRuntime();
  const brain = editorBrainLabel(runtime);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [reState, setReState] = useState<ReState>("idle");
  const [reMsg, setReMsg] = useState("");
  const [vVersion, setVVersion] = useState(0);
  const [warnings, setWarnings] = useState<WarningItem[]>([]);
  const [snapshotCount, setSnapshotCount] = useState<number | null>(null);
  const [verifiedPreview, setVerifiedPreview] = useState<PreviewAuthority>("checking");
  const previewAuthorityGeneration = useRef(0);
  const argsRef = useRef(a);
  argsRef.current = a;

  const invalidatePreviewAuthority = useCallback(() => {
    previewAuthorityGeneration.current += 1;
    setVerifiedPreview("stale");
  }, []);

  // Initial editor load is fail-closed: final.mp4 stays hidden until the disk
  // authority route proves it matches the current plan + manifest + approval.
  useEffect(() => {
    let active = true;
    const generation = previewAuthorityGeneration.current + 1;
    previewAuthorityGeneration.current = generation;
    setVerifiedPreview("checking");
    fetch(`/api/producer/project-status?dir=${encodeURIComponent(a.base)}&recover=0`)
      .then(async (response) => {
        const value = await response.json().catch(() => ({})) as {
          stages?: { final?: boolean };
          finalArtifact?: { state?: "missing" | "unapproved" | "approved" };
        };
        if (!response.ok) throw new Error(`project-status ${response.status}`);
        if (active && generation === previewAuthorityGeneration.current) {
          setVerifiedPreview(value.stages?.final === true ? "current"
            : value.finalArtifact?.state === "unapproved" ? "unapproved" : "stale");
        }
      })
      .catch(() => {
        if (active && generation === previewAuthorityGeneration.current) {
          setVerifiedPreview("stale");
        }
      });
    return () => { active = false; };
  }, [a.base]);

  // PROJECT BROWSER: opening a dir in the editor registers it as a recent edit.
  useEffect(() => {
    const { base, title } = argsRef.current;
    fetch("/api/producer/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dir: base, title: title || base.split("/").pop() }),
    }).catch(() => {}); // registry is a convenience — never block the editor on it
  }, [a.base]);

  /** Fold warning-class stream events into the persistent strip (any stream). */
  const addWarningEvent = useCallback((ev: StreamEvent) => {
    setWarnings((prev) => collectWarnings(prev, ev));
  }, []);
  const dismissWarnings = useCallback(() => setWarnings([]), []);

  const save = useCallback(async (): Promise<boolean> => {
    const { planPath, planRef, setDirty } = argsRef.current;
    setSaveState("saving");
    try {
      const res = await fetch("/api/producer/save-plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: planPath, plan: planRef.current }),
      });
      if (!res.ok) throw new Error(String(res.status));
      // Adopt the route's bumped planVersion (memory must match disk, else
      // every post-render reload sees a phantom diff). NOT a dirtying edit.
      const d = (await res.json().catch(() => ({}))) as {
        plan?: EditPlan; planVersion?: number; snapshots?: number;
      };
      if (d.plan) {
        argsRef.current.setPlan(reconcileGraphicIds(d.plan).plan);
      } else if (typeof d.planVersion === "number") {
        const v = d.planVersion;
        argsRef.current.setPlan((p) => ({ ...p, planVersion: v }));
      }
      if (typeof d.snapshots === "number") setSnapshotCount(d.snapshots);
      // The just-saved plan has a different version/hash than final.mp4's
      // approval. Keep the old video hidden until reviewed render promotion.
      invalidatePreviewAuthority();
      setDirty(false);
      setSaveState("saved");
      return true;
    } catch {
      setSaveState("error");
      return false;
    }
  }, [invalidatePreviewAuthority]);

  // Re-read edit_plan.json from disk (after an AI edit OR a smart re-render —
  // the auto-base path may refit-rewrite the plan on disk). Callers that want
  // the pre-reload state undo-able (the AI-edit path) pass pushUndo=true.
  const reloadPlan = useCallback(async (
    pushUndo = false,
    preservePreviewAuthority = false,
  ): Promise<boolean> => {
    const { planPath, planRef, setPlan, setDirty } = argsRef.current;
    try {
      const res = await fetch(`/api/producer/plan?path=${encodeURIComponent(planPath)}`);
      if (!res.ok) return false;
      // Reconcile graphic ids on the way in: an AI edit may have written new
      // (id-less) entries, duplicated an id on a copy, or fabricated one — the
      // editor addresses by id, so normalize before it enters state. Surviving
      // entries keep their ids, so an in-flight drag's captured id still lands.
      const next = reconcileGraphicIds((await res.json()) as EditPlan).plan;
      const prev = planRef.current;
      if (JSON.stringify(next) === JSON.stringify(prev)) return true;
      if (pushUndo) argsRef.current.pushUndo(prev);
      if (!preservePreviewAuthority) invalidatePreviewAuthority();
      setPlan(next);
      setDirty(false);
      return true;
    } catch {
      /* keep the in-memory plan on a read hiccup */
      return false;
    }
  }, [invalidatePreviewAuthority]);

  // Reviewed re-render: persist pending edits, then enter the deterministic
  // controller at the saved-plan checkpoint. It may revise the plan, but it
  // promotes final.mp4 only after planning gates, Audit B, and visual critics.
  const reRender = useCallback(async () => {
    if (argsRef.current.dirty && !(await save())) return;
    setReState("running");
    setReMsg(`${brain} is starting the reviewed MP4 pipeline…`);
    invalidatePreviewAuthority();
    const prog: ReProgress = { refits: 0, baseRebuilt: false };
    let approved = false;
    try {
      const res = await launchAutoEditFromHyperframes({
        dir: argsRef.current.base,
        request: { dir: argsRef.current.base, reviewSavedPlan: true },
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error(e.error || `saved-plan review ${res.status}`);
      }
      await readEventStream(res, (ev) => {
        addWarningEvent(ev); // warning-class statuses outlive the stream (strip)
        foldRenderReviewEvent(ev, prog, setReMsg, () => {
          approved = true;
          setVerifiedPreview("current");
          setVVersion((v) => v + 1);
        });
      }, undefined, "outputs");
      if (!approved) throw new Error("render completed without a current QC approval");
      setReState("idle");
      setReMsg("");
    } catch (e) {
      setReState("error");
      const msg = e instanceof Error ? e.message : "re-render failed";
      // The route's in-memory dir guard 409s a second POST; the python-side
      // .assemble.lock reports the same condition — one UX for both.
      setReMsg(/already running|another re-render/i.test(msg) ? "re-render already running — wait for it to finish" : msg);
    } finally {
      // Reload from disk when assemble may have REWRITTEN the plan (the refit
      // lands with a base rebuild, and the composite can still fail AFTER it —
      // skipping that reload would leave a stale un-refitted plan in memory
      // that a later Save clobbers over the refitted disk plan) or when memory
      // holds nothing unsaved. But a mid-render edit (e.g. drag-to-place while
      // the composite runs) must NOT be silently clobbered by reloading an
      // identical-but-older disk plan: on the graphics-only/audio fast paths
      // assemble never touches edit_plan.json, so a dirty plan skips the
      // reload. reloadPlan never touches reMsg — errors stay visible.
      const rewrote = prog.baseRebuilt || prog.refits > 0;
      if (rewrote && argsRef.current.dirty) {
        addWarningEvent({
          status: "midrender_edits_discarded",
          note: "the re-render refit rewrote edit_plan.json — unsaved edits made while it ran were on the old timebase and have been discarded",
        });
      }
      if (rewrote || !argsRef.current.dirty) await reloadPlan(false, approved);
      // A base rebuild is a point of no return: undo/redo snapshots are valid
      // only against the OLD base — Undo → Save → Re-render would composite
      // old-timebase windows onto the new base. Clear both stacks.
      if (prog.baseRebuilt) argsRef.current.clearHistory();
    }
  }, [save, reloadPlan, addWarningEvent, invalidatePreviewAuthority, brain]);

  // Export affordance: surface the deliverable in Finder (full-res final.mp4,
  // never the proxy). Errors land on the header status line — fail loudly.
  const revealFinal = useCallback(async (artifact: "sniper" | "palmier" = "sniper") => {
    try {
      const current = argsRef.current;
      const artifactPath = artifact === "palmier"
        ? `${current.base}/final.palmier.mp4` : current.videoPath;
      const res = await fetch("/api/producer/reveal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: artifactPath }),
      });
      const d = (await res.json().catch(() => ({}))) as { error?: string };
      if (!res.ok || d.error) throw new Error(d.error || `reveal ${res.status}`);
    } catch (e) {
      setReState("error");
      setReMsg(`reveal ${artifact}: ${e instanceof Error ? e.message : "failed"}`);
    }
  }, []);

  return {
    saveState,
    setSaveState,
    reState,
    reMsg,
    vVersion,
    warnings,
    snapshotCount,
    previewAuthority: effectivePreviewAuthority(a.dirty, verifiedPreview),
    invalidatePreviewAuthority,
    addWarningEvent,
    dismissWarnings,
    save,
    reloadPlan,
    reRender,
    revealFinal,
  };
}
