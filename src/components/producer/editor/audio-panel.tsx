"use client";

import { useState } from "react";
import { EditPlan, AudioGainEntry, planDuration } from "@/lib/producer/edit-plan";

interface Props {
  plan: EditPlan;
  onMutate: (fn: (p: EditPlan) => EditPlan) => void;
}

const PRESETS = [
  { id: "off", label: "Off", hint: "Keep the original dialogue audio" },
  { id: "voice", label: "Light cleanup", hint: "Gentle noise reduction and clearer speech" },
  { id: "voice-rnn", label: "Neural cleanup", hint: "Remove steady room noise with RNNoise" },
  { id: "voice-strong", label: "Strong cleanup", hint: "For noisy rooms; may sound more processed" },
  { id: "separate", label: "Isolate voice", hint: "Separate speech from complex background sound locally" },
] as const;

const REBUILD_HINT = "Applied when you re-render. Audio processing and QC time depend on the footage and requested changes.";

// A master entry is adopted when it starts at 0 and covers ≥85% of the CURRENT
// duration — the duration GROWS when cuts are undone, so an exact-length match
// (fixed tolerance) stops fitting and stepping would add a second overlapping
// full-duration entry that hard-fails lint.
const MASTER_COVERAGE = 0.85;

/** Index of the ONE whole-video master-volume entry in audioGain, or -1. */
function masterGainIndex(plan: EditPlan): number {
  const dur = planDuration(plan);
  return (plan.audioGain ?? []).findIndex(
    (g) => g.outStart === 0 && g.outEnd >= dur * MASTER_COVERAGE,
  );
}

// Stepping ALWAYS rewrites the adopted entry to {0, planDuration(current), dB}
// so it re-fits the current duration — never a second full-duration entry.
function withMasterGain(plan: EditPlan, dB: number): EditPlan {
  const track = [...(plan.audioGain ?? [])];
  const idx = masterGainIndex(plan);
  if (idx >= 0) track.splice(idx, 1);
  if (dB !== 0) {
    const entry: AudioGainEntry = { outStart: 0, outEnd: planDuration(plan), dB };
    track.push(entry);
  }
  if (track.length === 0) {
    const rest = { ...plan };
    delete rest.audioGain;
    return rest;
  }
  return { ...plan, audioGain: track };
}

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

function VolumeSection({ plan, onMutate }: Props) {
  const idx = masterGainIndex(plan);
  const dB = idx >= 0 ? (plan.audioGain ?? [])[idx].dB : 0;
  const step = (delta: number) => {
    const next = Math.max(-12, Math.min(12, dB + delta));
    onMutate((p) => withMasterGain(p, next));
  };
  return (
    <Section title="Dialogue volume">
      <div className="flex items-center gap-2">
        <button
          onClick={() => step(-1)}
          disabled={dB <= -12}
          aria-label="Decrease dialogue volume by 1 dB"
          className="h-7 w-7 rounded border border-neutral-700 text-neutral-200 enabled:hover:bg-neutral-800 disabled:opacity-40"
        >
          −
        </button>
        <span className="w-16 text-center font-mono text-sm text-neutral-100">
          {dB > 0 ? `+${dB}` : dB} dB
        </span>
        <button
          onClick={() => step(1)}
          disabled={dB >= 12}
          aria-label="Increase dialogue volume by 1 dB"
          className="h-7 w-7 rounded border border-neutral-700 text-neutral-200 enabled:hover:bg-neutral-800 disabled:opacity-40"
        >
          +
        </button>
      </div>
      <Hint text={`Changes the whole video's dialogue volume. ${REBUILD_HINT}`} />
    </Section>
  );
}

function EnhanceSection({ plan, onMutate }: Props) {
  const active = plan.audioEnhance?.preset ?? "off";
  const pick = (id: string) => {
    onMutate((p) => {
      const next = { ...p };
      if (id === "off") delete next.audioEnhance;
      else next.audioEnhance = { preset: id as NonNullable<EditPlan["audioEnhance"]>["preset"] };
      return next;
    });
  };
  return (
    <Section title="Dialogue cleanup">
      <div className="space-y-1">
        {PRESETS.map((pr) => (
          <label key={pr.id} className="flex cursor-pointer items-start gap-2 text-xs text-neutral-300">
            <input
              type="radio"
              name="audio-enhance"
              checked={active === pr.id}
              onChange={() => pick(pr.id)}
              className="mt-0.5 accent-emerald-500"
            />
            <span>
              <span className={active === pr.id ? "text-emerald-300" : ""}>{pr.label}</span>
              <span className="ml-1.5 text-[10px] text-neutral-500">{pr.hint}</span>
            </span>
          </label>
        ))}
      </div>
      <Hint text={REBUILD_HINT} />
    </Section>
  );
}

