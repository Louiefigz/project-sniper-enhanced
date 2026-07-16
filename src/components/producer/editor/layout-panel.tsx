"use client";

import { useEffect, useRef, useState } from "react";
import CropModal from "./crop-modal";
import type { CropRect, EditPlan, ReframeSpec } from "@/lib/producer/edit-plan";
import { aspectK, cellDims, centeredCrop, type CellRegion, type Dims } from "@/lib/producer/crop-geometry";
import { planCanvas } from "@/lib/producer/comps-catalog";

interface Props {
  plan: EditPlan;
  dir: string;
  playhead: number;
  onMutate: (fn: (p: EditPlan) => EditPlan) => void;
}

const REBUILD_HINT = "layout changes re-render the base (~3 min)";
const FRAC_DEFAULT = 0.5;

function Hint({ text }: { text: string }) {
  return <p className="mt-1 text-[10px] leading-snug text-neutral-500">{text}</p>;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-b border-neutral-800 px-3 py-3">
      <div className="mb-2 text-[10px] uppercase tracking-wide text-neutral-500">{title}</div>
      {children}
    </div>
  );
}

function EditCropButton({ onClick, disabled }: { onClick: () => void; disabled: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="rounded border border-neutral-700 px-2 py-0.5 text-[11px] text-neutral-200 enabled:hover:bg-neutral-800 disabled:opacity-40"
    >
      Edit crop
    </button>
  );
}

/** Deterministic default split: centered crops for each cell at frac 0.5. */
function defaultSplit(src: Dims): NonNullable<ReframeSpec["split"]> {
  return {
    top: { crop: centeredCrop(aspectK(cellDims("top", FRAC_DEFAULT), src)), frac: FRAC_DEFAULT },
    bottom: { crop: centeredCrop(aspectK(cellDims("bottom", FRAC_DEFAULT), src)) },
  };
}

