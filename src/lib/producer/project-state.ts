import type { ProjectIntent } from "./intent-presets";
import type { AutoEditDeliveryPolicy } from "./auto-edit-delivery-policy";
import { runPhaseLabel } from "./project-progress";
import { isTreatmentCheckpoint, treatmentCheckpointCopy, treatmentCheckpointLabel, treatmentCheckpointSummary } from "./guided-checkpoint-state";

export {
  boundedAutoEditProgressMessage,
  streamProgressMessage,
  runPhaseLabel,
  runPhaseRemainingLabel,
  elapsedRunLabel,
} from "./project-progress";

export interface StageFlags {
  ingested: boolean;
  transcribed: boolean;
  plan: boolean;
  base: boolean;
  final: boolean;
}

export const STAGE_ORDER = ["ingested", "transcribed", "plan", "base", "final"] as const;
export type StageName = (typeof STAGE_ORDER)[number];

export type ProjectPhase =
  | "needs_ingest"
  | "needs_transcript"
  | "ready_to_generate"
  | "plan_ready"
  | "final_pending"
  | "complete"
  | "inconsistent";

export type ProjectAction = "ingest" | "generate" | "render_plan" | "assemble" | "open" | "repair";

export interface ProjectPhaseCopy {
  label: string;
  detail: string;
  tone: "neutral" | "ready" | "running" | "complete" | "error";
}

export interface ProjectCardSummary {
  available: string;
  working: string;
  next: string;
  safe: string;
}

export type ProducerRunPhase =
  | "authoring"
  | "planning_review"
  | "validating"
  | "rendering"
  | "quality_check"
  | "repairing";
export type ProducerRunStatus = "running" | "failed" | "interrupted" | "awaiting_cut_approval" | "cut_accepted"
  | "awaiting_treatment_brief" | "treatment_admitted";

export interface ProducerRunEvent {
  at: string;
  message: string;
}

export interface ProducerRunState {
  kind: "auto_edit" | "render";
  status: ProducerRunStatus;
  phase: ProducerRunPhase;
  startedAt: string;
  updatedAt: string;
  message: string;
  events: ProducerRunEvent[];
  /** Opaque current-attempt fence for local run controls; never a worker PID. */
  controlToken?: string;
  /** Present only when a matching, valid durable Auto Edit journal proves it. */
  deliveryPolicy?: AutoEditDeliveryPolicy;
  /** Present only when proved by the matching durable cut-first journal. */
  workflowPolicy?: "cut-first";
  /** Proved only by the matching closed, versioned durable launch context. */
  workflowVersion?: 2;
}

const PHASE_COPY: Record<ProjectPhase, ProjectPhaseCopy> = {
  needs_ingest: {
    label: "Needs media preparation",
    detail: "The saved media has not been prepared for video creation yet.",
    tone: "neutral",
  },
  needs_transcript: {
    label: "Needs speech analysis",
    detail: "The media is ready, but its spoken content has not been analyzed.",
    tone: "ready",
  },
  ready_to_generate: {
    label: "Ready to create",
    detail: "The media and spoken content are ready. The video has not been created yet.",
    tone: "ready",
  },
  plan_ready: {
    label: "Edit ready to render",
    detail: "The edit is planned, but the playable video has not been rendered.",
    tone: "ready",
  },
  final_pending: {
    label: "Ready to resume review",
    detail: "The saved edit and base cut exist. Resume plan review, rendering, and QC to produce the approved video.",
    tone: "ready",
  },
  complete: {
    label: "Finished",
    detail: "The edit plan and final video exist.",
    tone: "complete",
  },
  inconsistent: {
    label: "Project files need attention",
    detail: "Some expected project files are missing or out of order. Open details, then check again.",
    tone: "error",
  },
};

