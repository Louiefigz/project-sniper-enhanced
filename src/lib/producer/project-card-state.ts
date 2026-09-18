import type { ProjectIntent } from "./intent-presets";
import type { CandidateQcAction } from "./candidate-qc-action";
import { isGuidedCheckpoint } from "./guided-checkpoint-state";
import {
  nextProjectAction,
  projectPrimaryActionLabel,
  projectCardSummary,
  type ProducerRunState,
  type StageFlags,
} from "./project-state";

export type PalmierProjectStateKind =
  | "no_workspace"
  | "source_bootstrap"
  | "saved_cut"
  | "approved_mirror"
  | "approved_working_head"
  | "manual_working_head"
  | "commit_recovery"
  | "reconciliation_required"
  | "pending_candidate"
  | "approved_candidate"
  | "rejected_candidate"
  | "quarantined_candidate"
  | "previous_export"
  | "unavailable";

export interface PalmierProjectState {
  state: PalmierProjectStateKind;
  canOpen: boolean;
  projectPath: string | null;
  projectId: string | null;
  timelineId: string | null;
  verified: boolean;
  authorityOrigin: string | null;
  approvedTimelineId?: string | null;
  approvalCurrent?: boolean;
  candidateQc?: {
    state: "none" | "pending" | "prepared" | "checking" | "approved"
      | "commit-recovery" | "reconciliation"
      | "stale" | "rejected" | "quarantined";
    active: boolean;
    action: CandidateQcAction | null;
    canRunQc: boolean;
    canPromote: boolean;
    canDiscard: boolean;
    step: string | null;
    message: string | null;
  };
  candidateApprovalStale?: boolean;
  detail: string;
}

export interface FinalArtifactState {
  state: "missing" | "unapproved" | "approved";
  path: string | null;
  reason: string | null;
}

export interface ProjectCardStateInput {
  origin: "segmenter" | "clipper" | "raw" | null;
  intent: ProjectIntent | null;
  stages: StageFlags;
  run: ProducerRunState | null;
  palmier: PalmierProjectState;
  finalArtifact: FinalArtifactState;
  segmentCount: number;
  clipperFileCount: number;
}

export type ProjectCardPrimary =
  | "stage"
  | "open_sniper"
  | "open_palmier"
  | "reveal_clipper"
  | "choose_segment";

export interface ProjectCardPresentation {
  label: string;
  available: string;
  working: string;
  next: string;
  safe: string;
  primary: ProjectCardPrimary;
}

function specialOrigin(input: ProjectCardStateInput): ProjectCardPresentation | null {
  if (input.origin === "clipper" && input.clipperFileCount > 0 && !input.stages.plan) {
    return {
      label: "Final Cut timeline ready",
      available: "A Final Cut Pro timeline was created by Clipper.",
      working: "Nothing is running in the background.",
      next: "Reveal the timeline and open it in Final Cut Pro.",
      safe: "This project is a Clipper export; Producer media preparation is not required.",
      primary: "reveal_clipper",
    };
  }
  if (input.origin === "segmenter" && input.segmentCount > 0 && !input.stages.ingested) {
    return {
      label: "Source clips ready",
      available: `${input.segmentCount} saved clip${input.segmentCount === 1 ? " is" : "s are"} ready to become a video.`,
      working: "Nothing is running in the background.",
      next: "Choose a clip below to prepare it as a new Producer edit.",
      safe: "Creating from one clip does not remove or change the other clips.",
      primary: "choose_segment",
    };
  }
  return null;
}

