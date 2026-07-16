"use client";

import { specFieldsFor } from "@/lib/producer/comps-catalog";
import { GraphicEntry } from "@/lib/producer/edit-plan";
import { SCALE_MAX, SCALE_MIN } from "@/lib/producer/placement-geometry";

interface Props {
  graphic: GraphicEntry;
  id: string; // the graphic's stable id (addressing key — never an array index)
  duration: number; // output duration — bounds the chips + "to end"/"whole video"
  onChange: (id: string, patch: Partial<GraphicEntry>) => void;
  onRemove: (id: string) => void;
  previewForced: boolean; // live comp preview pinned on even outside the window
  onTogglePreview: () => void;
}

// The primary human-editable text key for a graphic, probed in priority order
// (quotes use `words`, lower-thirds `titleBase`, statement cards `text`,
// whiteboard lists `title`, section markers `line1`, stat cards `value`,
// gauges `label`; angela pack: decks `header`, lockups `payload`, captions
// `cue1`, receipt cells `label1`; nateherk pack: cards `headlineLines`
// (pipe-separated thesis lines), scoreboard `heroValue`). null = no free
// text to edit (e.g. icon-badge).
const TEXT_KEYS = ["words", "titleBase", "text", "title", "line1", "value", "label",
  "header", "payload", "cue1", "label1", "headlineLines", "heroValue"] as const;

function textKey(g: GraphicEntry): (typeof TEXT_KEYS)[number] | null {
  const spec = g.spec ?? {};
  for (const k of TEXT_KEYS) if (typeof spec[k] === "string") return k;
  return null;
}

const round2 = (n: number): number => Math.round(n * 100) / 100;

function NumberField({
  label,
  value,
  onCommit,
  int = false, // integer px fields (placement) vs 0.01s time fields
  step,
  min,
  max,
}: {
  label: string;
  value: number;
  onCommit: (n: number) => void;
  int?: boolean;
  step?: number;
  min?: number;
  max?: number;
}) {
  return (
    <label className="flex items-center gap-1.5 text-[11px] text-neutral-400">
      {label}
      <input
        type="number"
        step={step ?? (int ? 1 : 0.1)}
        // Keyed by value (below) so external edits — chips, timeline drags,
        // arrow nudges, preview drags — refresh this uncontrolled input.
        defaultValue={int ? String(Math.round(value)) : value.toFixed(2)}
        onBlur={(e) => {
          const n = parseFloat(e.target.value);
          if (!Number.isFinite(n)) return;
          const c = Math.min(Math.max(n, min ?? -Infinity), max ?? Infinity);
          onCommit(int ? Math.round(c) : c);
        }}
        className="w-16 rounded border border-neutral-700 bg-neutral-900 px-1.5 py-0.5 text-neutral-100"
      />
    </label>
  );
}

/** 5s · 10s · 20s · to end · whole video — same commit path as everything else. */
function DurationChips({ graphic, id, duration, onChange }: Pick<Props, "graphic" | "id" | "duration" | "onChange">) {
  const chip = "rounded border border-neutral-700 px-1.5 py-0.5 text-[10px] text-neutral-300 hover:bg-neutral-800";
  return (
    <div className="flex items-center gap-1">
      {[5, 10, 20].map((s) => (
        <button
          key={s}
          onClick={() => onChange(id, { outEnd: round2(Math.min(duration, graphic.outStart + s)) })}
          title={`${s}s from the in-point`}
          className={chip}
        >
          {s}s
        </button>
      ))}
      <button
        onClick={() => onChange(id, { outEnd: round2(duration) })}
        title="extend to the end of the video"
        className={chip}
      >
        to end
      </button>
      <button
        onClick={() => onChange(id, { outStart: 0, outEnd: round2(duration) })}
        title="cover the whole video"
        className={chip}
      >
        whole video
      </button>
    </div>
  );
}

/**
 * Explicit position (comp-canvas px) + uniform scale (%) — mirrors the
 * preview's drag-to-place and corner grips. Own-screen kinds are full-frame
 * takeovers (never positionable or scalable); placed entries expose x/y/scale
 * + "Auto position" (deletes placement — scale included → anchor fallback);
 * unplaced non-own-screen entries hint at the drag affordance. x/y commits
 * PRESERVE scale; a scale of exactly 100% drops the key (absent = 1.0
 * byte-identical at render).
 */
