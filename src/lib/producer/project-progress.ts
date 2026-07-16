import {
  boundedAutoEditProgressMessage,
  eventElapsedSuffix,
} from "./auto-edit-progress";

export { boundedAutoEditProgressMessage } from "./auto-edit-progress";

function palmierPrimaryProgress(
  name: string,
  event: Record<string, unknown>,
): string | null {
  if (name === "palmier_primary_selected") {
    const limits = Array.isArray(event.limitations) ? event.limitations : [];
    const lanes = limits.map((item) => item && typeof item === "object"
      ? (item as Record<string, unknown>).lane : null).filter(Boolean).join(", ");
    return `Palmier-native build selected · editable timeline${lanes ? ` · declared limits: ${lanes}` : ""}`;
  }
  if (name === "palmier_primary_blocked" && typeof event.message === "string") {
    return `Palmier build blocked · ${event.message}`;
  }
  if (name === "candidate_qc_progress" && typeof event.message === "string") {
    return event.message;
  }
  if (name !== "palmier_native_progress") return null;
  if (typeof event.message === "string") return event.message;
  if (event.status === "operation_applied") {
    return `Palmier applied ${String(event.tool ?? "native edit")} · ${String(event.index ?? "?")} of ${String(event.total ?? "?")}`;
  }
  return typeof event.status === "string"
    ? `Palmier · ${event.status.replaceAll("_", " ")}` : null;
}

/** Human progress copy for the long-running Producer SSE routes. */
export function streamProgressMessage(event: Record<string, unknown>): string | null {
  const bounded = boundedAutoEditProgressMessage(event);
  if (bounded) return bounded;
  const name = typeof event.event === "string" ? event.event : "";
  const palmier = palmierPrimaryProgress(name, event);
  if (palmier) return palmier;
  const explicitBrain = typeof event.brain === "string" ? event.brain : null;
  const model = typeof event.model === "string" ? event.model : null;
  const brain = explicitBrain ?? (event.provider === "legacy"
    ? `Claude Code${model ? ` · ${model}` : ""}`
    : event.provider === "codex" ? "Codex" : "Editor brain");
  if (name === "start") return `Started · ${brain} is analyzing the transcript`;
  if (name === "authoring_started" && event.stage === "cut") {
    return `${brain} is authoring the transcript-first cut`;
  }
  if (name === "authoring_started") return `${brain} is authoring the governed visual plan`;
  if (name === "authoring_thread.started" || name === "authoring_turn.started") {
    return `${brain} authoring session started`;
  }
  if (name === "authoring_done" && event.stage === "cut") {
    return `Transcript cut authored${eventElapsedSuffix(event)} · independent cut review is next`;
  }
  if (name === "authoring_done") {
    return `Visual edit plan authored${eventElapsedSuffix(event)} · deterministic gates and planning review are next`;
  }
  if (name === "heartbeat" && typeof event.message === "string") return event.message;
  if (name === "intent_capability" && typeof event.message === "string") return event.message;
  if (name === "lint") return event.ok ? "Plan passed lint · preparing render" : "Plan failed lint";
  if (name === "phase" && event.phase === "assemble") return "Rendering base and final video";
  if (name === "outputs" && event.approved === true
      && event.mode === "palmier-native-initial") {
    return "Approved editable Palmier timeline is ready";
  }
  if (name === "outputs" && event.approved === true) return "Approved final video is ready";
  if (name === "outputs") return "Final video written · running QC";
  if (name === "error") return `Error · ${String(event.message ?? "pipeline failed")}`;
  const status = typeof event.status === "string" ? event.status.replaceAll("_", " ") : "";
  if (!status) return null;
  return [event.stage, status, event.note].filter(Boolean).join(" · ");
}
