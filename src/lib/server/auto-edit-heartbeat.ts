export const AUTO_EDIT_BRAIN_HEARTBEAT_MS = 30_000;

type IntervalHandle = ReturnType<typeof setInterval>;

export interface BrainHeartbeatClock {
  now: () => number;
  schedule: (callback: () => void, intervalMs: number) => IntervalHandle;
  cancel: (handle: IntervalHandle) => void;
}

export interface BrainHeartbeat {
  observe: (payload: Record<string, unknown>) => void;
  stop: () => void;
}

const SYSTEM_CLOCK: BrainHeartbeatClock = {
  now: Date.now,
  schedule: (callback, intervalMs) => setInterval(callback, intervalMs),
  cancel: (handle) => clearInterval(handle),
};

function renderedCriticLabel(payload: Record<string, unknown>): string {
  if (payload.lens === "composition") return "Composition critic still reviewing";
  if (payload.lens === "editorial") return "Editorial critic still reviewing";
  return "Visual critic still reviewing";
}

/** A string starts/replaces an activity, null stops it, undefined leaves it alone. */
export function brainHeartbeatTransition(
  payload: Record<string, unknown>,
): string | null | undefined {
  const event = typeof payload.event === "string" ? payload.event : "";
  if (event === "start" && payload.phase === "authoring") return "Editor brain still authoring";
  if (event === "authoring_thread.started" || event === "authoring_turn.started") {
    return "Editor brain still authoring";
  }
  if (event === "authoring_done") return null;
  if (event === "planning_review_started") return "Plan critic still reviewing";
  if (event === "planning_review_completed") return null;
  if (event === "revision_started") return "Plan revision writer still revising";
  if (event === "revision_completed") return null;
  if (event === "rendered_review_started") return renderedCriticLabel(payload);
  if (event === "rendered_review_completed") return null;
  if (event === "repair_started") return "QC repair writer still revising";
  if (event === "repair_completed") return null;
  if (event === "complete" || event === "error" || event === "interrupted") return null;
  return undefined;
}

export function brainHeartbeatMessage(label: string, startedAt: number, now: number): string {
  const elapsedMs = Math.max(0, now - startedAt);
  const minutes = Math.floor(elapsedMs / 60_000);
  const seconds = Math.floor((elapsedMs % 60_000) / 30_000) * 30;
  const elapsed = minutes > 0
    ? `${minutes}m${seconds ? ` ${seconds}s` : ""} elapsed`
    : `${Math.floor(elapsedMs / 1_000)}s elapsed`;
  return `${label} · ${elapsed}`;
}

/** One bounded timer for the currently-active brain call; ticks never append logs. */
export function createBrainHeartbeat(
  write: (message: string) => void,
  clock: BrainHeartbeatClock = SYSTEM_CLOCK,
): BrainHeartbeat {
  let handle: IntervalHandle | null = null;
  let label: string | null = null;
  let startedAt = 0;

  const stop = () => {
    if (handle) clock.cancel(handle);
    handle = null;
    label = null;
  };
  const start = (nextLabel: string) => {
    if (handle && label === nextLabel) return;
    stop();
    label = nextLabel;
    startedAt = clock.now();
    handle = clock.schedule(() => {
      if (!label) return;
      try { write(brainHeartbeatMessage(label, startedAt, clock.now())); } catch {}
    }, AUTO_EDIT_BRAIN_HEARTBEAT_MS);
    handle.unref?.();
  };
  return {
    observe(payload) {
      const transition = brainHeartbeatTransition(payload);
      if (transition === null) stop();
      else if (transition) start(transition);
    },
    stop,
  };
}
