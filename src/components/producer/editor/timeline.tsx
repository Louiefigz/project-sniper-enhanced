"use client";

import { useEffect, useState } from "react";
import { EditPlan, cutWindows, graphicBlocks, splitSegmentAt } from "@/lib/producer/edit-plan";
import {
  MAX_PX_PER_SEC,
  contentWidth,
  filmstripCols,
  timeToPx,
  zoomToRange,
  type Win,
} from "@/lib/producer/timeline-scale";
import { useTimelineZoom } from "./use-timeline-zoom";
import { CutSeams, Lane, MotionMarks, TransitionMarks, WaveformSvg } from "./timeline-lanes";
import GraphicsLane from "./timeline-graphics-lane";
import TimelineRuler, { RangeActionBar } from "./timeline-ruler";

// The PRODUCER editor timeline — hand-rolled lanes over ONE shared px↔time
// transform (timeline-scale.ts): zoom (wheel-at-cursor + slider + Fit),
// horizontal scroll, drag/trim graphics blocks (timeline-graphics-lane),
// ruler range-select with the Cut/Ask/Add/Zoom action bar, and a Split-at-
// playhead affordance. All plan edits flow UP through the on* props into
// editor-view's mutatePlan — the timeline never mutates the plan itself.

interface Props {
  plan: EditPlan;
  duration: number;
  currentTime: number;
  onSeek: (t: number) => void;
  selectedGraphic: string | null;
  onSelectGraphic: (id: string | null) => void;
  videoPath?: string; // absolute final.mp4 path → filmstrip + waveform lanes
  vVersion?: number; // bumped per re-render → refetch filmstrip + waveform (server caches by mtime)
  artifactLabel?: string;
  showPlanLanes?: boolean;
  onCommitWindow: (id: string, start: number, end: number) => void; // ONE per drag gesture
  onDragWindow: (w: { id: string; start: number; end: number } | null) => void;
  onSplit: () => void;
  onCutRange: (a: number, b: number) => void;
  onAskRange: (a: number, b: number) => void;
  onAddRange: (a: number, b: number) => void;
  locked?: boolean;
}

const LABEL_OFFSET_PX = 104; // px-4 (16) + w-20 label col (80) + gap-2 (8)

interface HeaderProps {
  pps: number;
  fit: number;
  isFit: boolean;
  canSplit: boolean;
  onSplit: () => void;
  onSlider: (targetPps: number) => void;
  onFit: () => void;
  artifactLabel?: string;
  showPlanLanes: boolean;
}

function TimelineHeader(p: HeaderProps) {
  const { pps, fit, isFit, canSplit, onSplit, onSlider, onFit, artifactLabel, showPlanLanes } = p;
  const min = Math.log(Math.min(fit, MAX_PX_PER_SEC));
  const max = Math.log(MAX_PX_PER_SEC);
  const factor = pps / fit;
  return (
    <div className="flex h-8 items-center gap-3 border-b border-neutral-800/60 px-4">
      <button
        type="button"
        onClick={onSplit}
        disabled={!canSplit}
        title={
          canSplit
            ? "Split the cut segment at the playhead (S) — then range-select either half to remove it"
            : "playhead sits on a cut seam or outside the cut — nothing to split"
        }
        className="rounded border border-neutral-700 px-2 py-0.5 text-[11px] text-neutral-200 enabled:hover:bg-neutral-800 disabled:cursor-not-allowed disabled:text-neutral-600"
      >
        ✂ Split
      </button>
      <span className="hidden select-none text-[10px] text-neutral-600 lg:inline">
        {showPlanLanes
          ? "drag blocks to move · edges to trim · Alt = no snap · drag the ruler to range-select"
          : "read-only reference preview · make timeline changes in Palmier or use Ask AI"}
      </span>
      {artifactLabel && <span className="text-[10px] text-neutral-500">{artifactLabel}</span>}
      <div className="ml-auto flex items-center gap-2">
        <span className="w-10 text-right text-[10px] tabular-nums text-neutral-500">
          {factor < 10 ? factor.toFixed(1) : Math.round(factor)}×
        </span>
        <input
          type="range"
          min={min}
          max={max}
          step={0.01}
          value={Math.log(pps)}
          onChange={(e) => onSlider(Math.exp(parseFloat(e.target.value)))}
          title="zoom (⌘/ctrl+wheel over the timeline zooms at the cursor)"
          className="h-1 w-36 accent-amber-400"
        />
        <button
          type="button"
          onClick={onFit}
          title="Fit the whole video in view"
          className={`rounded border px-2 py-0.5 text-[11px] ${
            isFit ? "border-amber-500/50 text-amber-300" : "border-neutral-700 text-neutral-200 hover:bg-neutral-800"
          }`}
        >
          Fit
        </button>
      </div>
    </div>
  );
}

