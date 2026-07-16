"use client";

import { ReviewConfig, MODEL_OPTIONS, SelectMode } from "@/lib/frameio/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function ConfigStep({
  fileName,
  config,
  onChange,
  onRun,
}: {
  fileName: string | null;
  config: ReviewConfig;
  onChange: (c: ReviewConfig) => void;
  onRun: () => void;
}) {
  const set = (patch: Partial<ReviewConfig>) => onChange({ ...config, ...patch });

  return (
    <div className="rise-in max-w-xl">
      <h1 className="font-display text-2xl font-bold tracking-tight">Choose review settings</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        <span className="text-foreground">{fileName}</span> · the recommended settings work for
        most videos. This review only reports possible issues; it never edits the MP4.
      </p>

      <VideoTypeField mode={config.mode} onSelect={(mode) => set({ mode })} />
      <AdvancedSettings config={config} set={set} />

      <div className="mt-8 flex items-center gap-3">
        <Button onClick={onRun}>Start text review →</Button>
        <span className="label text-muted-foreground/70">
          If the review is unusually large, it will pause and ask before continuing.
        </span>
      </div>
    </div>
  );
}

function VideoTypeField({
  mode,
  onSelect,
}: {
  mode: SelectMode;
  onSelect: (mode: SelectMode) => void;
}) {
  const options: Array<{ id: SelectMode; label: string; hint: string }> = [
    { id: "visual", label: "Standard video", hint: "Recommended for most videos" },
    { id: "ocr", label: "Static slides", hint: "Only for clean presentation slides" },
  ];
  return (
    <div className="mt-8">
      <div className="label text-foreground">What kind of video is this?</div>
      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
        Choose Standard video for footage, talking heads, captions, and lower thirds.
      </p>
      <div className="mt-3 flex gap-2">
        {options.map((option) => (
          <button
            type="button"
            key={option.id}
            aria-pressed={mode === option.id}
            onClick={() => onSelect(option.id)}
            className={`flex flex-1 flex-col items-start rounded-md border px-3 py-2 text-left transition-colors ${
              mode === option.id
                ? "border-signal/60 bg-signal/10"
                : "border-border bg-card/40 hover:border-border/80"
            }`}
          >
            <span className="text-sm font-medium">{option.label}</span>
            <span className="label text-muted-foreground/70">{option.hint}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function AdvancedSettings({
  config,
  set,
}: {
  config: ReviewConfig;
  set: (patch: Partial<ReviewConfig>) => void;
}) {
  return (
    <details className="mt-6 rounded-lg border border-border bg-card/30">
      <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-foreground">
        Advanced settings
        <span className="ml-2 text-xs font-normal text-muted-foreground">
          Sampling, limits, and AI model
        </span>
      </summary>
      <div className="space-y-6 border-t border-border px-4 py-5">
        <SamplingFields config={config} set={set} />
        <LimitFields config={config} set={set} />
        <ModelField config={config} set={set} />
      </div>
    </details>
  );
}

function SamplingFields({
  config,
  set,
}: {
  config: ReviewConfig;
  set: (patch: Partial<ReviewConfig>) => void;
}) {
  return (
    <>
      <SamplingRateField value={config.fps} set={set} />
      <SimilarityField config={config} set={set} />
    </>
  );
}

function SamplingRateField({
  value,
  set,
}: {
  value: number;
  set: (patch: Partial<ReviewConfig>) => void;
}) {
  return (
    <Field label="Sampling rate" hint="Frames checked per second. The recommended value is 1.">
      <Input
        aria-label="Frames checked per second"
        type="number"
        min={0.1}
        max={10}
        step={0.1}
        value={value}
        onChange={(e) => set({ fps: Math.min(10, Math.max(0.1, Number(e.target.value) || 1)) })}
        className="w-32"
      />
    </Field>
  );
}

function SimilarityField({
  config,
  set,
}: {
  config: ReviewConfig;
  set: (patch: Partial<ReviewConfig>) => void;
}) {
  if (config.mode === "ocr") {
    return (
      <Field
        label="Slide grouping sensitivity"
        hint="OCR similarity from 0–100. Lower values combine more slides."
      >
        <Input
          aria-label="Slide grouping sensitivity"
          type="number"
          min={0}
          max={100}
          value={config.fuzz}
          onChange={(e) =>
            set({ fuzz: Math.min(100, Math.max(0, Number(e.target.value) || 0)) })
          }
          className="w-32"
        />
      </Field>
    );
  }
  return (
    <Field
      label="Similar-frame threshold"
      hint="Perceptual-hash Hamming distance. Higher values combine more near-identical frames."
    >
      <Input
        aria-label="Similar-frame threshold"
        type="number"
        min={0}
        max={32}
        value={config.hamming}
        onChange={(e) => set({ hamming: Math.min(32, Math.max(0, Number(e.target.value) || 0)) })}
        className="w-32"
      />
    </Field>
  );
}

function LimitFields({
  config,
  set,
}: {
  config: ReviewConfig;
  set: (patch: Partial<ReviewConfig>) => void;
}) {
  return (
    <>
      <Field
        label="Images sent for review"
        hint="Optional cost cap. Leave blank to review all selected images."
      >
        <Input
          aria-label="Maximum images sent for review"
          type="number"
          min={1}
          placeholder="all"
          value={config.maxReps ?? ""}
          onChange={(e) =>
            set({ maxReps: e.target.value === "" ? null : Math.max(1, Number(e.target.value) || 1) })
          }
          className="w-32"
        />
      </Field>
      <Field
        label="Frames extracted"
        hint="Optional test-run cap. Leave blank to scan the full video."
      >
        <Input
          aria-label="Maximum frames extracted"
          type="number"
          min={1}
          placeholder="all"
          value={config.maxFrames ?? ""}
          onChange={(e) =>
            set({ maxFrames: e.target.value === "" ? null : Math.max(1, Number(e.target.value) || 1) })
          }
          className="w-32"
        />
      </Field>
    </>
  );
}

function ModelField({
  config,
  set,
}: {
  config: ReviewConfig;
  set: (patch: Partial<ReviewConfig>) => void;
}) {
  return (
    <Field
      label="AI review model"
      hint="Sonnet is recommended for accuracy; Haiku is faster and cheaper."
    >
      <div className="flex gap-2">
        {MODEL_OPTIONS.map((model) => (
          <button
            type="button"
            key={model.id}
            aria-pressed={config.model === model.id}
            onClick={() => set({ model: model.id })}
            className={`flex flex-col items-start rounded-md border px-3 py-2 text-left transition-colors ${
              config.model === model.id
                ? "border-signal/60 bg-signal/10"
                : "border-border bg-card/40 hover:border-border/80"
            }`}
          >
            <span className="text-sm font-medium">{model.label}</span>
            <span className="label text-muted-foreground/70">{model.hint}</span>
          </button>
        ))}
      </div>
    </Field>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-[1fr_auto] sm:items-start sm:gap-6">
      <div>
        <div className="label text-foreground">{label}</div>
        <p className="mt-1 max-w-sm text-xs leading-relaxed text-muted-foreground">{hint}</p>
      </div>
      <div className="sm:justify-self-end">{children}</div>
    </div>
  );
}
