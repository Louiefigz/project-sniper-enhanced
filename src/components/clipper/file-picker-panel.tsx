"use client";

import { Button } from "@/components/ui/button";
import type { SlotKey } from "@/components/clipper/file-picker-utils";

export interface PickerGroup {
  person: string;
  slots: { key: SlotKey; label: string; path: string; name: string; required: boolean }[];
}

interface Props {
  groups: PickerGroup[];
  pickingSlot: SlotKey | null;
  pickingMulti: boolean;
  autoNotice: string | null;
  pickError: string | null;
  lavsReady: boolean;
  canTranscribe: boolean;
  onPickMultiple: () => void;
  onPickSlot: (slot: SlotKey) => void;
  onClearSlot: (slot: SlotKey) => void;
  onTranscribe: () => void;
}

function SlotButton({
  person, slot, pickingSlot, pickingMulti, onPick, onClear,
}: {
  person: string;
  slot: PickerGroup["slots"][number];
  pickingSlot: SlotKey | null;
  pickingMulti: boolean;
  onPick: (slot: SlotKey) => void;
  onClear: (slot: SlotKey) => void;
}) {
  const isAudio = slot.key === "hostMic" || slot.key === "guestMic";
  const hasFile = !!slot.path;
  const isPicking = pickingSlot === slot.key;
  const border = hasFile ? "border-emerald-500 bg-emerald-950/20"
    : isPicking ? "border-amber-500/70 bg-amber-950/10"
    : "border-dashed border-neutral-700 bg-neutral-900/30 hover:border-neutral-600 hover:bg-neutral-900/60";
  return (
    <div className={`w-full flex items-stretch rounded-lg border-2 transition-colors ${border}`}>
      <button type="button" onClick={() => onPick(slot.key)}
        disabled={pickingMulti || (!!pickingSlot && !isPicking)}
        aria-label={`${hasFile ? "Replace" : "Choose"} ${person} ${slot.label}`}
        className="min-w-0 flex-1 text-left px-3 py-2 disabled:opacity-50">
        <div className="flex items-center gap-3">
        <span className="text-base shrink-0">{hasFile ? (isAudio ? "🎙️" : "🎬") : "📂"}</span>
        <div className="flex flex-col min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-neutral-400 shrink-0">
              {slot.label}{slot.required ? "" : " (optional)"}
            </span>
            <span className="text-[11px] text-neutral-500 truncate">{isAudio ? "Clean per-person audio" : "Video angle"}</span>
          </div>
          <span className={`text-xs font-mono truncate ${hasFile ? "text-emerald-300" : "text-neutral-600"}`}>
            {hasFile ? slot.name : "No file selected"}
          </span>
        </div>
        {!hasFile && !isPicking && <span className="text-[10px] font-semibold uppercase tracking-wider text-neutral-500">Click to browse</span>}
        {isPicking && <span className="text-[10px] font-semibold uppercase tracking-wider text-amber-400">Picker open…</span>}
        </div>
      </button>
      {hasFile && <button type="button" aria-label={`Clear ${person} ${slot.label}`}
        disabled={pickingMulti || !!pickingSlot} onClick={() => onClear(slot.key)}
        className="px-3 text-neutral-500 hover:text-neutral-200 disabled:opacity-40">✕</button>}
    </div>
  );
}

export function FilePickerPanel(props: Props) {
  return <>
    <div className="mb-4">
      <h2 className="text-2xl font-bold mb-1">Choose recording files</h2>
      <p className="text-neutral-400 text-sm">Choose the main Host camera. Add a Guest camera or separate mics only when you recorded them at the same time.</p>
    </div>
    <div className="mb-4 rounded-lg border border-amber-700/50 bg-amber-950/20 p-3 text-xs leading-relaxed text-amber-200">
      <strong>Clipper does not synchronize or conform media.</strong> Every extra camera and mic must already be synchronized to the Host camera and have a compatible start time and recording length. Extra video should also use a compatible frame rate and resolution.
    </div>
    <button onClick={props.onPickMultiple} disabled={!!props.pickingSlot || props.pickingMulti}
      className="w-full mb-3 rounded-lg border-2 border-dashed border-amber-700/60 bg-amber-950/10 hover:border-amber-500 hover:bg-amber-950/25 disabled:opacity-50 disabled:cursor-not-allowed px-3 py-3 text-left transition-colors">
      <div className="flex items-center gap-3">
        <span className="text-base shrink-0">{props.pickingMulti ? "⏳" : "✨"}</span>
        <div className="flex flex-col min-w-0 flex-1">
          <span className="text-sm font-semibold text-amber-200">{props.pickingMulti ? "Picker open…" : "Add all clips — auto-sort"}</span>
          <span className="text-[11px] text-amber-400/70">Select already-synchronized cameras + mics together; Clipper fills the Host/Guest slots automatically</span>
        </div>
      </div>
    </button>
    {props.autoNotice && <div className="mb-3 text-[11px] text-neutral-400 p-2.5 bg-neutral-900/40 border border-neutral-800 rounded-lg">{props.autoNotice}</div>}
    <div className="mb-4 space-y-3">
      {props.groups.map((group) => <fieldset key={group.person} className="rounded-xl border border-neutral-800 bg-neutral-900/30 p-3">
        <legend className="px-1 text-xs font-semibold uppercase tracking-wider text-neutral-400">{group.person}</legend>
        <div className="mt-2 space-y-2">{group.slots.map((slot) => <SlotButton key={slot.key} person={group.person} slot={slot}
          pickingSlot={props.pickingSlot} pickingMulti={props.pickingMulti}
          onPick={props.onPickSlot} onClear={props.onClearSlot} />)}</div>
      </fieldset>)}
    </div>
    <div className={`mb-4 text-[11px] p-2.5 rounded-lg border ${props.lavsReady ? "text-emerald-300/90 border-emerald-900/40 bg-emerald-950/20" : "text-neutral-400 border-neutral-800 bg-neutral-900/40"}`}>
      {props.lavsReady
        ? "✓ Both mics set — transcription uses clean lav audio and labels Host/Guest exactly. Export plays the lavs with camera audio muted."
        : "Add both lav mics to transcribe from clean per-person audio (otherwise the Host camera's own audio is used)."}
    </div>
    {props.pickError && <div className="mb-4 text-red-400 text-sm p-3 bg-red-950/20 border border-red-900/30 rounded-lg">{props.pickError}</div>}
    <div className="mb-6"><Button onClick={props.onTranscribe} disabled={!props.canTranscribe}
      className="w-full bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-30 disabled:cursor-not-allowed font-semibold">
      {props.canTranscribe ? "Transcribe and choose edit instructions →" : "Choose a Host camera to continue"}
    </Button></div>
  </>;
}
