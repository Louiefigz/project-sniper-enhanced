"use client";

import { useRef } from "react";
import type { PunchIn, Transition } from "@/lib/producer/edit-plan";
import { pxToTime, timeToPx } from "@/lib/producer/timeline-scale";

// Presentational timeline lanes (hand-rolled — no timeline dep). Every lane
// lives inside the ONE scrollable content div sized by timeline-scale's
// px↔time transform, so all positions here are `timeToPx(t, pps)` px. Lane
// labels live in the fixed column (timeline.tsx) — these are content-only.

/** Lane shell: click empty space to seek; children are absolute px blocks. */
export function Lane({
  heightClass,
  pps,
  onSeek,
  bgImage,
  children,
}: {
  heightClass: string;
  pps: number;
  onSeek: (t: number) => void;
  bgImage?: string;
  children?: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const seekFromClick = (e: React.MouseEvent) => {
    const el = ref.current;
    if (!el) return;
    onSeek(Math.max(0, pxToTime(e.clientX - el.getBoundingClientRect().left, pps)));
  };
  return (
    <div
      ref={ref}
      onClick={seekFromClick}
      style={bgImage ? { backgroundImage: `url("${bgImage}")`, backgroundSize: "100% 100%" } : undefined}
      className={`relative ${heightClass} w-full cursor-pointer overflow-hidden rounded bg-neutral-900/70`}
    >
      {children}
    </div>
  );
}

/** Cut seams over the filmstrip — where the joins between kept spans land. */
export function CutSeams({
  cuts,
  pps,
}: {
  cuts: { start: number; end: number; sourceId: string }[];
  pps: number;
}) {
  return (
    <>
      {cuts.slice(1).map((c, i) => (
        <div
          key={i}
          className="absolute inset-y-0 w-0.5 -translate-x-1/2 bg-sky-300/80"
          style={{ left: timeToPx(c.start, pps) }}
          title={`cut → ${c.sourceId} @ ${c.start.toFixed(1)}s`}
        />
      ))}
    </>
  );
}

/** Punch-in / creep windows on the Motion lane. */
export function MotionMarks({ punches, pps }: { punches: PunchIn[]; pps: number }) {
  return (
    <>
      {punches.map((p, i) => {
        const isRamp = p.kind === "ramp" || !!p.ramp;
        return (
          <div
            key={i}
            className={`absolute inset-y-1.5 rounded-sm ${isRamp ? "bg-orange-400/25" : "bg-orange-500/50"}`}
            style={{
              left: timeToPx(p.outStart, pps),
              width: Math.max(2, timeToPx(p.outEnd - p.outStart, pps)),
            }}
            title={`${isRamp ? "creep" : `punch ${p.zoom ?? ""}`}  ${p.outStart.toFixed(1)}–${p.outEnd.toFixed(1)}s`}
          />
        );
      })}
    </>
  );
}

/** Transition markers. */
export function TransitionMarks({ transitions, pps }: { transitions: Transition[]; pps: number }) {
  return (
    <>
      {transitions.map((t, i) => (
        <div
          key={i}
          className="absolute inset-y-1 w-0.5 -translate-x-1/2 bg-rose-400"
          style={{ left: timeToPx(t.outTime, pps) }}
          title={`${t.kind} @ ${t.outTime.toFixed(1)}s`}
        />
      ))}
    </>
  );
}

/** The waveform SVG — normalized viewBox, stretches to the zoomed lane width. */
export function WaveformSvg({ peaks }: { peaks: number[] }) {
  return (
    <svg
      className="pointer-events-none absolute inset-0 h-full w-full"
      viewBox={`0 0 ${peaks.length} 100`}
      preserveAspectRatio="none"
    >
      {peaks.map((p, i) => (
        <line
          key={i}
          x1={i + 0.5}
          x2={i + 0.5}
          y1={50 - p * 46}
          y2={50 + p * 46}
          stroke="rgba(110,200,160,0.65)"
          strokeWidth={0.85}
        />
      ))}
    </svg>
  );
}
