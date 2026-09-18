"use client";

import { useEffect, useRef, type RefObject } from "react";

const FINE_STEP_S = 1 / 24; // honest fixed-time nudge; source/output frame rates can vary

interface ShortcutOpts {
  videoRef: RefObject<HTMLVideoElement | null>;
  onTime: (t: number) => void; // report the new playhead after a seek nudge
  undo: () => void;
  redo: () => void;
  // EDIT KEYS — the arrows are MODAL: with a graphic block selected they nudge
  // the BLOCK (±1 frame, Shift ±1s); with none selected they seek as before.
  // Esc exits block mode (deselect) so the arrows seek again.
  hasBlock: boolean;
  onNudgeBlock: (deltaS: number, coalesce: boolean) => void; // coalesce = key auto-repeat (held key = ONE undo entry)
  onDeselectBlock: () => void; // Esc — back to seek mode
  onDeleteBlock: () => void; // Delete/Backspace removes the selected graphic
  onDuplicateBlock: () => void; // ⌘D duplicates it at the playhead
  onSplit: () => void; // S splits the cut segment at the playhead
  locked?: boolean;
}

/** True when the key event originates in a text-entry control (don't hijack). */
function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || !el.tagName) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

/** Block-edit keys; returns true when the event was consumed. */
function handleEditKeys(e: KeyboardEvent, o: ShortcutOpts): boolean {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "d") {
    e.preventDefault(); // even without a block — ⌘D must never bookmark the tab mid-edit
    if (o.hasBlock) o.onDuplicateBlock();
    return true;
  }
  if (e.metaKey || e.ctrlKey || e.altKey) return false;
  if ((e.key === "Delete" || e.key === "Backspace") && o.hasBlock) {
    e.preventDefault();
    o.onDeleteBlock();
    return true;
  }
  if (e.key === "Escape" && o.hasBlock) {
    o.onDeselectBlock(); // leave block mode — the arrows seek again
    return true;
  }
  if (e.key.toLowerCase() === "s" && !e.shiftKey) {
    e.preventDefault();
    o.onSplit();
    return true;
  }
  if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && o.hasBlock) {
    e.preventDefault();
    const step = e.shiftKey ? 1 : FINE_STEP_S;
    // e.repeat = held key: coalesce the auto-repeats into the first press's
    // undo entry, so the whole hold is ONE gesture to ⌘Z.
    o.onNudgeBlock(e.key === "ArrowLeft" ? -step : step, e.repeat);
    return true;
  }
  return false;
}

/** Play/pause + seek keys (the no-block-selected mode). */
function handleTransportKeys(e: KeyboardEvent, o: ShortcutOpts): void {
  const v = o.videoRef.current;
  if (e.key === " ") {
    e.preventDefault();
    if (!v) return;
    if (v.paused) void v.play();
    else v.pause();
    return;
  }
  if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
    e.preventDefault();
    if (!v) return;
    const step = e.shiftKey ? 1 : FINE_STEP_S;
    const delta = e.key === "ArrowLeft" ? -step : step;
    const max = Number.isFinite(v.duration) ? v.duration : Number.MAX_VALUE;
    v.currentTime = Math.max(0, Math.min(v.currentTime + delta, max));
    o.onTime(v.currentTime);
  }
}

// Editor-root keyboard shortcuts: space play/pause · ←/→ ±0.04s, Shift ±1s
// (seek — or nudge the selected block; Esc deselects) · Del/Backspace remove
// block · ⌘D duplicate at playhead · S split at playhead · ⌘Z / ⌘⇧Z undo /
// redo. Guarded by event target so typing in an input/textarea never triggers.
export function useEditorShortcuts(opts: ShortcutOpts): void {
  const optsRef = useRef(opts);
  useEffect(() => {
    optsRef.current = opts; // keydown handler reads the latest bindings
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target)) return;
      const o = optsRef.current;
      if (o.locked) {
        handleTransportKeys(e, o);
        return;
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) o.redo();
        else o.undo();
        return;
      }
      if (handleEditKeys(e, o)) return;
      handleTransportKeys(e, o);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

/** Warn before closing/reloading the tab while the plan has unsaved edits. */
export function useUnsavedGuard(dirty: boolean): void {
  useEffect(() => {
    if (!dirty) return;
    const guard = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "unsaved edits"; // Chrome shows a generic prompt; the value flags it
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);
}