// LAYOUT panel — the Fill | Split control over plan.reframe (undo-covered via
// mutatePlan). Split is a 9:16-shorts move (top = person, bottom = screen);
// on a longform (16:9) plan the control is disabled with an honest hint.
// Geometry defaults need the SOURCE dims, fetched once via the source-frame
// route (header only, the jpeg is cached server-side).
export default function LayoutPanel({ plan, dir, playhead, onMutate }: Props) {
  const [src, setSrc] = useState<Dims | null>(null);
  const [srcError, setSrcError] = useState<string | null>(null);
  const [modal, setModal] = useState<CellRegion | null>(null);
  // Slider value lives locally while dragging; committed to the plan on
  // release so one drag = ONE undo entry, not eight.
  const [fracDraft, setFracDraft] = useState<number | null>(null);
  // Fields the OTHER layout owns, stashed on a switch so toggling back within
  // the session restores them. plan_lint_reframe.py rejects cross-layout
  // leftovers (strategy/crop under 'split', split under 'fill'), so they must
  // leave the plan — they only survive here, in component state.
  const stashRef = useRef<{ strategy?: string; crop?: CropRect; split?: ReframeSpec["split"] }>({});

  const longform = plan.target?.mode === "longform";
  const reframe = plan.reframe ?? {};
  const layout = reframe.layout ?? "fill";
  const frac = reframe.split?.top?.frac ?? FRAC_DEFAULT;
  const shownFrac = fracDraft ?? frac;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/producer/source-frame?dir=${encodeURIComponent(dir)}&t=0`);
        if (!res.ok) {
          const e = (await res.json().catch(() => ({}))) as { error?: string };
          throw new Error(e.error || `source-frame ${res.status}`);
        }
        const [w, h] = (res.headers.get("X-Source-Dims") || "").split("x").map(Number);
        if (!w || !h) throw new Error("bad X-Source-Dims header");
        if (!cancelled) setSrc({ w, h });
      } catch (e) {
        if (!cancelled) setSrcError(e instanceof Error ? e.message : "source dims unavailable");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [dir]);

  // Switching layouts must leave ONLY the incoming layout's fields in the plan
  // (lint: strategy/crop are fill-only, split is split-only). The outgoing
  // layout's fields are stashed locally and restored on toggle-back; on a
  // fresh load fill simply reverts to the automatic face path.
  const setLayout = (next: "fill" | "split") => {
    if (next === layout) return;
    const stash = stashRef.current;
    if (next === "split") {
      stash.strategy = reframe.strategy;
      stash.crop = reframe.crop;
    } else {
      stash.split = reframe.split;
    }
    onMutate((p) => {
      const r: ReframeSpec = { ...p.reframe, layout: next };
      delete r.strategy;
      delete r.crop;
      delete r.split;
      if (next === "split") {
        const split = p.reframe?.split ?? stash.split ?? (src ? defaultSplit(src) : undefined);
        if (split) r.split = split;
      } else {
        if (stash.strategy !== undefined) r.strategy = stash.strategy;
        if (stash.crop !== undefined) r.crop = stash.crop;
      }
      return { ...p, reframe: r };
    });
  };

  const commitFrac = (f: number) => {
    setFracDraft(null);
    if (f === frac) return;
    onMutate((p) => {
      const s = p.reframe?.split ?? {};
      return {
        ...p,
        reframe: { ...p.reframe, split: { ...s, top: { ...s.top, frac: f } } },
      };
    });
  };

  const applyCrop = (region: CellRegion, rect: CropRect) => {
    onMutate((p) => {
      if (region === "fill") return { ...p, reframe: { ...p.reframe, crop: rect } };
      const s = p.reframe?.split ?? {};
      return {
        ...p,
        reframe: { ...p.reframe, split: { ...s, [region]: { ...s[region], crop: rect } } },
      };
    });
  };

  const clearFillCrop = () =>
    onMutate((p) => {
      const r = { ...p.reframe };
      delete r.crop;
      return { ...p, reframe: r };
    });

  const disabled = longform || !src;

  return (
    <div className="text-sm">
      <Section title="Layout">
        <div className="flex overflow-hidden rounded border border-neutral-700 text-xs">
          {(["fill", "split"] as const).map((id) => (
            <button
              key={id}
              onClick={() => setLayout(id)}
              disabled={disabled}
              className={`flex-1 px-2 py-1 capitalize disabled:opacity-40 ${
                layout === id ? "bg-emerald-500/15 text-emerald-300" : "text-neutral-400 enabled:hover:bg-neutral-800"
              }`}
            >
              {id}
            </button>
          ))}
        </div>
        {longform && <Hint text={`Split is for 9:16 shorts — this plan is ${planCanvas(plan.target)}`} />}
        {!longform && srcError && <Hint text={`Source dims failed: ${srcError}`} />}
        {!longform && !src && !srcError && <Hint text="loading source dims…" />}
        <Hint text={REBUILD_HINT} />
      </Section>

      {layout === "fill" && (
        <Section title="Fill crop">
          <div className="flex items-center gap-2">
            <EditCropButton onClick={() => setModal("fill")} disabled={disabled} />
            {reframe.crop && (
              <button
                onClick={clearFillCrop}
                disabled={longform}
                className="rounded border border-neutral-700 px-2 py-0.5 text-[11px] text-neutral-400 enabled:hover:bg-neutral-800 disabled:opacity-40"
              >
                Auto (face)
              </button>
            )}
          </div>
          <Hint
            text={
              reframe.crop
                ? "manual crop set — Auto (face) returns to the automatic face crop"
                : "automatic face crop — Edit crop overrides it"
            }
          />
        </Section>
      )}

      {layout === "split" && (
        <Section title="Split cells">
          <div className="flex gap-3">
            <div
              className="flex w-9 shrink-0 flex-col overflow-hidden rounded border border-neutral-700"
              style={{ height: 96 }}
              aria-label="stacked preview"
            >
              <div className="bg-emerald-500/25" style={{ height: `${shownFrac * 100}%` }} />
              <div className="flex-1 bg-sky-500/25" />
            </div>
            <div className="flex flex-1 flex-col justify-between gap-2 text-xs text-neutral-300">
              <div className="flex items-center justify-between gap-2">
                <span>Top (person)</span>
                <EditCropButton onClick={() => setModal("top")} disabled={disabled} />
              </div>
              <div className="flex items-center justify-between gap-2">
                <span>Bottom (screen)</span>
                <EditCropButton onClick={() => setModal("bottom")} disabled={disabled} />
              </div>
              <label className="flex items-center gap-2">
                <span className="shrink-0 text-neutral-400">Top height</span>
                <input
                  type="range"
                  min={0.3}
                  max={0.7}
                  step={0.05}
                  value={shownFrac}
                  disabled={disabled}
                  onChange={(e) => setFracDraft(parseFloat(e.target.value))}
                  onPointerUp={(e) => commitFrac(parseFloat((e.target as HTMLInputElement).value))}
                  onKeyUp={(e) => commitFrac(parseFloat((e.target as HTMLInputElement).value))}
                  className="w-full accent-emerald-500"
                />
                <span className="w-8 text-right font-mono text-[10px]">{Math.round(shownFrac * 100)}%</span>
              </label>
            </div>
          </div>
          <Hint text="frac = top cell's share of output height (0.3–0.7)" />
        </Section>
      )}

      {modal && (
        <CropModal
          dir={dir}
          cutTrack={plan.cutTrack ?? []}
          playhead={playhead}
          region={modal}
          frac={shownFrac}
          initial={modal === "fill" ? reframe.crop : reframe.split?.[modal]?.crop}
          onApply={(rect) => {
            applyCrop(modal, rect);
            setModal(null);
          }}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}
