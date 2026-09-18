"use client";

import { useState } from "react";
import { Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  KNOWN_STYLES,
  suggestedMode,
  type KnownReferenceStyle,
  type ReferenceDecision,
  type ReferenceEntry,
  type ReferenceMode,
  type ReferenceStrategy,
} from "./reference-types";
import { VERIFIED_MIMIC_RELEASED } from
  "@/lib/producer/reference-qualification";

interface Props {
  reference: ReferenceEntry;
  saving: boolean;
  onSave: (decision: ReferenceDecision) => Promise<ReferenceEntry | null>;
}

interface Draft {
  mode?: ReferenceMode;
  strategy: ReferenceStrategy;
  targetStyle?: KnownReferenceStyle;
  candidateStyleName: string;
}

const CLOSED_STYLE_NAMES = new Set(["restrained", "punch", "slideware"]);

function reservedCandidate(name: string): boolean {
  return CLOSED_STYLE_NAMES.has(name.trim().toLowerCase());
}

function initialDraft(reference: ReferenceEntry): Draft {
  const saved = reference.decision;
  const known = reference.profile?.suggestedKnownStyle ?? undefined;
  return {
    mode: saved?.mode,
    strategy: saved?.strategy ?? (known ? "extend" : "mimic"),
    targetStyle: saved?.targetStyle ?? known,
    candidateStyleName: saved?.candidateStyleName ?? "",
  };
}

function ModeChoice({ reference, draft, onPick }: {
  reference: ReferenceEntry;
  draft: Draft;
  onPick: (mode: ReferenceMode) => void;
}) {
  const suggested = suggestedMode(reference);
  return (
    <div>
      <p className="mb-1.5 text-[10px] uppercase tracking-wider text-muted-foreground/60">
        Confirm format {suggested ? `· study suggests ${suggested === "short" ? "Short" : "Long"}` : ""}
      </p>
      <div className="grid grid-cols-2 gap-2">
        {(["short", "longform"] as ReferenceMode[]).map((mode) => (
          <button
            key={mode}
            type="button"
            aria-pressed={draft.mode === mode}
            onClick={() => onPick(mode)}
            className={`rounded-md border px-3 py-2 text-left text-xs transition-colors ${
              draft.mode === mode ? "border-signal/70 bg-signal/10 text-foreground" : "border-border text-muted-foreground hover:border-signal/40"
            }`}
          >
            <span className="font-medium">{mode === "short" ? "Short · 9:16" : "Long · 16:9"}</span>
            {suggested === mode && <span className="ml-1 text-[9px] uppercase text-signal">suggested</span>}
          </button>
        ))}
      </div>
    </div>
  );
}

function StrategyChoice({ draft, onPick }: { draft: Draft; onPick: (value: ReferenceStrategy) => void }) {
  const options: Array<{ id: ReferenceStrategy; label: string; hint: string }> = [
    {
      id: "mimic",
      label: "Reference-inspired",
      hint: VERIFIED_MIMIC_RELEASED
        ? "Verified mimic"
        : "Measured guidance · verified mimic not qualified",
    },
    { id: "extend", label: "Extend a style", hint: "Add evidence to a measured grammar" },
    { id: "new-style", label: "New style", hint: "Create a named candidate" },
  ];
  return (
    <div className="space-y-1.5">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Style direction</p>
      {options.map((option) => {
        const disabled = option.id === "extend" && draft.mode === "longform";
        return (
          <button
            key={option.id}
            type="button"
            aria-pressed={draft.strategy === option.id}
            disabled={disabled}
            onClick={() => onPick(option.id)}
            className={`flex w-full items-center justify-between rounded-md border px-3 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
              draft.strategy === option.id ? "border-signal/60 bg-signal/10" : "border-border hover:border-signal/30"
            }`}
          >
            <span className="text-xs text-foreground">{option.label}</span>
            <span className="text-[10px] text-muted-foreground">{disabled ? "Shorts only" : option.hint}</span>
          </button>
        );
      })}
    </div>
  );
}

function StrategyDetail({ draft, onStyle, onName }: {
  draft: Draft;
  onStyle: (style: KnownReferenceStyle) => void;
  onName: (name: string) => void;
}) {
  if (draft.strategy === "extend") {
    return (
      <div className="flex flex-wrap gap-1.5">
        {KNOWN_STYLES.map((style) => (
          <Button
            key={style.id}
            type="button"
            aria-pressed={draft.targetStyle === style.id}
            size="xs"
            variant={draft.targetStyle === style.id ? "default" : "outline"}
            onClick={() => onStyle(style.id)}
          >
            {style.label}
          </Button>
        ))}
      </div>
    );
  }
  if (draft.strategy !== "new-style") return null;
  return (
    <div className="space-y-1">
      <Input
        value={draft.candidateStyleName}
        maxLength={80}
        onChange={(event) => onName(event.target.value)}
        placeholder="Name this style candidate"
        className="h-8 text-xs"
      />
      {reservedCandidate(draft.candidateStyleName) && (
        <p className="text-[10px] text-amber-300">That is a closed style. Choose “Extend a style” instead.</p>
      )}
    </div>
  );
}

function validDecision(draft: Draft): boolean {
  if (!draft.mode) return false;
  if (draft.strategy === "extend") return !!draft.targetStyle && draft.mode === "short";
  if (draft.strategy === "new-style") {
    return draft.candidateStyleName.trim().length > 1 && !reservedCandidate(draft.candidateStyleName);
  }
  return true;
}

function toDecision(draft: Draft): ReferenceDecision {
  return {
    mode: draft.mode as ReferenceMode,
    strategy: draft.strategy,
    ...(draft.strategy === "extend" && draft.targetStyle ? { targetStyle: draft.targetStyle } : {}),
    ...(draft.strategy === "new-style" ? { candidateStyleName: draft.candidateStyleName.trim() } : {}),
  };
}

export default function ReferenceDecisionForm({ reference, saving, onSave }: Props) {
  const [draft, setDraft] = useState(() => initialDraft(reference));
  const [dirty, setDirty] = useState(!reference.decision);
  const update = (next: Partial<Draft>) => {
    setDraft((current) => ({ ...current, ...next }));
    setDirty(true);
  };
  const pickMode = (mode: ReferenceMode) => update({
    mode,
    ...(mode === "longform" && draft.strategy === "extend" ? { strategy: "mimic", targetStyle: undefined } : {}),
  });
  const save = async () => {
    if (!validDecision(draft)) return;
    if (await onSave(toDecision(draft))) setDirty(false);
  };
  return (
    <div className="space-y-3 border-t border-border/60 pt-3">
      <ModeChoice reference={reference} draft={draft} onPick={pickMode} />
      <StrategyChoice draft={draft} onPick={(strategy) => update({ strategy })} />
      <StrategyDetail
        draft={draft}
        onStyle={(targetStyle) => update({ targetStyle })}
        onName={(candidateStyleName) => update({ candidateStyleName })}
      />
      <div className="flex items-center justify-between gap-3">
        <p className="text-[10px] text-muted-foreground">
          {reference.decision && !dirty ? "Decision saved. This reference can guide the next edit." : "Save is required before this reference can be used."}
          {" "}Sniper never copies its words, branding, footage, assets, or music.
        </p>
        <Button size="sm" disabled={saving || !dirty || !validDecision(draft)} onClick={() => void save()}>
          {saving ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />}
          {saving ? "Saving…" : "Save decision"}
        </Button>
      </div>
    </div>
  );
}
