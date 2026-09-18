"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { CropRect, CutSegment } from "@/lib/producer/edit-plan";
import { outputToSource } from "@/lib/producer/edit-plan";
import {
  aspectK,
  cellDims,
  centeredCrop,
  fitToAspect,
  moveCrop,
  resizeCrop,
  type CellRegion,
  type Dims,
  type Handle,
} from "@/lib/producer/crop-geometry";

interface Props {
  dir: string;
  cutTrack: CutSegment[];
  playhead: number; // OUTPUT seconds — mapped through outputToSource for the frame
  region: CellRegion;
  frac: number; // current split frac (the lock is computed from it)
  initial?: CropRect;
  onApply: (rect: CropRect) => void;
  onClose: () => void;
}

const LABELS: Record<CellRegion, string> = {
  fill: "Fill crop",
  top: "Top cell (person)",
  bottom: "Bottom cell (screen)",
};

// Handle table (data): position + cursor per resize handle.
const HANDLES: { id: Handle; cursor: string; style: React.CSSProperties }[] = [
  { id: "nw", cursor: "nwse-resize", style: { left: -5, top: -5 } },
  { id: "n", cursor: "ns-resize", style: { left: "calc(50% - 5px)", top: -5 } },
  { id: "ne", cursor: "nesw-resize", style: { right: -5, top: -5 } },
  { id: "e", cursor: "ew-resize", style: { right: -5, top: "calc(50% - 5px)" } },
  { id: "se", cursor: "nwse-resize", style: { right: -5, bottom: -5 } },
  { id: "s", cursor: "ns-resize", style: { left: "calc(50% - 5px)", bottom: -5 } },
  { id: "sw", cursor: "nesw-resize", style: { left: -5, bottom: -5 } },
  { id: "w", cursor: "ew-resize", style: { left: -5, top: "calc(50% - 5px)" } },
];

const pct = (n: number) => `${n * 100}%`;

