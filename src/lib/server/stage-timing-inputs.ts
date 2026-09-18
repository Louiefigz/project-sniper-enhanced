import type { RunTimingInputSummary, RunTimingStage } from "@/lib/producer/run-timing";

type Metadata = Record<string, unknown>;
const LABELS = {
  provider: ["codex", "legacy"], effort: ["low", "medium", "high", "xhigh", "max", "ultra"],
  lens: ["composition", "editorial"],
};

function object(value: unknown): Metadata | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Metadata : null;
}

function observedNumber(start: Metadata, end: Metadata, key: string): number | null {
  const value = start[key];
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    && value === end[key] ? value : null;
}

function observedLabel(start: Metadata, end: Metadata, key: keyof typeof LABELS): string | null {
  const value = start[key];
  return typeof value === "string" && value === end[key] && LABELS[key].includes(value) ? value : null;
}

function maximum(before: number | null, after: number | null): number | null {
  return after === null ? before : before === null ? after : Math.max(before, after);
}

function addLabel(labels: string[], value: string | null): void {
  if (value && !labels.includes(value)) { labels.push(value); labels.sort(); }
}

function emptyInput(): RunTimingInputSummary {
  return { promptCalls: 0, maxPromptBytes: null, maxEvidenceImages: null,
    providers: [], efforts: [], lenses: [], deadlineRangeMs: null };
}

/** A malformed or changing optional scalar cannot falsify measured duration. */
export function accountTimingInputs(stage: RunTimingStage, startValue: unknown, endValue: unknown): void {
  const start = object(startValue), end = object(endValue);
  if (!start || !end) return;
  const prompt = observedNumber(start, end, "promptBytes"), images = observedNumber(start, end, "evidenceImages");
  const deadline = observedNumber(start, end, "deadlineMs");
  const provider = observedLabel(start, end, "provider"), effort = observedLabel(start, end, "effort");
  const lens = observedLabel(start, end, "lens");
  if (prompt === null && images === null && !deadline && !provider && !effort && !lens) return;
  const input = stage.inputs ?? emptyInput();
  if (prompt !== null) input.promptCalls += 1;
  input.maxPromptBytes = maximum(input.maxPromptBytes, prompt);
  input.maxEvidenceImages = maximum(input.maxEvidenceImages, images);
  addLabel(input.providers, provider); addLabel(input.efforts, effort); addLabel(input.lenses, lens);
  if (deadline) input.deadlineRangeMs = input.deadlineRangeMs
    ? [Math.min(input.deadlineRangeMs[0], deadline), Math.max(input.deadlineRangeMs[1], deadline)] : [deadline, deadline];
  stage.inputs = input;
}