function palmierRevision(input: ProjectCardStateInput): ProjectCardPresentation | null {
  if (input.palmier.state === "commit_recovery"
      || input.palmier.state === "reconciliation_required") {
    const blocked = input.palmier.state === "reconciliation_required";
    return {
      label: blocked ? "Palmier commit needs reconciliation" : "Palmier commit needs recovery",
      available: blocked
        ? "Palmier and the local revision authority do not form one proved commit."
        : "Palmier selected the approved candidate; its reserved local revision is not committed yet.",
      working: "No completed dual commit is being reported.",
      next: blocked
        ? "Inspect the retained saga before any further promotion."
        : "Resume Use approved candidate to finish the exact durable commit.",
      safe: "The saga preserves both observed heads and never reports a partial commit as complete.",
      primary: "open_palmier",
    };
  }
  if (input.palmier.state === "approved_working_head") {
    return {
      label: "Palmier edit approved",
      available: "The exact editable Palmier timeline passed deterministic and rendered QC and is the current approved working head.",
      working: "Nothing is changing this timeline in the background.",
      next: "Open the approved timeline in Palmier to review it or continue editing.",
      safe: "Manual Palmier changes become a new unapproved working revision; the last approved head stays recorded separately.",
      primary: "open_palmier",
    };
  }
  if (input.palmier.state === "quarantined_candidate") {
    return {
      label: "Palmier candidate stopped safely",
      available: "The failed AI copy is quarantined; the preserved parent remains canonical.",
      working: "Nothing is changing either timeline in the background.",
      next: "Restore and verify the exact parent by choosing Discard candidate & keep parent; the failed copy is archived before you ask again.",
      safe: "Recovery never approves the failed candidate or discards its diagnostic receipt.",
      primary: "open_palmier",
    };
  }
  if (input.palmier.state === "pending_candidate") {
    const active = input.palmier.candidateQc?.active === true;
    const staleApproval = input.palmier.candidateApprovalStale === true;
    return {
      label: staleApproval ? "Palmier candidate approval is stale" : "Palmier candidate needs review",
      available: staleApproval
        ? "The prior approval no longer matches the candidate receipt or export evidence. This candidate is not approved."
        : "The current Palmier edit is preserved, and an AI-edited candidate is ready separately.",
      working: active
        ? input.palmier.candidateQc?.message ?? "Candidate QC is running in the background."
        : "Nothing is changing the parent timeline in the background.",
      next: staleApproval
        ? "Inspect it if useful, then discard it safely before asking AI for a fresh governed candidate."
        : active
        ? "You may leave this page; return to the saved project to see the next durable QC checkpoint."
        : "Open the review-only candidate in Palmier, then run its exported deterministic and visual QC.",
      safe: "Opening does not accept it. A deliberate manual edit makes that visible revision the new unapproved working truth.",
      primary: "open_palmier",
    };
  }
  if (input.palmier.state === "approved_candidate") {
    return {
      label: "Palmier candidate approved",
      available: "The separate candidate passed exported deterministic, composition, and editorial QC.",
      working: "Nothing is changing the parent or candidate in the background.",
      next: "Use approved candidate to make it the Palmier working source of truth.",
      safe: "Promotion rechecks both timelines. If Palmier changed during review, nothing is overwritten.",
      primary: "open_palmier",
    };
  }
  if (input.palmier.state === "rejected_candidate") {
    return {
      label: "Palmier candidate QC stopped safely",
      available: "The rejected candidate and its QC evidence are archived. The verified parent remains current.",
      working: "Nothing is changing the preserved parent in the background.",
      next: "Open the preserved Palmier parent. Ask AI again only when you want a new governed candidate.",
      safe: "No rejected candidate was approved, promoted, or edited in place.",
      primary: "open_palmier",
    };
  }
  if (input.palmier.state === "manual_working_head") {
    return {
      label: "Palmier edit needs QC",
      available: input.palmier.approvedTimelineId
        ? "Palmier contains a newer manual working revision. The last approved delivery remains recorded separately."
        : "Palmier contains a newer manual working revision, which is now the source of truth.",
      working: "Nothing is changing this revision in the background.",
      next: "Review the current Palmier edit; the next AI request starts from this exact revision.",
      safe: "Sniper will not replace this manual work with an older saved plan.",
      primary: "open_palmier",
    };
  }
  return null;
}