interface MusicPickResult {
  path?: string;
  canceled?: boolean;
  error?: string;
}

async function pickMusicFile(): Promise<MusicPickResult> {
  try {
    const res = await fetch("/api/producer/pick-file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: "file", prompt: "Choose a music track" }),
    });
    const data = await res.json().catch(() => ({})) as MusicPickResult;
    if (!res.ok) return { error: data.error || `File picker failed (${res.status})` };
    if (data.canceled) return { canceled: true };
    if (typeof data.path === "string") return { path: data.path };
    return { error: "The file picker returned no music file." };
  } catch (error) {
    return { error: error instanceof Error ? error.message : "The file picker could not open." };
  }
}

function MusicSection({ plan, onMutate }: Props) {
  const music = plan.music;
  const [picking, setPicking] = useState(false);
  const [pickError, setPickError] = useState("");
  const patchMusic = (patch: Partial<NonNullable<EditPlan["music"]>>) =>
    onMutate((p) => ({ ...p, music: { enabled: true, ...p.music, ...patch } }));

  const add = async () => {
    setPicking(true);
    setPickError("");
    const result = await pickMusicFile();
    setPicking(false);
    if (result.error) setPickError(result.error);
    if (result.path) {
      onMutate((p) => ({ ...p, music: { enabled: true, path: result.path, duck: true } }));
    }
  };
  const remove = () =>
    onMutate((p) => {
      const next = { ...p };
      delete next.music;
      return next;
    });

  return (
    <Section title="Music">
      {!music?.enabled ? (
        <button
          onClick={add}
          disabled={picking}
          aria-busy={picking}
          className="rounded border border-emerald-500/40 px-2.5 py-1 text-xs text-emerald-200 enabled:hover:bg-emerald-500/10 disabled:cursor-wait disabled:opacity-60"
        >
          {picking ? "Opening file picker…" : "Choose music file"}
        </button>
      ) : (
        <div className="space-y-2 text-xs text-neutral-300">
          <div className="truncate font-mono text-[10px] text-neutral-400" title={music.path ?? music.assetId}>
            {(music.path ?? music.assetId ?? "").split("/").pop()}
          </div>
          <label className="flex items-center gap-2">
            <span className="w-24 shrink-0 text-neutral-400">Voice/music gap</span>
            <input
              type="number"
              step={1}
              min={3}
              max={40}
              defaultValue={music.gapDb ?? ""}
              placeholder="auto"
              onBlur={(e) => {
                const n = parseFloat(e.target.value);
                if (!Number.isFinite(n)) {
                  patchMusic({ gapDb: undefined });
                  return;
                }
                const valid = Math.max(3, Math.min(40, n));
                e.currentTarget.value = String(valid);
                patchMusic({ gapDb: valid });
              }}
              className="w-16 rounded border border-neutral-700 bg-neutral-900 px-1.5 py-0.5 text-neutral-100"
            />
          </label>
          <Hint text="How many dB the music sits below your voice — larger = quieter music." />
          {music.duck === false ? (
            <div className="rounded border border-amber-500/30 bg-amber-500/5 p-2 text-amber-200" role="alert">
              <p>Music must lower automatically under dialogue before this video can render.</p>
              <button onClick={() => patchMusic({ duck: true })} className="mt-1 text-[11px] underline">
                Turn on dialogue ducking
              </button>
            </div>
          ) : (
            <p className="text-neutral-400">✓ Dialogue ducking on <span className="text-[10px]">(keeps speech clear)</span></p>
          )}
          <button
            onClick={remove}
            className="rounded border border-rose-500/40 px-2 py-0.5 text-rose-300 hover:bg-rose-500/10"
          >
            Remove music
          </button>
        </div>
      )}
      {pickError && (
        <p className="mt-2 text-[11px] leading-snug text-rose-300" role="alert">
          Couldn&apos;t choose music: {pickError} You can try again.
        </p>
      )}
      <Hint text="Applied when you re-render (about 1 minute)." />
    </Section>
  );
}

// AUDIO panel — direct plan edits only ($0): a whole-video dB master gain, the
// base-side enhance preset, and the assemble-time music bed. Every mutation
// goes through the editor's undo-able mutatePlan; Re-render applies it.
export default function AudioPanel({ plan, onMutate }: Props) {
  return (
    <div className="text-sm">
      <VolumeSection plan={plan} onMutate={onMutate} />
      <EnhanceSection plan={plan} onMutate={onMutate} />
      <MusicSection plan={plan} onMutate={onMutate} />
    </div>
  );
}
