"use client";

import { useState } from "react";
import { COMPS_CATALOG, CompCanvas, CompCatalogEntry } from "@/lib/producer/comps-catalog";
import type { Win } from "@/lib/producer/timeline-scale";
import {
  AddAtPlayheadButton,
  ElementBadges,
  ElementPreview,
  usePreviewLoop,
  type PreviewLoop,
} from "./element-preview";
import ElementShowcase from "./element-showcase";

interface Props {
  playhead: number;
  canvas: CompCanvas; // the plan's canvas (longform → 16:9, else 9:16)
  onAdd: (entry: CompCatalogEntry) => void;
  pendingInsert?: Win | null; // ruler-armed window — the next Add inserts here, not playhead+4
  onClearPending?: () => void;
}

// ELEMENTS panel — the curated comp catalog as insertable cards, each with a
// LIVE mini-preview: a sandboxed comp-html iframe animated by the panel's ONE
// shared rAF loop (element-preview.tsx) — only while in view, and the whole
// drawer unmounts on close, so nothing burns CPU in the background. Clicking a
// preview opens the SHOWCASE overlay (element-showcase.tsx) — browse elements
// like a template gallery. "Add at playhead" drops a 4s graphicsTrack entry at
// the current time with the catalog's placeholder spec, then the properties
// panel opens for text edits. Own-screen kinds are flagged: they hard-cut the
// full frame (cutaway), not an overlay. Comps authored on the OTHER canvas
// stay visible — preview included, seeing them is the point — but their insert
// is DISABLED: a mismatched comp would composite half-frame (the fast assemble
// path has no lint), so the panel refuses the insert instead of hiding the
// option. $0 — a direct plan edit; Re-render composites it.
export default function ElementsPanel({ playhead, canvas, onAdd, pendingInsert, onClearPending }: Props) {
  const loop = usePreviewLoop();
  const [showcase, setShowcase] = useState<CompCatalogEntry | null>(null);
  // Sectioned groups (slideware reference pack, module card pack, then raw
  // primitives) follow dividers so the curated designed comps stay the
  // first read.
  const comps = COMPS_CATALOG.filter((c) => !c.section);
  const slideware = COMPS_CATALOG.filter((c) => c.section === "slideware");
  const moduleCards = COMPS_CATALOG.filter((c) => c.section === "module");
  const primitives = COMPS_CATALOG.filter((c) => c.section === "primitives");
  const card = (c: CompCatalogEntry) => (
    <ElementCard
      key={c.kind}
      entry={c}
      planCanvas={canvas}
      playhead={playhead}
      pendingInsert={pendingInsert}
      loop={loop}
      onAdd={onAdd}
      onExpand={() => setShowcase(c)}
    />
  );

  return (
    <div className="space-y-2 p-3 text-sm">
      {pendingInsert && (
        <div className="flex items-center justify-between rounded border border-sky-500/40 bg-sky-500/10 px-2 py-1 text-[11px] text-sky-200">
          <span title="set by the ruler's range select — the next Add inserts into this window">
            Insert window: {pendingInsert.start.toFixed(1)}–{pendingInsert.end.toFixed(1)}s
          </span>
          <button onClick={onClearPending} aria-label="Clear insert window" className="text-sky-300 hover:text-sky-100">
            ✕
          </button>
        </div>
      )}
      {comps.map(card)}
      {slideware.length > 0 && (
        <div className="flex items-center gap-2 pt-2 text-[10px] uppercase tracking-wide text-neutral-500">
          <span className="h-px flex-1 bg-neutral-800" />
          Slideware pack
          <span className="h-px flex-1 bg-neutral-800" />
        </div>
      )}
      {slideware.map(card)}
      {moduleCards.length > 0 && (
        <div className="flex items-center gap-2 pt-2 text-[10px] uppercase tracking-wide text-neutral-500">
          <span className="h-px flex-1 bg-neutral-800" />
          Module pack
          <span className="h-px flex-1 bg-neutral-800" />
        </div>
      )}
      {moduleCards.map(card)}
      {primitives.length > 0 && (
        <div className="flex items-center gap-2 pt-2 text-[10px] uppercase tracking-wide text-neutral-500">
          <span className="h-px flex-1 bg-neutral-800" />
          Primitives
          <span className="h-px flex-1 bg-neutral-800" />
        </div>
      )}
      {primitives.map(card)}
      {showcase && (
        <ElementShowcase
          entry={showcase}
          planCanvas={canvas}
          playhead={playhead}
          pendingInsert={pendingInsert}
          loop={loop}
          onAdd={onAdd}
          onClose={() => setShowcase(null)}
        />
      )}
    </div>
  );
}

interface CardProps {
  entry: CompCatalogEntry;
  planCanvas: CompCanvas;
  playhead: number;
  pendingInsert?: Win | null;
  loop: PreviewLoop;
  onAdd: (entry: CompCatalogEntry) => void;
  onExpand: () => void;
}

function ElementCard({ entry: c, planCanvas, playhead, pendingInsert, loop, onAdd, onExpand }: CardProps) {
  const mismatch = c.canvas !== planCanvas;
  return (
    <div className="rounded-md border border-neutral-800 bg-neutral-900/60 p-2.5">
      <div className="mb-1.5 flex items-center gap-1.5">
        <span className={`text-xs font-medium ${mismatch ? "text-neutral-400" : "text-neutral-100"}`}>
          {c.label}
        </span>
        <ElementBadges entry={c} planCanvas={planCanvas} />
      </div>
      <ElementPreview
        kind={c.kind}
        spec={c.defaultSpec}
        canvas={c.canvas}
        maxHeight={190}
        loop={loop}
        loopId={`card:${c.kind}`}
        onClick={onExpand}
        className="mb-1.5"
      />
      <p className={`mb-1.5 text-[11px] leading-snug ${mismatch ? "text-neutral-500" : "text-neutral-400"}`}>
        {c.description}
      </p>
      <div className="flex items-center justify-between">
        <span className="font-mono text-[9px] text-neutral-600">{c.kind}</span>
        <AddAtPlayheadButton
          entry={c}
          planCanvas={planCanvas}
          playhead={playhead}
          pendingInsert={pendingInsert}
          onAdd={onAdd}
          className="px-2 py-0.5 text-[11px]"
        />
      </div>
    </div>
  );
}
