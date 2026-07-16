"use client";

import { useEffect } from "react";
import type { CompCanvas, CompCatalogEntry } from "@/lib/producer/comps-catalog";
import { AddAtPlayheadButton, ElementBadges, ElementPreview, type PreviewLoop } from "./element-preview";

// SHOWCASE — the template-gallery expand. Clicking a card's PREVIEW (not its
// Add button) opens this centered overlay: the comp animating at readable size
// plus label, description, canvas badges, kind, and the same Add-at-playhead
// action. Canvas-mismatch comps still showcase (seeing them is the point) but
// the insert stays DISABLED — a mismatched comp composites half-frame and the
// fast assemble path has no lint. Esc / backdrop / ✕ close it.

interface Props {
  entry: CompCatalogEntry;
  planCanvas: CompCanvas;
  playhead: number;
  pendingInsert?: { start: number; end: number } | null; // ruler-armed insert window
  loop: PreviewLoop;
  onAdd: (entry: CompCatalogEntry) => void;
  onClose: () => void;
}

function useEscape(onClose: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
}

export default function ElementShowcase({ entry, planCanvas, playhead, pendingInsert, loop, onAdd, onClose }: Props) {
  const wide = entry.canvas === "16:9";
  useEscape(onClose);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6"
      onClick={onClose}
    >
      <div
        className={`max-h-[92vh] overflow-y-auto rounded-lg border border-neutral-700 bg-neutral-950 p-4 shadow-2xl ${
          wide ? "w-[min(880px,90vw)]" : "w-[min(400px,90vw)]"
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-2 flex items-center gap-1.5">
          <span className="text-sm font-medium text-neutral-100">{entry.label}</span>
          <ElementBadges entry={entry} planCanvas={planCanvas} />
          <button onClick={onClose} className="ml-auto text-neutral-500 hover:text-neutral-200" aria-label="Close showcase">
            ✕
          </button>
        </div>
        <ElementPreview
          kind={entry.kind}
          spec={entry.defaultSpec}
          canvas={entry.canvas}
          maxHeight={wide ? 468 : 600}
          loop={loop}
          loopId={`showcase:${entry.kind}`}
        />
        <p className="mt-2 text-xs leading-snug text-neutral-400">{entry.description}</p>
        <div className="mt-3 flex items-center justify-between">
          <span className="font-mono text-[10px] text-neutral-600">{entry.kind}</span>
          <AddAtPlayheadButton
            entry={entry}
            planCanvas={planCanvas}
            playhead={playhead}
            pendingInsert={pendingInsert}
            onAdd={(e) => {
              onAdd(e);
              onClose();
            }}
            className="px-2.5 py-1 text-xs"
          />
        </div>
      </div>
    </div>
  );
}
