"use client";

import { useState } from "react";
import AudioPanel from "./audio-panel";
import ElementsPanel from "./elements-panel";
import LayoutPanel from "./layout-panel";
import type { EditPlan } from "@/lib/producer/edit-plan";
import type { Win } from "@/lib/producer/timeline-scale";
import { planCanvas, type CompCatalogEntry } from "@/lib/producer/comps-catalog";

type PanelId = "audio" | "elements" | "layout";

const PANELS: { id: PanelId; label: string; icon: string }[] = [
  { id: "audio", label: "Audio", icon: "♪" },
  { id: "elements", label: "Elements", icon: "▦" },
  { id: "layout", label: "Layout", icon: "◫" },
];

interface Props {
  plan: EditPlan;
  dir: string;
  playhead: number;
  onMutate: (fn: (p: EditPlan) => EditPlan) => void;
  onAddGraphic: (entry: CompCatalogEntry) => void;
  openRequest?: { id: PanelId; nonce: number } | null; // ruler "Add graphic here" opens ELEMENTS
  pendingInsert?: Win | null; // armed insert window (next Add uses it instead of playhead+4)
  onClearPending?: () => void;
  locked?: boolean;
  lockedReason?: string | null;
}

// The right rail + its drawer: click a rail item to open its panel column,
// click again (or ✕) to close. Replaces the Phase-1 placeholder rail.
export default function RightRail({
  plan, dir, playhead, onMutate, onAddGraphic, openRequest, pendingInsert, onClearPending,
  locked, lockedReason,
}: Props) {
  const [open, setOpen] = useState<PanelId | null>(null);

  // External open request (e.g. the ruler's "Add graphic here") — nonce per
  // click so repeating the same request re-opens a closed drawer. Render-adjust
  // pattern (state derived from a prop change), not an effect.
  const [seenNonce, setSeenNonce] = useState<number | null>(null);
  if (openRequest && openRequest.nonce !== seenNonce) {
    setSeenNonce(openRequest.nonce);
    setOpen(openRequest.id);
  }

  return (
    <>
      {open && (
        <aside className="flex w-80 shrink-0 flex-col border-l border-neutral-800 bg-neutral-950">
          <div className="flex h-9 shrink-0 items-center justify-between border-b border-neutral-800 px-3">
            <span className="text-[10px] uppercase tracking-wide text-neutral-400">
              {PANELS.find((p) => p.id === open)?.label}
            </span>
            <button
              onClick={() => setOpen(null)}
              className="text-neutral-500 hover:text-neutral-200"
              aria-label="Close panel"
            >
              ✕
            </button>
          </div>
          {locked && (
            <p className="border-b border-amber-500/20 px-3 py-2 text-[10px] text-amber-300">
              {lockedReason ?? "View only while another workflow owns timeline changes."}
            </p>
          )}
          <div className={`min-h-0 flex-1 overflow-y-auto ${locked ? "pointer-events-none opacity-60" : ""}`}>
            {open === "audio" && <AudioPanel plan={plan} onMutate={onMutate} />}
            {open === "elements" && (
              <ElementsPanel
                playhead={playhead}
                canvas={planCanvas(plan.target)}
                onAdd={onAddGraphic}
                pendingInsert={pendingInsert}
                onClearPending={onClearPending}
              />
            )}
            {open === "layout" && (
              <LayoutPanel plan={plan} dir={dir} playhead={playhead} onMutate={onMutate} />
            )}
          </div>
        </aside>
      )}

      <aside className="flex w-16 shrink-0 flex-col items-center gap-3 border-l border-neutral-800 py-4">
        {PANELS.map((p) => {
          const active = open === p.id;
          return (
            <button
              key={p.id}
              onClick={() => setOpen(active ? null : p.id)}
              className="flex flex-col items-center gap-0.5 text-[9px]"
            >
              <span
                className={`flex h-7 w-7 items-center justify-center rounded-md border text-xs ${
                  active
                    ? "border-emerald-500/60 bg-emerald-500/15 text-emerald-300"
                    : "border-neutral-800 bg-neutral-900 text-neutral-400"
                }`}
              >
                {p.icon}
              </span>
              <span className={active ? "text-emerald-300" : "text-neutral-500"}>{p.label}</span>
            </button>
          );
        })}
      </aside>
    </>
  );
}
