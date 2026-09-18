"use client";

import { useRef, useState } from "react";
import {
  fmtMmSs,
  pxToTime,
  tickStep,
  timeToPx,
  type Win,
} from "@/lib/producer/timeline-scale";

// The timeline ruler: ticks at a zoom-aware step, click to seek, and DRAG to
// range-select a span of the output. The selection itself (Win in output
// seconds) is owned by timeline.tsx — this file owns the drag gesture, the
// tick rendering (visible window only — a zoomed 10-min video would otherwise
// mount thousands of ticks), and the floating action bar component.

interface RulerProps {
  duration: number;
  pps: number;
  scrollLeft: number;
  viewportPx: number;
  onSeek: (t: number) => void;
  onSelectionChange: (sel: Win | null) => void;
}

const fmtTick = (t: number): string => (t >= 60 ? fmtMmSs(t) : `${+t.toFixed(2)}s`);

function visibleTicks(p: RulerProps): number[] {
  const step = tickStep(p.pps);
  const t0 = Math.max(step, Math.ceil(pxToTime(p.scrollLeft - 80, p.pps) / step) * step);
  const t1 = Math.min(p.duration, pxToTime(p.scrollLeft + p.viewportPx + 80, p.pps));
  const out: number[] = [];
  for (let t = t0; t < t1; t += step) out.push(+t.toFixed(4));
  return out;
}

export default function TimelineRuler(p: RulerProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ pointerId: number; t0: number; moved: boolean } | null>(null);

  const tAt = (clientX: number): number => {
    const rect = ref.current!.getBoundingClientRect();
    return Math.max(0, Math.min(p.duration, pxToTime(clientX - rect.left, p.pps)));
  };

  const down = (e: React.PointerEvent) => {
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    setDrag({ pointerId: e.pointerId, t0: tAt(e.clientX), moved: false });
  };
  const move = (e: React.PointerEvent) => {
    if (!drag || e.pointerId !== drag.pointerId) return;
    const t = tAt(e.clientX);
    if (!drag.moved && Math.abs(timeToPx(t - drag.t0, p.pps)) < 3) return;
    if (!drag.moved) setDrag({ ...drag, moved: true });
    p.onSelectionChange({ start: Math.min(drag.t0, t), end: Math.max(drag.t0, t) });
  };
  const up = (e: React.PointerEvent) => {
    if (!drag || e.pointerId !== drag.pointerId) return;
    if (!drag.moved) {
      p.onSeek(drag.t0); // plain click = seek
      p.onSelectionChange(null);
    }
    setDrag(null);
  };

  return (
    <div
      ref={ref}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={up}
      title="click to seek · drag to select a range"
      className="relative mb-1 h-4 w-full cursor-crosshair touch-none select-none text-[10px] text-neutral-500"
    >
      {visibleTicks(p).map((t) => (
        <span key={t} className="absolute -translate-x-1/2" style={{ left: timeToPx(t, p.pps) }}>
          {fmtTick(t)}
        </span>
      ))}
    </div>
  );
}

// ---- floating action bar over an active range selection ----

interface BarProps {
  sel: Win;
  left: number; // px inside the timeline root (already clamped by the caller)
  onCut: () => void;
  onAsk: () => void;
  onAddGraphic: () => void;
  onZoom: () => void;
  onClear: () => void;
}

const BTN = "rounded border border-neutral-700 px-2 py-0.5 text-[11px] text-neutral-200 hover:bg-neutral-800";

export function RangeActionBar(b: BarProps) {
  return (
    // top-9 = just below the h-8 timeline header, floating over the ruler
    <div
      className="absolute top-9 z-30 flex -translate-x-1/2 items-center gap-1.5 rounded-md border border-neutral-700 bg-neutral-950/95 px-2 py-1 shadow-lg"
      style={{ left: b.left }}
    >
      <span className="text-[11px] text-sky-300">
        {fmtMmSs(b.sel.start)}–{fmtMmSs(b.sel.end)}
      </span>
      <button onClick={b.onCut} title="Remove this span from the cut (same semantics as strike-to-cut; spans crossing a cut seam remove each source sub-range)" className={`${BTN} border-rose-500/40 text-rose-300 hover:bg-rose-500/10`}>
        Cut section
      </button>
      <button onClick={b.onAsk} title="Prefill the Ask-editor bar with this range" className={BTN}>
        Describe change
      </button>
      <button onClick={b.onAddGraphic} title="Open the Elements panel — the next Add inserts into this window" className={BTN}>
        Add graphic here
      </button>
      <button onClick={b.onZoom} title="Zoom the timeline to this selection" className={BTN}>
        Zoom to selection
      </button>
      <button onClick={b.onClear} title="Clear selection (Esc)" className="px-1 text-neutral-500 hover:text-neutral-200">
        ✕
      </button>
    </div>
  );
}