export function projectPhase(stages: StageFlags): ProjectPhase {
  if (stages.transcribed && !stages.ingested) return "inconsistent";
  if ((stages.base || stages.final) && !stages.plan) return "inconsistent";
  if (stages.final && stages.plan) return "complete";
  if (stages.base && stages.plan) return "final_pending";
  if (stages.plan) return "plan_ready";
  if (stages.transcribed) return "ready_to_generate";
  if (stages.ingested) return "needs_transcript";
  return "needs_ingest";
}

export function projectPhaseCopy(stages: StageFlags, run?: ProducerRunState | null): ProjectPhaseCopy {
  const treatment = treatmentCheckpointCopy(run);
  if (treatment) return treatment;
  if (run?.status === "cut_accepted") {
    return { label: "Cut accepted · continuation pending", detail: "Your cut acceptance is saved. A production worker has not yet been confirmed.", tone: "ready" };
  }
  if (run?.status === "awaiting_cut_approval") {
    return { label: "Cut ready for your review", detail: "Play the reviewed cut before the visual treatment stage. This is not a finished video.", tone: "ready" };
  }
  if (run?.status === "running") {
    return { label: runPhaseLabel(run.phase), detail: run.message, tone: "running" };
  }
  if (run?.status === "interrupted") {
    const action = run.kind === "auto_edit"
      ? "Choose Resume Edit to continue from the last safe checkpoint."
      : "Choose Resume review & QC to safely restart the unfinished render.";
    const label = run.kind === "auto_edit" ? "Edit interrupted" : "Render interrupted";
    return { label, detail: `${run.message} ${action}`, tone: "error" };
  }
  if (run?.status === "failed") {
    const label = stages.final
      ? "Finished · QC needs attention"
      : run.kind === "auto_edit" ? "Generation failed" : "Render failed";
    const action = run.kind === "auto_edit"
      ? " The last safe checkpoint is saved; choose Resume Edit to continue without repeating completed work."
      : "";
    return { label, detail: `${run.message}${action}`, tone: "error" };
  }
  return PHASE_COPY[projectPhase(stages)];
}

export function canResumeAutoEdit(run?: ProducerRunState | null): boolean {
  return !isTreatmentCheckpoint(run) && run?.kind === "auto_edit" && ["failed", "interrupted"].includes(run.status);
}

export function nextProjectAction(stages: StageFlags): ProjectAction {
  const phase = projectPhase(stages);
  if (phase === "complete") return "open";
  if (phase === "final_pending") return "assemble";
  if (phase === "plan_ready") return "render_plan";
  if (phase === "ready_to_generate") return "generate";
  if (phase === "inconsistent") return "repair";
  return "ingest";
}

export function canOpenProject(stages: StageFlags): boolean {
  return stages.plan;
}

/** User-facing primary action for every resumable project state. */
export function projectPrimaryActionLabel(
  stages: StageFlags,
  run?: ProducerRunState | null,
): string {
  if (isTreatmentCheckpoint(run)) return treatmentCheckpointLabel(run);
  if (run?.status === "cut_accepted") return "Continue accepted cut";
  if (run?.status === "awaiting_cut_approval") return "Review cut";
  if (canResumeAutoEdit(run)) return "Resume edit";
  if (run?.status === "failed") {
    return run.kind === "auto_edit" ? "Retry edit" : "Retry review & render";
  }
  const action = nextProjectAction(stages);
  if (action === "ingest") return stages.ingested ? "Analyze speech" : "Prepare media";
  if (action === "generate") return "Create first edit";
  if (action === "render_plan") return "Start render & QC";
  if (action === "assemble") return "Resume review & QC";
  if (action === "open") return "Open editor";
  return "Check project files";
}

const AVAILABLE_COPY: Record<ProjectPhase, string> = {
  needs_ingest: "The project folder exists, but its media has not been prepared.",
  needs_transcript: "Prepared source media exists; speech analysis is still missing.",
  ready_to_generate: "The source media and speech analysis are ready.",
  plan_ready: "A saved edit timeline exists; Palmier can open a source working view while video review is still pending.",
  final_pending: "A saved edit timeline and base preview exist; Palmier can open that latest saved cut before delivery approval.",
  complete: "An approved video and its managed Palmier timeline are ready.",
  inconsistent: "Some project files exist, but the saved stages are incomplete or out of order.",
};

