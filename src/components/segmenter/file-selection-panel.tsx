"use client";

import { Button } from "@/components/ui/button";
import {
  SEGMENT_PROMPT_TEMPLATES,
  type FileSlots,
  type SegmentPromptTemplateId,
  type SlotKey,
} from "@/lib/segmenter/file-browser-helpers";

const SLOT_META: Array<{
  key: SlotKey;
  label: string;
  subtitle: string;
  required: boolean;
}> = [
  { key: "a", label: "Main video", subtitle: "Used to find and download clips", required: true },
  { key: "b", label: "Extra camera 1", subtitle: "Optional alternate angle", required: false },
  { key: "c", label: "Extra camera 2", subtitle: "Optional alternate angle", required: false },
  { key: "lav1", label: "Microphone audio 1", subtitle: "Optional separate audio", required: false },
  { key: "lav2", label: "Microphone audio 2", subtitle: "Optional separate audio", required: false },
];

interface PanelProps {
  files: FileSlots;
  picker: {
    slot: SlotKey | null;
    multiple: boolean;
    error: string | null;
    notice: string | null;
  };
  instructions: {
    value: string;
    template: SegmentPromptTemplateId;
    onChange: (value: string) => void;
    onSelectTemplate: (template: SegmentPromptTemplateId) => void;
    onReset: () => void;
  };
  actions: {
    onPick: (slot: SlotKey) => void;
    onPickMultiple: () => void;
    onClear: (slot: SlotKey) => void;
    onStart: () => void;
  };
}

interface SlotButtonProps {
  slot: (typeof SLOT_META)[number];
  panel: PanelProps;
}

function FileSlotButton({ slot, panel }: SlotButtonProps) {
  const file = panel.files[slot.key];
  const isPicking = panel.picker.slot === slot.key;
  const idleClass = "border-dashed border-neutral-700 bg-neutral-900/30 hover:border-neutral-600 hover:bg-neutral-900/60";
  const borderClass = file
    ? "border-cyan-500 bg-cyan-950/20"
    : isPicking ? "border-amber-500/70 bg-amber-950/10" : idleClass;
  const disabled = panel.picker.multiple || (!!panel.picker.slot && !isPicking);
  return (
    <div className={`flex w-full items-center rounded-lg border-2 transition-colors ${disabled ? "opacity-50" : ""} ${borderClass}`}>
      <button
        type="button"
        onClick={() => panel.actions.onPick(slot.key)}
        disabled={disabled}
        className="flex min-w-0 flex-1 items-center gap-3 px-3 py-2 text-left disabled:cursor-not-allowed"
      >
        <span className="text-base shrink-0">{file ? (slot.key.startsWith("lav") ? "🎙️" : "🎬") : "📂"}</span>
        <div className="flex flex-col min-w-0 flex-1">
          <span className="text-xs font-semibold text-neutral-300">
            {slot.label}{slot.required ? " · Required" : ""}
          </span>
          <span className="text-[11px] text-neutral-500">{slot.subtitle}</span>
          <span className={`text-xs truncate ${file ? "text-cyan-300 font-mono" : "text-neutral-600"}`}>
            {file?.name ?? "No file selected"}
          </span>
        </div>
        <span className={`shrink-0 text-[10px] font-semibold uppercase ${isPicking ? "text-amber-400" : "text-neutral-500"}`}>
          {isPicking ? "Picker open…" : file ? "Change" : "Browse"}
        </span>
      </button>
      {file && (
        <button
          type="button"
          onClick={() => panel.actions.onClear(slot.key)}
          disabled={disabled}
          className="mr-2 rounded p-2 text-xs text-neutral-500 hover:bg-neutral-800 hover:text-neutral-200 disabled:cursor-not-allowed"
          aria-label={`Remove ${slot.label}`}
          title={`Remove ${slot.label}`}
        >
          ✕
        </button>
      )}
    </div>
  );
}

function BulkPicker({ panel }: { panel: PanelProps }) {
  return (
    <button
      type="button"
      onClick={panel.actions.onPickMultiple}
      disabled={!!panel.picker.slot || panel.picker.multiple}
      className="w-full mb-3 rounded-lg border-2 border-dashed border-cyan-700/60 bg-cyan-950/10 hover:border-cyan-500 hover:bg-cyan-950/25 disabled:opacity-50 px-3 py-3 text-left transition-colors"
    >
      <div className="flex items-center gap-3">
        <span>{panel.picker.multiple ? "⏳" : "✨"}</span>
        <div className="flex flex-col">
          <span className="text-sm font-semibold text-cyan-200">{panel.picker.multiple ? "Picker open…" : "Add all files — auto-sort"}</span>
          <span className="text-[11px] text-cyan-400/70">Choose videos and audio together; you can correct any assignment below.</span>
        </div>
      </div>
    </button>
  );
}

