/** Observed execution timings, never approval authority or a delivery estimate. */
export interface RunTimingStage {
  stage: string;
  calls: number;
  inclusiveMs: number;
  failed: number;
  interrupted: number;
  inputs?: RunTimingInputSummary;
}

/** Only observed scalar metadata; missing input size is not a zero-sized prompt. */
export interface RunTimingInputSummary {
  promptCalls: number;
  maxPromptBytes: number | null;
  maxEvidenceImages: number | null;
  providers: string[];
  efforts: string[];
  lenses: string[];
  deadlineRangeMs: [number, number] | null;
}

/** Source availability is not evidence that every stage was instrumented. */
export interface RunTimingSource {
  source: "producer" | "base_work";
  state: "read" | "missing" | "rejected";
  reason: string | null;
}

export interface RunTimingReport {
  schemaVersion: 1;
  scope: "auto-edit-job";
  state: "observed" | "unavailable";
  reason: string | null;
  jobStatus: string;
  attempts: number | null;
  wallMs: number | null;
  /** Lower bound from valid job-bound journal timestamps, not liveness or approval. */
  observedActivity?: { throughAt: string; sinceRequestMs: number } | null;
  stages: RunTimingStage[];
  openSpans: number;
  incompleteSpans: number;
  invalidRows: number;
  legacyRows: number;
  clockWarnings: number;
  coverage: "partial-instrumentation";
  sources: RunTimingSource[];
}

/** Compact durations retain seconds so a short edit's latency stays visible. */
export function timingDuration(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms) || ms < 0) return "unavailable";
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

/** Per-stage diagnostic labels; a process ceiling is not a promised completion time. */
export function timingInputSummary(stage: RunTimingStage): string[] {
  const input = stage.inputs;
  if (!input) return [];
  const labels: string[] = [];
  if (input.maxPromptBytes !== null) labels.push(
    `Largest prompt ${(input.maxPromptBytes / 1024).toFixed(1)} KiB (${input.promptCalls}/${stage.calls} calls measured)`);
  if (input.maxEvidenceImages !== null) labels.push(`Up to ${input.maxEvidenceImages} listed evidence images`);
  if (input.providers.length) labels.push(`Provider: ${input.providers.join(", ")}`);
  if (input.efforts.length) labels.push(`Effort: ${input.efforts.join(", ")}`);
  if (input.lenses.length) labels.push(`Lens: ${input.lenses.join(", ")}`);
  if (input.deadlineRangeMs) {
    const [minimum, maximum] = input.deadlineRangeMs;
    labels.push(`Hard process ceiling: ${timingDuration(minimum)}${minimum === maximum ? "" : `–${timingDuration(maximum)}`}`);
  }
  return labels;
}

/** Diagnostic only: an allocation overrun cannot waive a failed quality gate. */
export function timingCaveats(report: RunTimingReport): string[] {
  const notes = [
    "Job wall time includes resume gaps. Earlier media preparation and launch preflight are not included.",
    "Stage times include child work and can overlap; do not add them as total elapsed time.",
    "Execution completed does not mean QC passed. Active time, user wait and the two-hour generation budget are not yet fully attributed.",
  ];
  if (report.reason) notes.push(report.reason);
  if (report.incompleteSpans) notes.push(`${report.incompleteSpans} span(s) without a recorded end; they may be active, interrupted or lost. No zero duration was inferred.`);
  if (report.invalidRows) notes.push(`${report.invalidRows} malformed or conflicting journal record(s) excluded; records without identity cannot be attributed to this job.`);
  if (report.legacyRows) notes.push(`${report.legacyRows} legacy row(s) cannot be attributed safely to this job.`);
  if (report.clockWarnings) notes.push("Wall-clock changes or invalid timestamps were detected; wall time may be unreliable.");
  for (const source of report.sources) {
    const label = source.source === "producer" ? "Producer journal" : "Base-render journal";
    notes.push(`${label}: ${source.state}. ${source.reason ?? "Only matching job records are included; this does not prove complete stage coverage."}`);
  }
  return notes;
}
