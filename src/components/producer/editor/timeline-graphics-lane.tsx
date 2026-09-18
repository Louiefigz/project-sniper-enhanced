"use client";

import { useState } from "react";
import type { GraphicBlock } from "@/lib/producer/edit-plan";
import {
  fmtWindow,
  moveWindow,
  resolveSnap,
  snapMovedWindow,
  snapThresholdS,
  timeToPx,
  trimWindow,
  type Win,
} from "@/lib/producer/timeline-scale";

// DIRECT-MANIPULATION graphics lane. Pointer-capture drag on a block moves it
// in time; the left/right edge handles trim outStart/outEnd. Geometry is all
// timeline-scale pure functions (move/trim clamp + min duration + snap);
// snapping targets the playhead, other blocks' edges, and whole seconds —
// hold Alt to disable. ONE commit per gesture on release (undo = the whole
// drag); pointermoves report the live window upward so the instant graphic
// preview tracks the in-progress window. A plain click (<3px) keeps the old
// select-and-seek behavior.

interface Drag {
  id: string; // the dragged block's stable id — survives a mid-drag plan replace
  mode: "move" | "trim-start" | "trim-end";
  pointerId: number;
  originX: number;
  orig: Win;
  live: Win;
  moved: boolean;
  snapped: number | null;
}

interface Props {
  blocks: GraphicBlock[];
  pps: number;
  duration: number;
  currentTime: number;
  selected: string | null;
  onSelect: (id: string | null) => void;
  onSeek: (t: number) => void;
  onCommitWindow: (id: string, start: number, end: number) => void;
  onDragWindow: (w: { id: string; start: number; end: number } | null) => void;
  locked?: boolean;
}

const round2 = (n: number): number => Math.round(n * 100) / 100;
const q10 = (n: number): number => Math.round(n * 10) / 10; // preview-report quantum

/** Live window for a drag position, snapped (unless Alt) and clamped. */
function dragWin(d: Drag, dxT: number, targets: number[], thr: number, duration: number): {
  live: Win;
  snapped: number | null;
} {
  if (d.mode === "move") {
    let w = moveWindow(d.orig, dxT, duration);
    let snapped: number | null = null;
    if (thr > 0) {
      const r = snapMovedWindow(w, targets, thr);
      w = moveWindow(r.win, 0, duration); // re-clamp after the snap shift
      snapped = r.snapped;
    }
    return { live: w, snapped };
  }
  const edge = d.mode === "trim-start" ? "start" : "end";
  let t = (edge === "start" ? d.orig.start : d.orig.end) + dxT;
  let snapped: number | null = null;
  if (thr > 0) {
    const r = resolveSnap(t, targets, thr);
    t = r.t;
    snapped = r.snapped;
  }
  return { live: trimWindow(d.orig, edge, t, duration), snapped };
}

export default function GraphicsLane(p: Props) {
  const [drag, setDrag] = useState<Drag | null>(null);

  const targetsFor = (id: string): number[] => [
    p.currentTime,
    ...p.blocks.filter((b) => b.id !== id).flatMap((b) => [b.start, b.end]),
  ];

  const begin = (e: React.PointerEvent, b: GraphicBlock, mode: Drag["mode"]) => {
    e.stopPropagation();
    if (p.locked) {
      p.onSelect(b.id);
      p.onSeek(b.start);
      return;
    }
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    const orig = { start: b.start, end: b.end };
    setDrag({ id: b.id, mode, pointerId: e.pointerId, originX: e.clientX, orig, live: orig, moved: false, snapped: null });
  };

  const move = (e: React.PointerEvent) => {
    if (!drag || e.pointerId !== drag.pointerId) return;
    const dx = e.clientX - drag.originX;
    if (!drag.moved && Math.abs(dx) < 3) return; // click, not a drag (yet)
    if (!drag.moved && p.selected !== drag.id) p.onSelect(drag.id); // preview follows the gesture
    const thr = e.altKey ? 0 : snapThresholdS(p.pps);
    const { live, snapped } = dragWin(drag, dx / p.pps, targetsFor(drag.id), thr, p.duration);
    setDrag({ ...drag, live, moved: true, snapped });
    p.onDragWindow({ id: drag.id, start: q10(live.start), end: q10(live.end) });
  };

  const end = (e: React.PointerEvent, cancel = false) => {
    if (!drag || e.pointerId !== drag.pointerId) return;
    if (drag.moved && !cancel) {
      p.onCommitWindow(drag.id, round2(drag.live.start), round2(drag.live.end)); // ONE mutatePlan per gesture
    } else if (!drag.moved && !cancel) {
      const active = p.selected === drag.id; // plain click: toggle select + seek (pre-drag behavior)
      p.onSelect(active ? null : drag.id);
      p.onSeek(drag.orig.start);
    }
    p.onDragWindow(null);
    setDrag(null);
  };

  return (
    <>
      {p.blocks.map((b) => {
        const active = p.selected === b.id;
        const dragging = drag?.moved && drag.id === b.id;
        const win = dragging ? drag.live : { start: b.start, end: b.end };
        return (
          <div
            key={b.id}
            onPointerDown={(e) => begin(e, b, "move")}
            onPointerMove={move}
            onPointerUp={(e) => end(e)}
            onPointerCancel={(e) => end(e, true)}
            onClick={(e) => e.stopPropagation()} // the lane behind seeks; the block owns its click
            className={`absolute inset-y-0.5 flex touch-none items-center overflow-hidden rounded-sm border px-1.5 text-left text-[10px] leading-tight ${
              p.locked ? "cursor-pointer" : dragging ? "cursor-grabbing" : "cursor-grab"
            } ${
              b.ownScreen
                ? "bg-violet-500/30 border-violet-400/40 text-violet-100"
                : "bg-emerald-500/25 border-emerald-400/40 text-emerald-100"
            } ${active ? "ring-2 ring-amber-400" : ""}`}
            style={{
              left: timeToPx(win.start, p.pps),
              width: Math.max(3, timeToPx(win.end - win.start, p.pps)),
            }}
            title={p.locked
              ? `${b.kind} · ${b.label} — view only while Sniper works`
              : `${b.kind} · ${b.label} — drag to move, edges to trim (Alt = no snap)`}
          >
            <span className="pointer-events-none truncate select-none">{b.label}</span>
            <div
              onPointerDown={(e) => begin(e, b, "trim-start")}
              className="absolute inset-y-0 left-0 w-1.5 cursor-ew-resize touch-none border-l-2 border-transparent hover:border-amber-300/80"
            />
            <div
              onPointerDown={(e) => begin(e, b, "trim-end")}
              className="absolute inset-y-0 right-0 w-1.5 cursor-ew-resize touch-none border-r-2 border-transparent hover:border-amber-300/80"
            />
          </div>
        );
      })}
      {drag?.moved && (
        <div
          className="pointer-events-none absolute top-0 z-20 whitespace-nowrap rounded border border-neutral-700 bg-neutral-950/95 px-1.5 text-[10px] leading-4 text-neutral-100"
          style={{ left: timeToPx(drag.live.start, p.pps) }}
        >
          {fmtWindow(drag.live)}
          {drag.snapped != null && <span className="text-amber-300"> ⌁{drag.snapped.toFixed(2)}s</span>}
        </div>
      )}
    </>
  );
}
