"use client";

import { useState } from "react";
import {
  SCALE_MAX,
  scaleFromCornerDrag,
  scaledContentRect,
  type CanvasDims,
  type Placement,
  type ScaleCorner,
  type SnappedScale,
} from "@/lib/producer/placement-geometry";

// CORNER SCALE GRIPS on the selected draggable graphic preview: an outline
// around the (scaled) content bbox with four corner grips. Dragging a grip is
// a uniform scale about the PLACEMENT PIN (the content top-left — the renderer
// keeps it pinned at placement {x, y}, so scaling never moves the pin), with a
// live "128%" tooltip, a soft snap at 100% (±3%, Alt disables) and the
// [0.25, 1.5] clamp surfaced as min/max when the cap is hit. The math is pure
// (placement-geometry.scaleFromCornerDrag, tsx-tested); this component owns
// only the pointer state. Release → ONE onCommit (the parent's single
// mutatePlan — undo = the whole gesture). Grips stop pointerdown propagation
// so the wrapper's move-drag never starts under a scale gesture; dblclick
// still bubbles, so double-click-to-reset (clears placement AND scale) works
// on a grip too.

interface Props {
  pin: Placement; // content top-left pin (canvas px): placement, or the measured origin when unplaced
  content: CanvasDims; // UNSCALED content bbox size (canvas px)
  scale: number; // scale to display (gesture live ?? committed)
  base: number; // committed scale at gesture start
  canvas: CanvasDims;
  box: { width: number; height: number }; // the <video> display box
  onLive: (s: SnappedScale | null) => void; // live gesture scale; null = gesture over
  onCommit: (s: SnappedScale) => void; // release → ONE plan commit
}

const CORNERS: ScaleCorner[] = ["tl", "tr", "bl", "br"];

interface Gesture {
  pointerId: number;
  corner: ScaleCorner;
  originX: number;
  originY: number;
  live: SnappedScale | null; // null until the 3px threshold — a click, not a scale
}

export default function ScaleHandles({ pin, content, scale, base, canvas, box, onLive, onCommit }: Props) {
  const [g, setG] = useState<Gesture | null>(null);
  const sx = box.width / canvas.w;
  const sy = box.height / canvas.h;
  const r = scaledContentRect(pin, content, scale);
  const rect = { left: r.left * sx, top: r.top * sy, width: r.width * sx, height: r.height * sy };

  const down = (corner: ScaleCorner) => (e: React.PointerEvent) => {
    e.stopPropagation(); // the wrapper owns move-drag; the grips own scale
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    setG({ pointerId: e.pointerId, corner, originX: e.clientX, originY: e.clientY, live: null });
  };
  const move = (e: React.PointerEvent) => {
    if (!g || e.pointerId !== g.pointerId) return;
    e.stopPropagation();
    const dxPx = e.clientX - g.originX;
    const dyPx = e.clientY - g.originY;
    if (!g.live && Math.hypot(dxPx, dyPx) < 3) return; // click, not a scale (yet)
    const live = scaleFromCornerDrag({ base, corner: g.corner, dxPx, dyPx, content, canvas, box, snap: !e.altKey });
    setG({ ...g, live });
    onLive(live);
  };
  const end = (e: React.PointerEvent, cancel = false) => {
    if (!g || e.pointerId !== g.pointerId) return;
    e.stopPropagation();
    if (g.live && !cancel) onCommit(g.live); // ONE mutatePlan per gesture
    setG(null);
    onLive(null);
  };

  return (
    <>
      <div
        className="pointer-events-none absolute rounded-sm border border-sky-400/60"
        style={rect}
      />
      {CORNERS.map((c) => (
        <div
          key={c}
          onPointerDown={down(c)}
          onPointerMove={move}
          onPointerUp={(e) => end(e)}
          onPointerCancel={(e) => end(e, true)}
          title="drag to scale (Alt = no snap) · double-click = auto position"
          className="absolute z-10 h-3 w-3 -translate-x-1/2 -translate-y-1/2 touch-none rounded-[3px] border border-sky-300 bg-neutral-950 hover:bg-sky-500/40"
          style={{
            left: rect.left + (c === "tr" || c === "br" ? rect.width : 0),
            top: rect.top + (c === "bl" || c === "br" ? rect.height : 0),
            cursor: c === "tl" || c === "br" ? "nwse-resize" : "nesw-resize",
          }}
        />
      ))}
      {g?.live && (
        <span
          className="pointer-events-none absolute z-10 -translate-x-1/2 whitespace-nowrap rounded border border-neutral-700 bg-neutral-950/95 px-1.5 py-0.5 text-[10px] text-neutral-100"
          style={{ left: rect.left + rect.width / 2, top: Math.max(2, rect.top - 24) }}
        >
          {Math.round(g.live.s * 100)}%{g.live.snapped && <span className="text-amber-300">⌁</span>}
          {g.live.capped && (
            <span className="text-rose-300"> {g.live.s === SCALE_MAX ? "max" : "min"}</span>
          )}
        </span>
      )}
    </>
  );
}