const RUNNING_COPY: Record<ProducerRunPhase, { working: string; next: string }> = {
  authoring: {
    working: "Sniper is creating the first edit timeline.",
    next: "Independent edit reviews, a private render, and final video review follow.",
  },
  planning_review: {
    working: "Sniper is reviewing the edit timeline.",
    next: "After the timeline passes review, Sniper renders a private review copy.",
  },
  validating: {
    working: "Sniper is checking the edit for structural problems.",
    next: "Next, Sniper renders and reviews the actual video.",
  },
  rendering: {
    working: "Sniper is rendering a private review copy.",
    next: "Next, Sniper reviews the video and either approves it or corrects it.",
  },
  quality_check: {
    working: "Sniper is reviewing the rendered video for visual and editorial problems.",
    next: "A passing video is approved; otherwise Sniper corrects it and reviews it again.",
  },
  repairing: {
    working: "Sniper is correcting problems found during video review.",
    next: "The corrected edit is reviewed again before a new video is rendered.",
  },
};

/** Plain-language snapshot for the main Continue card; technical detail stays behind disclosure. */
export function projectCardSummary(
  stages: StageFlags,
  run?: ProducerRunState | null,
  hasStoredIntent = true,
): ProjectCardSummary {
  const treatment = treatmentCheckpointSummary(run);
  if (treatment) return treatment;
  const available = AVAILABLE_COPY[projectPhase(stages)];
  if (run?.status === "cut_accepted") {
    return { available: "Your exact cut acceptance is saved; this is not final-video approval.",
      working: "Continuation is pending. Sniper has not confirmed that a production worker is running.",
      next: "Continue the accepted cut using its saved acceptance, without making a new edit request.",
      safe: "Closing the project does not discard acceptance. Ordinary Generate and Resume cannot bypass the pending continuation." };
  }
  if (run?.status === "awaiting_cut_approval") {
    return { available: "An independently reviewed story cut and private playback checkpoint are saved.",
      working: run.message || "The job is at cut review; inspect the checkpoint for decision and verification status.",
      next: "Choose Review cut to watch the exact preview. It is not an approved final.",
      safe: "Opening or playing the preview does not accept the cut. Ordinary Generate and Resume cannot bypass this checkpoint." };
  }
  if (run?.status === "running") {
    return {
      available,
      ...RUNNING_COPY[run.phase],
      safe: "Open Palmier, go back, or start another project; this job keeps running. Opening alone changes nothing. A manual Palmier edit becomes the newer working revision and cannot be overwritten by this older attempt. Stop and keep the checkpoint before changing source assets or asking AI for another edit.",
    };
  }
  const action = projectPrimaryActionLabel(stages, run);
  const working = run?.status === "interrupted"
    ? "The previous job stopped; its completed checkpoint is saved."
    : run?.status === "failed"
      ? "The previous attempt stopped before completing this project."
      : "Nothing is running in the background.";
  return {
    available,
    working,
    next: !hasStoredIntent && ["generate", "render_plan", "assemble"].includes(nextProjectAction(stages))
      ? "Choose Short or Long and an edit level, then save the request to unlock Palmier and resume safely."
      : action === "Open editor"
      ? "Open the project to watch the approved video or make changes."
      : `Choose ${action} to continue from this saved stage.`,
    safe: "Open Palmier at any saved stage. Opening alone changes nothing; manual Palmier edits become the working revision used by the next governed AI change.",
  };
}

export function requestedEditLabel(intent: ProjectIntent): string {
  const format = intent.mode === "longform" ? "Long (16:9)" : "Short (9:16)";
  const level = `${intent.scope[0].toUpperCase()}${intent.scope.slice(1)} edit`;
  return `${format} · ${level}`;
}