// CROP MODAL — a SOURCE video frame with a draggable + resizable rect,
// ASPECT-LOCKED to the target cell's output shape so the box previews exactly
// what the viewer sees (the renderer COVERS the cell, never letterboxes).
// All drag math lives in pure functions in lib/producer/crop-geometry.ts.
export default function CropModal({
  dir,
  cutTrack,
  playhead,
  region,
  frac,
  initial,
  onApply,
  onClose,
}: Props) {
  // Frame time: current playhead mapped to SOURCE seconds; falls back to t=0
  // when the playhead maps to cut material (before 0 / past the last segment).
  // The mapping also names WHICH source the playhead is on — passed to the
  // frame route so a multi-source plan previews the right footage (no
  // sourceId = the route's default, manifest.sources[0]).
  const mapped = useMemo(() => outputToSource(cutTrack, playhead), [cutTrack, playhead]);
  const tSrc = mapped?.tSrc ?? 0;
  const sourceId = mapped?.sourceId ?? null;

  const cell = useMemo(() => cellDims(region, frac), [region, frac]);
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [src, setSrc] = useState<Dims | null>(null);
  const [crop, setCrop] = useState<CropRect | null>(null);
  const [error, setError] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ kind: "move" | Handle; x: number; y: number; rect: CropRect } | null>(null);

  const k = src ? aspectK(cell, src) : null;

  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    (async () => {
      try {
        const sid = sourceId ? `&sourceId=${encodeURIComponent(sourceId)}` : "";
        const res = await fetch(
          `/api/producer/source-frame?dir=${encodeURIComponent(dir)}&t=${tSrc.toFixed(2)}${sid}`,
        );
        if (!res.ok) {
          const e = (await res.json().catch(() => ({}))) as { error?: string };
          throw new Error(e.error || `source-frame ${res.status}`);
        }
        const dims = res.headers.get("X-Source-Dims") || "";
        const [w, h] = dims.split("x").map(Number);
        if (!w || !h) throw new Error(`bad X-Source-Dims header: "${dims}"`);
        url = URL.createObjectURL(await res.blob());
        if (cancelled) {
          URL.revokeObjectURL(url); // cleanup already ran with url unset
          return;
        }
        setSrc({ w, h });
        setImgUrl(url);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "failed to load frame");
      }
    })();
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [dir, tSrc, sourceId]);

  // Seed the rect once dims (→ the lock) are known: incoming value conformed
  // to the CURRENT lock, else the largest centered default.
  useEffect(() => {
    if (k == null) return;
    setCrop(initial ? fitToAspect(initial, k) : centeredCrop(k));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [k == null]);

  const beginDrag = (e: React.PointerEvent, kind: "move" | Handle) => {
    if (!crop) return;
    e.preventDefault();
    e.stopPropagation();
    (e.target as Element).setPointerCapture(e.pointerId);
    dragRef.current = { kind, x: e.clientX, y: e.clientY, rect: crop };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    const box = boxRef.current?.getBoundingClientRect();
    if (!d || !box || k == null) return;
    const dx = (e.clientX - d.x) / box.width;
    const dy = (e.clientY - d.y) / box.height;
    setCrop(d.kind === "move" ? moveCrop(d.rect, dx, dy) : resizeCrop(d.rect, d.kind, { dx, dy }, k));
  };

  const reset = () => {
    if (k == null) return;
    setCrop(initial ? fitToAspect(initial, k) : centeredCrop(k));
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6">
      <div className="flex max-h-full w-fit max-w-[80vw] flex-col rounded-lg border border-neutral-800 bg-neutral-950 shadow-xl">
        <div className="flex items-center justify-between border-b border-neutral-800 px-4 py-2.5">
          <div>
            <span className="text-sm text-neutral-100">{LABELS[region]}</span>
            <span className="ml-2 font-mono text-[10px] text-neutral-500">
              cell {cell.w}×{cell.h}
            </span>
          </div>
          <button onClick={onClose} className="text-neutral-500 hover:text-neutral-200" aria-label="Close">
            ✕
          </button>
        </div>

        <div className="flex min-h-[200px] items-center justify-center bg-black p-4">
          {error && <p className="max-w-md text-xs text-rose-300">{error}</p>}
          {!error && !imgUrl && <p className="text-xs text-neutral-500">Loading source frame…</p>}
          {imgUrl && (
            <div
              ref={boxRef}
              className="relative inline-block touch-none select-none overflow-hidden"
              onPointerMove={onPointerMove}
              onPointerUp={() => (dragRef.current = null)}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={imgUrl}
                alt={`source frame @ ${tSrc.toFixed(1)}s`}
                draggable={false}
                className="block max-h-[56vh] max-w-[70vw]"
              />
              {crop && (
                <div
                  className="absolute cursor-move border border-white/90"
                  style={{
                    left: pct(crop[0]),
                    top: pct(crop[1]),
                    width: pct(crop[2]),
                    height: pct(crop[3]),
                    boxShadow: "0 0 0 9999px rgba(0,0,0,0.55)",
                  }}
                  onPointerDown={(e) => beginDrag(e, "move")}
                >
                  {HANDLES.map((h) => (
                    <div
                      key={h.id}
                      onPointerDown={(e) => beginDrag(e, h.id)}
                      className="absolute h-2.5 w-2.5 rounded-[1px] border border-neutral-900 bg-white"
                      style={{ ...h.style, cursor: h.cursor }}
                    />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-4 border-t border-neutral-800 px-4 py-2.5">
          <div className="font-mono text-[10px] text-neutral-500">
            {crop
              ? `x ${crop[0].toFixed(3)} · y ${crop[1].toFixed(3)} · w ${crop[2].toFixed(3)} · h ${crop[3].toFixed(3)}`
              : "—"}
            <span className="ml-3 text-neutral-600">
              frame @ {tSrc.toFixed(1)}s · src {sourceId ?? "first (default)"}
              {mapped ? "" : " (playhead is cut material — showing t=0)"}
            </span>
          </div>
          <div className="flex gap-2">
            <button
              onClick={reset}
              disabled={!crop}
              className="rounded border border-neutral-700 px-2.5 py-1 text-xs text-neutral-300 enabled:hover:bg-neutral-800 disabled:opacity-40"
            >
              Reset
            </button>
            <button
              onClick={onClose}
              className="rounded border border-neutral-700 px-2.5 py-1 text-xs text-neutral-300 hover:bg-neutral-800"
            >
              Cancel
            </button>
            <button
              onClick={() => crop && onApply(crop)}
              disabled={!crop}
              className="rounded border border-emerald-500/40 px-2.5 py-1 text-xs text-emerald-200 enabled:hover:bg-emerald-500/10 disabled:opacity-40"
            >
              Apply
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
