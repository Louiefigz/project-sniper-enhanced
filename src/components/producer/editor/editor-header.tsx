"use client";

import type { PreviewAuthority } from "@/lib/producer/editor-preview-authority";

interface Props {
  title?: string;
  onBack?: () => void;
  reState: "idle" | "running" | "error";
  reMsg: string;
  saveState: "idle" | "saving" | "saved" | "error";
  dirty: boolean;
  previewAuthority: PreviewAuthority;
  canUndo: boolean;
  canRedo: boolean;
  saveBlocked?: string | null; // concurrency guard — why Save is disabled right now
  reBlocked?: string | null; // concurrency guard — why Re-render is disabled right now
  snapshotCount?: number | null; // plan-history/ snapshots on disk (save-plan reports it)
  revealLabel?: string;
  revealTitle?: string;
  onUndo: () => void;
  onRedo: () => void;
  onSave: () => void;
  onReRender: () => void;
  onReveal: () => void;
}

const SHORTCUTS =
  "Space play/pause · ←/→ ±0.04s, Shift+←/→ ±1s (block selected: arrows nudge the BLOCK, not the playhead — Esc deselects) · " +
  "Del/⌫ remove selected graphic · ⌘D duplicate at playhead · S split cut at playhead · " +
  "drag blocks to move, edges to trim (Alt = no snap) · drag the ruler to range-select (Esc clears) · " +
  "⌘Z undo · ⌘⇧Z redo";

// Editor chrome header: title, SKILLS badge, save/re-render status line, and
// the Undo / Redo / Save / Re-render / Reveal actions. Pure presentation —
// state lives in editor-view / use-plan-actions. saveBlocked/reBlocked carry
// the concurrency-guard reason into the disabled buttons' tooltips.
export default function EditorHeader(p: Props) {
  const saveTitle =
    p.saveBlocked ??
    (typeof p.snapshotCount === "number"
      ? `writes edit_plan.json (${p.snapshotCount} snapshot${p.snapshotCount === 1 ? "" : "s"} on disk in plan-history/)`
      : "writes edit_plan.json (previous version snapshotted to plan-history/)");
  return (
    <header className="flex min-h-12 shrink-0 items-center gap-3 overflow-x-auto border-b border-neutral-800 px-4 py-2">
      {p.onBack && (
        <button type="button" onClick={p.onBack} className="text-sm text-neutral-400 hover:text-neutral-200">
          ← Projects
        </button>
      )}
      <h1 className="truncate text-sm font-medium" title={SHORTCUTS}>
        {p.title ?? "PRODUCER editor"}
      </h1>
      <span
        title={SHORTCUTS}
        className="flex h-4 w-4 shrink-0 cursor-help select-none items-center justify-center rounded-full border border-neutral-700 text-[10px] text-neutral-500"
      >
        ?
      </span>
      <div className="ml-auto flex items-center gap-2">
        {p.reState !== "idle" && (
          <span
            className={`max-w-[22rem] truncate text-[11px] ${p.reState === "error" ? "text-rose-400" : "text-neutral-400"}`}
          >
            {p.reMsg}
          </span>
        )}
        {p.reState === "idle" && p.saveState === "saved" && !p.dirty && (
          <span className="text-[11px] text-emerald-400/80">timeline saved · render to update the video</span>
        )}
        {p.saveState === "error" && <span className="text-[11px] text-rose-400">save failed</span>}
        {p.reState === "idle" && p.previewAuthority !== "current" && (
          <span className="text-[11px] text-amber-300/90">
            {p.previewAuthority === "checking" ? "verifying video…"
              : p.previewAuthority === "unapproved" ? "unapproved review copy" : "video out of date"}
          </span>
        )}
        <button
          type="button"
          onClick={p.onUndo}
          disabled={!p.canUndo}
          title="Undo the last timeline edit (⌘Z — save and render the updated video to apply)"
          className="rounded-md border border-neutral-700 px-3 py-1 text-xs text-neutral-200 enabled:hover:bg-neutral-800 disabled:cursor-not-allowed disabled:text-neutral-600"
        >
          Undo
        </button>
        <button
          type="button"
          onClick={p.onRedo}
          disabled={!p.canRedo}
          title="Redo the last undone edit (⌘⇧Z — cleared by a new edit or a base rebuild)"
          className="rounded-md border border-neutral-700 px-3 py-1 text-xs text-neutral-200 enabled:hover:bg-neutral-800 disabled:cursor-not-allowed disabled:text-neutral-600"
        >
          Redo
        </button>
        <button
          type="button"
          onClick={p.onSave}
          disabled={!p.dirty || p.saveState === "saving" || !!p.saveBlocked}
          title={saveTitle}
          className="rounded-md border border-neutral-700 px-3 py-1 text-xs text-neutral-200 enabled:hover:bg-neutral-800 disabled:cursor-not-allowed disabled:text-neutral-600"
        >
          {p.saveState === "saving" ? "Saving…" : "Save timeline"}
        </button>
        <button
          type="button"
          onClick={p.onReRender}
          disabled={p.reState === "running" || !!p.reBlocked}
          className="rounded-md bg-amber-500/90 px-3 py-1 text-xs font-medium text-neutral-950 enabled:hover:bg-amber-400 disabled:cursor-not-allowed disabled:opacity-60"
          title={
            p.reBlocked ??
            "Review the saved plan, render an isolated candidate, run deterministic + visual QC, then promote only an approved video"
          }
        >
          {p.reState === "running" ? "Rendering…" : "Render updated video"}
        </button>
        <button
          type="button"
          onClick={p.onReveal}
          disabled={p.reState === "running" || p.previewAuthority === "checking" || p.previewAuthority === "stale"}
          title={p.previewAuthority === "current" || p.previewAuthority === "unapproved"
            ? p.revealTitle ?? "opens Finder at the approved deliverable"
            : "the saved plan has no matching approved deliverable yet"}
          className="rounded-md border border-neutral-700 px-3 py-1 text-xs text-neutral-200 enabled:hover:bg-neutral-800 disabled:cursor-not-allowed disabled:text-neutral-600"
        >
          {p.revealLabel ?? "Show final video"}
        </button>
      </div>
    </header>
  );
}
