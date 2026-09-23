"use client";

import { useMemo, useState } from "react";
import { Check, ChevronDown, ChevronRight, X } from "lucide-react";
import { ShortDirectionControl } from "./short-direction-control";
import { AUTOMATIC_SHORT_DIRECTION, shortDirectionForStyle } from "@/lib/producer/short-direction";
import {
  INTENT_PRESETS,
  LANES,
  LANE_LABELS,
  deriveScopeAndLanes,
  presetToIntent,
  resolveLanes,
  type IntentPreset,
  type Lane,
  type LaneDirective,
  type Mode,
  type ProjectIntent,
} from "@/lib/producer/intent-presets";

// INTENT CARD — sits between "pick footage" and "Run ingest": Short|Long
// toggle, preset chips, a will/won't description of the selection, and an
// expandable lane customizer (checkbox edits derive the smallest covering
// scope + "off" overrides — edit_scope semantics, see intent-presets.ts).
// The chosen intent rides the ingest POST into project.json ("intent") and
// prefills Auto-edit.

interface Props {
  value: ProjectIntent;
  onChange: (intent: ProjectIntent) => void;
  disabled?: boolean;
  formatConfirmed?: boolean;
  styleConfirmed?: boolean;
  onFormatConfirmed?: () => void;
  onStyleConfirmed?: () => void;
  onStyleInvalidated?: () => void;
}

const PRESET_COPY: Record<string, { label: string; summary: string }> = {
  "light-short": { label: "Simple short", summary: "A clean vertical cut with captions and subtle motion." },
  "produced-short": { label: "Polished short", summary: "A vertical cut with captions, graphics, motion, transitions, and available cutaways." },
  "longform-produced": { label: "Polished long video", summary: "A horizontal edit with structured sections, cutaways, graphics, and a caption file." },
  "trim-only": { label: "Clean trim only", summary: "Remove pauses, retakes, and setup chatter without adding visual effects." },
};