function TemplateChooser({ panel }: { panel: PanelProps }) {
  return (
    <>
      <div className="mb-3">
        <p className="text-sm font-semibold text-neutral-200">Choose a starting point</p>
        <p className="text-[11px] text-neutral-500">Pick the closest match, then change the instructions if needed.</p>
      </div>
      <div className="mb-4 grid gap-2 sm:grid-cols-3">
        {SEGMENT_PROMPT_TEMPLATES.map((template) => (
          <button
            key={template.id}
            type="button"
            onClick={() => panel.instructions.onSelectTemplate(template.id)}
            aria-pressed={panel.instructions.template === template.id}
            className={`rounded-lg border p-3 text-left transition-colors ${
              panel.instructions.template === template.id
                ? "border-cyan-500 bg-cyan-950/30"
                : "border-neutral-700 bg-neutral-950/30 hover:border-neutral-600"
            }`}
          >
            <span className="block text-xs font-semibold text-neutral-200">{template.label}</span>
            <span className="mt-1 block text-[10px] leading-4 text-neutral-500">{template.description}</span>
          </button>
        ))}
      </div>
    </>
  );
}

function InstructionsEditor({ panel }: { panel: PanelProps }) {
  return (
    <div className="mb-5 rounded-xl border border-neutral-800 bg-neutral-900/30 p-4">
      <TemplateChooser panel={panel} />
      <div className="mb-2 flex items-start justify-between gap-3">
        <div>
          <label htmlFor="segment-instructions" className="text-sm font-semibold text-neutral-200">What clips should we find?</label>
          <p className="text-[11px] text-neutral-500">Describe where a clip starts and ends, what to keep, and what to leave out.</p>
        </div>
        <button type="button" onClick={panel.instructions.onReset} className="shrink-0 text-xs text-cyan-400 hover:text-cyan-300">
          {panel.instructions.template === "custom" ? "Clear" : "Restore template"}
        </button>
      </div>
      <textarea
        id="segment-instructions"
        value={panel.instructions.value}
        onChange={(event) => panel.instructions.onChange(event.target.value)}
        rows={6}
        placeholder="Example: Make one clip for each question and answer. Start on the question; end after the complete answer. Skip setup chatter and repeated takes."
        className="w-full resize-y rounded-lg border border-neutral-700 bg-neutral-950/60 p-3 text-sm leading-5 text-neutral-200 outline-none focus:border-cyan-600"
      />
      {!panel.instructions.value.trim() && <p className="mt-2 text-xs text-amber-400">Instructions are required.</p>}
    </div>
  );
}

export function FileSelectionPanel(panel: PanelProps) {
  const ready = !!panel.files.a && !!panel.instructions.value.trim();
  return (
    <>
      <div className="mb-4">
        <h2 className="text-2xl font-bold">Choose source files</h2>
        <p className="mt-1 text-sm text-neutral-400">The main video is enough. Add other cameras or microphone files only if you want synced exports.</p>
      </div>
      <BulkPicker panel={panel} />
      {panel.picker.notice && <div className="mb-3 rounded-lg border border-neutral-800 bg-neutral-900/40 p-2.5 text-[11px] text-neutral-400">{panel.picker.notice}</div>}
      <div className="mb-5 space-y-2">{SLOT_META.map((slot) => <FileSlotButton key={slot.key} slot={slot} panel={panel} />)}</div>
      {panel.picker.error && <div className="mb-4 rounded-lg border border-red-900/30 bg-red-950/20 p-3 text-sm text-red-400">{panel.picker.error}</div>}
      <InstructionsEditor panel={panel} />
      {ready ? (
        <Button onClick={panel.actions.onStart} className="w-full bg-cyan-600 font-semibold text-white hover:bg-cyan-700">Find clips →</Button>
      ) : (
        <div className="w-full rounded-xl border border-dashed border-neutral-700 px-5 py-3 text-center text-sm text-neutral-600">Add a main video and describe the clips you want.</div>
      )}
    </>
  );
}