function idlePipeline(input: ProjectCardStateInput): ProjectCardPresentation {
  const action = projectPrimaryActionLabel(input.stages, input.run);
  if (input.finalArtifact.state === "unapproved") {
    const missingIntent = !input.intent
      && ["generate", "render_plan", "assemble"].includes(nextProjectAction(input.stages));
    return {
      label: "Rendered — QC not approved",
      available: "A rendered review copy exists, but it did not earn current delivery approval.",
      working: input.run?.status === "failed" ? "The last review attempt failed." : "Nothing is running in the background.",
      next: missingIntent
        ? "Choose Short or Long and an edit level, then save the request before resuming review."
        : `Choose ${action} to correct or review it. The unapproved copy remains inspectable in Sniper.`,
      safe: input.finalArtifact.reason ?? "The unapproved render is never presented as the finished delivery.",
      primary: "stage",
    };
  }
  if (input.stages.final) {
    const managed = input.palmier.state === "approved_mirror";
    return {
      label: "Finished",
      available: managed
        ? "The approved video and its verified Palmier edit are ready."
        : "The approved Sniper video is ready. No current verified Palmier edit is being claimed.",
      working: "Nothing is running in the background.",
      next: managed ? "Open the approved edit in Palmier." : "Open the approved video in Sniper.",
      safe: managed
        ? "Palmier is the working source of truth for later manual or governed AI changes."
        : "A Palmier source view or previous export, if shown, is labeled separately from the approved delivery.",
      primary: managed ? "open_palmier" : "open_sniper",
    };
  }
  const missingIntent = !input.intent
    && ["generate", "render_plan", "assemble"].includes(nextProjectAction(input.stages));
  return {
    label: action,
    available: pipelineAvailable(input.stages),
    working: input.run?.status === "failed"
      ? "The previous attempt stopped before this project was completed."
      : input.run?.status === "interrupted"
        ? "The previous job stopped; its completed checkpoint is saved."
        : "Nothing is running in the background.",
    next: missingIntent
      ? "Choose Short or Long and an edit level, then save the request."
      : `Choose ${action} to continue from this saved stage.`,
    safe: "Existing saved work stays in place until a reviewed candidate passes its required checks.",
    primary: "stage",
  };
}

function pipelineAvailable(stages: StageFlags): string {
  if (stages.base) return "A saved edit and base preview exist; final QC is not complete.";
  if (stages.plan) return "A saved edit timeline exists; no approved video has been produced yet.";
  if (stages.transcribed) return "The source media and speech analysis are ready for editing.";
  if (stages.ingested) return "Prepared media exists; speech analysis is still missing.";
  return "The project exists, but Producer media has not been prepared.";
}

export function projectCardPresentation(input: ProjectCardStateInput): ProjectCardPresentation {
  if (isGuidedCheckpoint(input.run)) {
    return { ...projectCardSummary(input.stages, input.run),
      label: projectPrimaryActionLabel(input.stages, input.run), primary: "stage" };
  }
  if (input.run?.status === "running") {
    return {
      label: "Working in background",
      available: pipelineAvailable(input.stages),
      working: input.run.message,
      next: "Stop and keep the checkpoint if you need to change source assets or start another edit here.",
      safe: "You may leave this page or open another project without interrupting this detached job.",
      primary: "stage",
    };
  }
  return palmierRevision(input) ?? specialOrigin(input) ?? idlePipeline(input);
}

export function palmierActionLabel(palmier: PalmierProjectState, finished: boolean): string {
  const labels: Record<PalmierProjectStateKind, string> = {
    no_workspace: finished ? "Create Palmier workspace" : "Create Palmier source view",
    source_bootstrap: "Open Palmier source view",
    saved_cut: "Open saved cut in Palmier",
    approved_mirror: "Open approved Palmier edit",
    approved_working_head: "Open approved Palmier timeline",
    manual_working_head: "Open current Palmier edit",
    commit_recovery: "Resume Palmier commit",
    reconciliation_required: "Inspect Palmier reconciliation",
    pending_candidate: "Review Palmier candidate",
    approved_candidate: "Use approved candidate",
    rejected_candidate: "Open preserved Palmier parent",
    quarantined_candidate: "Restore preserved Palmier parent",
    previous_export: "Open previous Palmier export",
    unavailable: "Palmier workspace unavailable",
  };
  return labels[palmier.state];
}