export default function Timeline(p: Props) {
  const showPlanLanes = p.showPlanLanes !== false;
  const cuts = cutWindows(p.plan);
  const blocks = graphicBlocks(p.plan);
  const { scrollRef, viewportPx, scrollLeft, setScrollLeft, pps, fit, isFit, applyZoom, zoomToFit, sliderZoom } =
    useTimelineZoom(p.duration);
  const [sel, setSel] = useState<Win | null>(null);
  const [peaks, setPeaks] = useState<number[]>([]);

  useEffect(() => {
    if (!p.videoPath) return;
    fetch(`/api/producer/waveform?path=${encodeURIComponent(p.videoPath)}`)
      .then((r) => r.json())
      .then((d) => setPeaks(Array.isArray(d.peaks) ? d.peaks : []))
      .catch(() => setPeaks([]));
  }, [p.videoPath, p.vVersion]);

  // Esc clears the range selection (guarded: not while typing in an input).
  useEffect(() => {
    if (!sel) return;
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el?.tagName === "INPUT" || el?.tagName === "TEXTAREA" || el?.isContentEditable) return;
      if (e.key === "Escape") setSel(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sel]);

  // Filmstrip column count scales with zoom (quantized; capped honestly — see
  // timeline-scale.ts) but the URL only flips once the zoom SETTLES for 250ms:
  // the sprite response is no-store, so oscillating across a quantization
  // boundary mid-pinch would refetch a multi-MB sprite per crossing. Until it
  // settles the old sprite just stretches. &v= busts the cache per re-render.
  const cols = filmstripCols(p.duration, pps);
  const [settledCols, setSettledCols] = useState(cols);
  useEffect(() => {
    if (cols === settledCols) return;
    const id = setTimeout(() => setSettledCols(cols), 250);
    return () => clearTimeout(id);
  }, [cols, settledCols]);
  const filmstrip = p.videoPath
    ? `/api/producer/filmstrip?path=${encodeURIComponent(p.videoPath)}&n=${settledCols}&v=${p.vVersion ?? 0}`
    : undefined;

  const canSplit = !p.locked && splitSegmentAt(p.plan.cutTrack ?? [], p.currentTime) !== null
    && showPlanLanes;
  const widthPx = contentWidth(p.duration, pps);
  // Keep cached peaks for a possible same-authority remount, but never present
  // a waveform while its corresponding video is authority-gated away.
  const visiblePeaks = p.videoPath ? peaks : [];
  const rows = [
    { label: "Video", h: "h-12" },
    ...(showPlanLanes ? [
      { label: "Graphics", h: "h-8" },
      { label: "Motion", h: "h-8", readOnly: true },
      { label: "Transitions", h: "h-8", readOnly: true },
    ] : []),
    ...(visiblePeaks.length > 0 ? [{ label: "Audio", h: "h-10" }] : []),
  ];
  const barLeft = sel
    ? LABEL_OFFSET_PX +
      Math.max(90, Math.min(viewportPx - 90, timeToPx((sel.start + sel.end) / 2, pps) - scrollLeft))
    : 0;

  return (
    <div className="relative border-t border-neutral-800 bg-neutral-950/80">
      <TimelineHeader pps={pps} fit={fit} isFit={isFit} canSplit={canSplit} onSplit={p.onSplit}
        onSlider={sliderZoom} onFit={zoomToFit} artifactLabel={p.artifactLabel}
        showPlanLanes={showPlanLanes} />
      <div className="flex gap-2 px-4 pb-3 pt-2">
        <div className="flex w-20 shrink-0 flex-col">
          <div className="mb-1 h-4" />
          <div className="flex flex-col gap-1.5">
            {rows.map((r) => (
              <div key={r.label} className={`${r.h} flex items-center justify-end`}>
                <span
                  className="flex select-none flex-col items-end text-[10px] uppercase leading-tight tracking-wide text-neutral-500"
                  title={r.readOnly ? `${r.label} markers are a view-only preview` : undefined}
                >
                  {r.label}
                  {r.readOnly && <span className="text-[8px] normal-case tracking-normal text-neutral-600">view only</span>}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div
          ref={scrollRef}
          onScroll={(e) => setScrollLeft(e.currentTarget.scrollLeft)}
          className="relative min-w-0 flex-1 overflow-x-auto overflow-y-hidden"
        >
          <div className="relative" style={{ width: widthPx }}>
            <TimelineRuler
              duration={p.duration}
              pps={pps}
              scrollLeft={scrollLeft}
              viewportPx={viewportPx}
              onSeek={p.onSeek}
              onSelectionChange={setSel}
            />
            <div className="flex flex-col gap-1.5">
              <Lane heightClass="h-12" pps={pps} onSeek={p.onSeek} bgImage={filmstrip}>
                <CutSeams cuts={cuts} pps={pps} />
              </Lane>
              {showPlanLanes && <>
                <Lane heightClass="h-8" pps={pps} onSeek={p.onSeek}>
                  <GraphicsLane
                    blocks={blocks}
                    pps={pps}
                    duration={p.duration}
                    currentTime={p.currentTime}
                    selected={p.selectedGraphic}
                    onSelect={p.onSelectGraphic}
                    onSeek={p.onSeek}
                    onCommitWindow={p.onCommitWindow}
                    onDragWindow={p.onDragWindow}
                    locked={p.locked}
                  />
                </Lane>
                <Lane heightClass="h-8" pps={pps} onSeek={p.onSeek}>
                  <MotionMarks punches={p.plan.punchIns ?? []} pps={pps} />
                </Lane>
                <Lane heightClass="h-8" pps={pps} onSeek={p.onSeek}>
                  <TransitionMarks transitions={p.plan.transitions ?? []} pps={pps} />
                </Lane>
              </>}
              {visiblePeaks.length > 0 && (
                <Lane heightClass="h-10" pps={pps} onSeek={p.onSeek}>
                  <WaveformSvg peaks={visiblePeaks} />
                </Lane>
              )}
            </div>

            <div
              className="pointer-events-none absolute inset-y-0 z-10 w-px bg-amber-400"
              style={{ left: timeToPx(p.currentTime, pps) }}
            >
              <div className="absolute -left-1 top-0 h-2 w-2 rounded-full bg-amber-400" />
            </div>
            {sel && (
              <div
                className="pointer-events-none absolute inset-y-0 z-10 border-x border-sky-400/70 bg-sky-400/10"
                style={{
                  left: timeToPx(sel.start, pps),
                  width: Math.max(2, timeToPx(sel.end - sel.start, pps)),
                }}
              />
            )}
          </div>
        </div>
      </div>

      {sel && showPlanLanes && !p.locked && (
        <RangeActionBar
          sel={sel}
          left={barLeft}
          onCut={() => {
            p.onCutRange(sel.start, sel.end);
            setSel(null);
          }}
          onAsk={() => p.onAskRange(sel.start, sel.end)}
          onAddGraphic={() => {
            p.onAddRange(sel.start, sel.end);
            setSel(null);
          }}
          onZoom={() => applyZoom(zoomToRange(sel.start, sel.end, viewportPx, p.duration))}
          onClear={() => setSel(null)}
        />
      )}
    </div>
  );
}
