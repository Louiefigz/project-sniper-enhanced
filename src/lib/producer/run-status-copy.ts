import type { ProducerRunState } from "./project-state";

const FAILURE_COPY: Array<[RegExp, string]> = [
  [
    /no eligible b-?roll|no cutaways? (?:were )?found/i,
    "No cutaways were available. The edit can continue without them, or you can add cutaways and rescan before retrying.",
  ],
  [
    /deterministic planning gates? failed|plan(?:ning)? (?:lint|gate).*(?:fail|error)/i,
    "The saved edit plan did not pass its required review. Your checkpoint is safe; retry to revise and review it again.",
  ],
  [
    /max(?:imum)? (?:qc|quality).*(?:round|attempt)|unresolved (?:qc|quality).*(?:finding|issue)/i,
    "Quality review still found problems after the allowed repair attempts. No unapproved candidate was promoted.",
  ],
  [
    /ffmpeg|render(?:ing)? (?:failed|exited|stopped)|assemble.*(?:failed|error)/i,
    "Video rendering stopped before a review copy was completed. The saved edit is still available to retry.",
  ],
  [
    /enoent|no such file|missing (?:file|manifest|asset)|manifest.*(?:not found|missing)/i,
    "A required project or media file could not be found. Check the project files, then retry from the saved stage.",
  ],
  [
    /timed? ?out|timeout/i,
    "A review or rendering step took longer than its safety limit. The last completed checkpoint is still saved.",
  ],
  [
    /(?:process|worker|command).*(?:exit|signal|stopp|died)|exited with (?:code|status)/i,
    "A background editing process stopped before finishing. Resume or retry from the last saved checkpoint.",
  ],
  [
    /palmier.*(?:closed|unavailable|connect|project|timeline)/i,
    "Sniper could not reach the expected Palmier project or timeline. Reopen the correct project, then try again.",
  ],
];

/** Translate known implementation failures without discarding the original diagnostic. */
export function plainRunFailureMessage(raw: string): string {
  const normalized = raw.trim();
  if (!normalized) return "This attempt stopped before it could finish. Retry from the last saved checkpoint.";
  return FAILURE_COPY.find(([pattern]) => pattern.test(normalized))?.[1]
    ?? "This attempt stopped before it could finish. Retry from the last saved checkpoint; technical details are available below.";
}

export function elapsedLabel(startedAt: string, now = Date.now()): string {
  return `${compactAge(startedAt, now)} elapsed`;
}

export function heartbeatLabel(updatedAt: string, now = Date.now()): string {
  return `last progress ${compactAge(updatedAt, now)} ago`;
}

export function runTimingLabel(run: ProducerRunState, now = Date.now()): string {
  return `${elapsedLabel(run.startedAt, now)} · ${heartbeatLabel(run.updatedAt, now)}`;
}

export function eventTimestamp(at: string): string {
  const parsed = Date.parse(at);
  if (!Number.isFinite(parsed)) return at || "time unavailable";
  return new Date(parsed).toISOString().replace("T", " ").replace(".000Z", "Z");
}

function compactAge(value: string, now: number): string {
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return "unknown";
  const seconds = Math.max(0, Math.floor((now - parsed) / 1_000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}