function ModeToggle({ value, disabled, confirmed, onPick }: {
  value: Mode;
  disabled?: boolean;
  confirmed?: boolean;
  onPick: (m: Mode) => void;
}) {
  const opts: { m: Mode; label: string }[] = [
    { m: "short", label: "Vertical short (9:16)" },
    { m: "longform", label: "Horizontal video (16:9)" },
  ];
  return (
    <div className="flex overflow-hidden rounded-md border border-border">
      {opts.map(({ m, label }) => (
        <button
          key={m}
          type="button"
          aria-pressed={confirmed && value === m}
          disabled={disabled}
          onClick={() => onPick(m)}
          className={`px-3 py-1 text-xs transition-colors ${
            confirmed && value === m ? "bg-signal/20 text-foreground" : "text-muted-foreground hover:bg-card"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function PresetChip({ p, current, disabled, onPick }: {
  p: IntentPreset;
  current?: string;
  disabled?: boolean;
  onPick: (p: IntentPreset) => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={current === p.id}
      disabled={disabled}
      onClick={() => onPick(p)}
      className={`rounded-full border px-2.5 py-0.5 text-[11px] transition-colors ${
        current === p.id
          ? "border-signal/60 bg-signal/10 text-foreground"
          : "border-border text-muted-foreground hover:border-signal/40"
      }`}
    >
      {PRESET_COPY[p.id]?.label ?? p.label}
    </button>
  );
}

/** Preset chips grouped Styles (measured grammars, p.style set) vs Generic. */
function PresetChips({ current, disabled, onPick }: {
  current?: string;
  disabled?: boolean;
  onPick: (p: IntentPreset) => void;
}) {
  const styles = INTENT_PRESETS.filter((p) => p.style);
  const generic = INTENT_PRESETS.filter((p) => !p.style);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="w-24 shrink-0 text-[10px] uppercase tracking-wider text-muted-foreground/60">Saved styles</span>
        {styles.map((p) => (
          <PresetChip key={p.id} p={p} current={current} disabled={disabled} onPick={onPick} />
        ))}
      </div>
      <div className="border-t border-border/60" />
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="w-24 shrink-0 text-[10px] uppercase tracking-wider text-muted-foreground/60">Editing level</span>
        {generic.map((p) => (
          <PresetChip key={p.id} p={p} current={current} disabled={disabled} onPick={onPick} />
        ))}
        {current === "custom" && (
          <span className="rounded-full border border-amber-500/40 bg-amber-500/5 px-2.5 py-0.5 text-[11px] text-amber-400/90">
            custom
          </span>
        )}
      </div>
    </div>
  );
}

function WillWont({ will, wont }: { will: string[]; wont: string[] }) {
  return (
    <div className="grid gap-x-4 gap-y-0.5 sm:grid-cols-2">
      <ul className="space-y-0.5">
        <li className="mb-1 text-xs font-medium text-foreground">Required deliverables</li>
        {will.map((t) => (
          <li key={t} className="flex items-start gap-1.5 text-[11px] text-muted-foreground">
            <Check className="mt-0.5 size-3 shrink-0 text-emerald-400" strokeWidth={3} /> {t}
          </li>
        ))}
      </ul>
      <ul className="space-y-0.5">
        <li className="mb-1 text-xs font-medium text-foreground">Not included</li>
        {wont.map((t) => (
          <li key={t} className="flex items-start gap-1.5 text-[11px] text-muted-foreground/70">
            <X className="mt-0.5 size-3 shrink-0 text-neutral-500" strokeWidth={3} /> {t}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Plain-language will/wont for a customized (non-preset) lane selection. */
function customLists(value: ProjectIntent, active: Record<Lane, LaneDirective>) {
  const will = ["Cut pauses, retakes and the cold-open (the base cut is always on)"];
  const wont: string[] = [];
  for (const lane of LANES) {
    if (active[lane] === "auto") will.push(`Required: ${LANE_LABELS[lane]}`);
    else wont.push(`No ${LANE_LABELS[lane]}`);
  }
  if (value.audioEnhance) will.push(`Dialogue cleanup: ${value.audioEnhance.preset}`);
  if (value.music) will.push("Music bed at assemble (ducked under dialogue)");
  else wont.push("No music bed");
  will.push("Reframe + −14 LUFS master (always on)");
  return { will, wont };
}

export default function IntentCard({
  value,
  onChange,
  disabled,
  formatConfirmed = true,
  styleConfirmed = true,
  onFormatConfirmed,
  onStyleConfirmed,
  onStyleInvalidated,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const active = useMemo(() => resolveLanes(value.scope, value.lanes), [value.scope, value.lanes]);
  const preset = INTENT_PRESETS.find((p) => p.id === value.preset);
  const lists = preset ?? customLists(value, active);

  const setMode = (mode: Mode) => {
    const keepPreset = preset && (preset.mode === null || preset.mode === mode);
    onChange({
      ...value,
      mode,
      // pacing_<pace> profiles + style grammars are shorts-measured only.
      ...(mode === "longform" ? { pace: undefined, style: undefined, shortDirection: undefined } : {}),
      ...(mode === "short" ? { shortDirection: value.shortDirection ?? AUTOMATIC_SHORT_DIRECTION } : {}),
      preset: keepPreset ? value.preset : "custom",
    });
    onFormatConfirmed?.();
    if (!keepPreset) onStyleInvalidated?.();
  };

  // Presets replace intent. Music never carries across a preset choice and no
  // style may enable it implicitly; only the checkbox below can opt in.
  const applyPreset = (p: IntentPreset) => {
    const next = presetToIntent(p, value.mode);
    onChange({ ...next, ...(next.mode === "short"
      ? { shortDirection: p.style ? shortDirectionForStyle(PRESET_COPY[p.id]?.label ?? p.label, value.shortDirection)
        : value.shortDirection ?? AUTOMATIC_SHORT_DIRECTION } : {}) });
    onStyleConfirmed?.();
    if (p.mode !== null) onFormatConfirmed?.();
  };

  const toggleLane = (lane: Lane) => {
    const next = {} as Record<Lane, boolean>;
    for (const l of LANES) next[l] = l === lane ? active[l] !== "auto" : active[l] === "auto";
    const { scope, lanes } = deriveScopeAndLanes(next);
    onChange({ ...value, scope, lanes, preset: "custom" });
    onStyleConfirmed?.();
  };

  return (
    <div className="rounded-lg border border-border bg-card/60 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <span className="text-sm font-semibold text-foreground">Choose format and editing style</span>
        <ModeToggle
          value={value.mode}
          disabled={disabled}
          confirmed={formatConfirmed}
          onPick={setMode}
        />
      </div>

      <PresetChips
        current={styleConfirmed ? value.preset : undefined}
        disabled={disabled}
        onPick={applyPreset}
      />

      <p className="mt-3 text-sm text-muted-foreground">
        {preset ? PRESET_COPY[preset.id]?.summary ?? preset.label : "A custom mix of editing features."}
      </p>

      {value.mode === "short" && <ShortDirectionControl value={value.shortDirection} disabled={disabled}
        onChange={(shortDirection) => {
          onChange({ ...value, shortDirection, style: undefined, pace: undefined,
            preset: value.style ? "custom" : value.preset });
          onStyleConfirmed?.();
        }} />}

      <label className="mt-3 flex items-start gap-2 rounded-md border border-border bg-background/30 p-3 text-sm text-foreground">
        <input
          type="checkbox"
          className="mt-0.5 accent-signal"
          disabled={disabled}
          checked={value.music === true}
          onChange={(event) => onChange({ ...value, music: event.target.checked || undefined })}
        />
        <span>
          Add background music
          <span className="mt-0.5 block text-xs text-muted-foreground">Uses a track from the selected project folder when one is available.</span>
        </span>
      </label>

      <details className="mt-3 text-xs text-muted-foreground">
        <summary className="cursor-pointer hover:text-foreground">See exactly what is included</summary>
        <div className="mt-2"><WillWont will={lists.will} wont={lists.wont} /></div>
      </details>

      <button
        type="button"
        disabled={disabled}
        onClick={() => setExpanded((e) => !e)}
        className="mt-3 flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
      >
        {expanded ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
        Choose required editing deliverables (advanced)
      </button>

      {expanded && (
        <div className="mt-2 space-y-1.5 border-l border-border pl-3">
          <p className="pb-1 text-[11px] leading-relaxed text-muted-foreground">
            Checked means required: the edit must include and verify this lane,
            or the run stops with a specific failure. Uncheck a lane only to waive it.
          </p>
          {LANES.map((lane) => (
            <label key={lane} className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <input
                type="checkbox"
                className="accent-signal"
                disabled={disabled}
                checked={active[lane] === "auto"}
                onChange={() => toggleLane(lane)}
              />
              {LANE_LABELS[lane]} <span className="font-mono text-[9px] text-muted-foreground/50">{lane}</span>
            </label>
          ))}
          {value.mode === "short" && (
            <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <input
                type="checkbox"
                className="accent-signal"
                disabled={disabled}
                checked={value.pace === "talking-head"}
                onChange={(e) =>
                  onChange({ ...value, pace: e.target.checked ? "talking-head" : undefined })
                }
              />
              talking-head pace (slow, sustained graphics — paces like longform)
            </label>
          )}
        </div>
      )}

    </div>
  );
}