function PlacementFields({ graphic, id, onChange }: Pick<Props, "graphic" | "id" | "onChange">) {
  if (graphic.anchor === "own-screen") {
    return <span className="text-neutral-600">full-frame (not positionable)</span>;
  }
  const p = graphic.placement;
  if (!p) {
    return (
      <span className="text-neutral-600" title="drag the preview over the video to place this graphic">
        position: auto
      </span>
    );
  }
  const commitScale = (s: number) =>
    onChange(id, { placement: s === 1 ? { x: p.x, y: p.y } : { x: p.x, y: p.y, scale: s } });
  return (
    <>
      <NumberField
        key={`px:${p.x}`}
        label="x"
        value={p.x}
        int
        onCommit={(n) => onChange(id, { placement: { ...p, x: n } })}
      />
      <NumberField
        key={`py:${p.y}`}
        label="y"
        value={p.y}
        int
        onCommit={(n) => onChange(id, { placement: { ...p, y: n } })}
      />
      <NumberField
        key={`ps:${p.scale ?? 1}`}
        label="scale %"
        value={(p.scale ?? 1) * 100}
        int
        min={SCALE_MIN * 100}
        max={SCALE_MAX * 100}
        onCommit={(n) => commitScale(Math.round(n) / 100)}
      />
      {typeof p.scale === "number" && p.scale !== 1 && (
        <button
          onClick={() => commitScale(1)}
          title="reset scale to 100%"
          className="rounded border border-neutral-700 px-1.5 py-0.5 text-[10px] text-neutral-300 hover:bg-neutral-800"
        >
          100%
        </button>
      )}
      <button
        onClick={() => onChange(id, { placement: undefined })}
        title="clear the explicit position (and scale) — placement falls back to the anchor"
        className="rounded border border-neutral-700 px-1.5 py-0.5 text-[10px] text-neutral-300 hover:bg-neutral-800"
      >
        Auto position
      </button>
    </>
  );
}

/**
 * The catalog's extra spec knobs (specFields) rendered generically — number
 * fields clamp to the field's min/max; color fields commit on blur with the
 * same real-change guard as the text input (one undo per picking session).
 */
function SpecFields({ graphic, id, onChange }: Pick<Props, "graphic" | "id" | "onChange">) {
  const spec = graphic.spec ?? {};
  const commit = (key: string, v: unknown) => onChange(id, { spec: { ...spec, [key]: v } });
  return (
    <>
      {specFieldsFor(graphic.kind).map((f) => {
        if (f.type === "color") {
          const val = typeof spec[f.key] === "string" ? (spec[f.key] as string) : "#ffffff";
          return (
            <label key={f.key} className="flex items-center gap-1.5 text-[11px] text-neutral-400">
              {f.label}
              <input
                key={`c:${val}`}
                type="color"
                defaultValue={val}
                onBlur={(e) => e.target.value !== val && commit(f.key, e.target.value)}
                className="h-6 w-9 cursor-pointer rounded border border-neutral-700 bg-neutral-900 p-0.5"
              />
            </label>
          );
        }
        const int = (f.step ?? 1) >= 1;
        const num = typeof spec[f.key] === "number" ? (spec[f.key] as number) : 0;
        return (
          <NumberField
            key={`${f.key}:${num}`}
            label={f.label}
            value={num}
            int={int}
            step={f.step}
            min={f.min}
            max={f.max}
            onCommit={(n) => commit(f.key, n)}
          />
        );
      })}
    </>
  );
}

// Properties panel — direct-manipulation edits (retime / duration chips / edit
// text / remove) mutate the in-memory plan through the editor's ONE commit
// path (mutatePlan); Save writes edit_plan.json. $0, no AI. This is the
// keyboard-precise path; the timeline blocks are the drag path. Preview pins
// the live comp overlay on even when the playhead is outside the window.
export default function GraphicProperties({
  graphic,
  id,
  duration,
  onChange,
  onRemove,
  previewForced,
  onTogglePreview,
}: Props) {
  const key = textKey(graphic);
  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-neutral-800 bg-neutral-900/60 px-4 py-2 text-xs">
      <span className="rounded bg-emerald-500/20 px-2 py-0.5 text-emerald-200">{graphic.kind}</span>
      <button
        onClick={onTogglePreview}
        title="Live comp preview over the video (client-side; the render is the truth). On = shown even outside the graphic's window."
        className={`rounded border px-2 py-0.5 ${
          previewForced
            ? "border-sky-400/60 bg-sky-500/20 text-sky-200"
            : "border-neutral-700 text-neutral-400 hover:bg-neutral-800"
        }`}
      >
        Preview{previewForced ? " on" : ""}
      </button>

      <NumberField
        key={`in:${graphic.outStart}`}
        label="in"
        value={graphic.outStart}
        onCommit={(n) => onChange(id, { outStart: n })}
      />
      <NumberField
        key={`out:${graphic.outEnd}`}
        label="out"
        value={graphic.outEnd}
        onCommit={(n) => onChange(id, { outEnd: n })}
      />

      <DurationChips graphic={graphic} id={id} duration={duration} onChange={onChange} />

      <PlacementFields graphic={graphic} id={id} onChange={onChange} />

      <SpecFields graphic={graphic} id={id} onChange={onChange} />

      {key ? (
        <input
          defaultValue={String((graphic.spec ?? {})[key] ?? "")}
          onBlur={(e) => {
            // Commit ONLY a real change — an untouched blur must not write the
            // (possibly stale) input value into the current graphic's spec.
            if (e.target.value === String((graphic.spec ?? {})[key] ?? "")) return;
            onChange(id, { spec: { ...(graphic.spec ?? {}), [key]: e.target.value } });
          }}
          placeholder={key}
          className="min-w-[16rem] flex-1 rounded border border-neutral-700 bg-neutral-900 px-2 py-0.5 text-neutral-100"
        />
      ) : (
        <span className="text-neutral-600">no editable text ({graphic.kind})</span>
      )}

      <button
        onClick={() => onRemove(id)}
        className="ml-auto rounded border border-rose-500/40 px-2 py-0.5 text-rose-300 hover:bg-rose-500/10"
      >
        Remove
      </button>
    </div>
  );
}
