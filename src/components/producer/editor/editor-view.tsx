"use client";

import type { EditPlan } from "@/lib/producer/edit-plan";
import { projectCardSummary } from "@/lib/producer/project-state";
import { useProjectStatus, type ProjectStatus } from "../use-project-status";
import EditorSurface, { confirmedBack } from "./editor-view-sections";
import { useEditorController } from "./use-editor-controller";
import CutReviewPanel from "../cut-review-panel";
import CutAcceptedPanel from "../cut-accepted-panel";
import GuidedOpeningPanel from "../guided-opening-panel";
import { isTreatmentCheckpoint, treatmentCheckpointLabel, treatmentCheckpointLockReason, TREATMENT_INTEGRATION_NOTICE } from "@/lib/producer/guided-checkpoint-state";

interface Props {
  plan: EditPlan;
  dir: string;
  title?: string;
  onBack?: () => void;
}

// Thin entry point: behavior lives in focused editor hooks; the stable visual
// composition lives in editor-view-sections. This keeps the public API intact.
export default function EditorView({ plan, dir, title, onBack }: Props) {
  const project = useProjectStatus(dir);
  const externalLockReason = editorRunLockReason(project.status, project.error);
  const palmierLockReason = palmierTimelineLockReason(project.status);
  const editor = useEditorController({
    initialPlan: plan, dir, title, externalLockReason, palmierLockReason,
  });
  const checkpointBack = confirmedBack(onBack, editor.planState.history.dirty);
  if (!project.status) return <CheckpointNotice title={title} onBack={checkpointBack}
    message={project.error ? "Project status could not be verified. The editor remains locked; no preview or timeline has been opened." : "Checking project status before opening the editor…"}
    onRefresh={project.refresh} />;
  if (isTreatmentCheckpoint(project.status.run)) return <CheckpointNotice title={title} onBack={checkpointBack}
    heading={treatmentCheckpointLabel(project.status.run)}
    message={project.error ? "Project status could not be reverified. Opening playback is hidden until status is current again." : TREATMENT_INTEGRATION_NOTICE}
    onRefresh={project.refresh}>
    {!project.error && project.status.run?.workflowVersion === 2 && project.status.run.status === "treatment_admitted"
      && <GuidedOpeningPanel key={JSON.stringify([dir, project.status.run.controlToken, project.status.run.updatedAt])} dir={dir} />}
  </CheckpointNotice>;
  const checkpoint = project.status?.run?.status;
  if (checkpoint === "awaiting_cut_approval" || checkpoint === "cut_accepted") {
    return <main className="min-h-0 flex-1 overflow-auto p-4">
      {checkpointBack && <button type="button" onClick={checkpointBack} className="mb-3 text-sm text-neutral-300">← Projects</button>}
      {checkpoint === "cut_accepted" ? <CutAcceptedPanel dir={dir} onStatusChanged={project.refresh} />
        : <CutReviewPanel dir={dir} onStatusChanged={project.refresh} />}
    </main>;
  }
  return (
    <EditorSurface
      editor={editor}
      title={title}
      onBack={onBack}
      onProjectStatusChanged={project.refresh}
    />
  );
}

/** The controller stays mounted so a status refresh never discards local edits. */
function CheckpointNotice(props: { title?: string; heading?: string; message: string; onBack?: () => void; onRefresh: () => void; children?: React.ReactNode }) {
  return <main className="min-h-0 flex-1 overflow-auto p-4">
    {props.onBack && <button type="button" onClick={props.onBack} className="mb-3 text-sm text-neutral-300">← Projects</button>}
    {props.title && <p className="mb-2 text-sm text-neutral-400">{props.title}</p>}
    {props.heading && <h1 className="mb-2 font-medium">{props.heading}</h1>}
    <p role="status" className="text-sm text-neutral-300">{props.message}</p>
    <button type="button" onClick={props.onRefresh} className="mt-3 text-sm underline">Recheck project status</button>
    {props.children}
  </main>;
}

/** Palmier owns timeline mutations as soon as a managed workspace exists. */
export function palmierTimelineLockReason(status: ProjectStatus | null): string | null {
  const palmier = status?.palmier;
  if (!palmier || palmier.state === "no_workspace") return null;
  if (palmier.state === "unavailable") {
    return "Sniper found a Palmier workspace record it cannot verify. Timeline controls stay read-only to avoid overwriting Palmier; repair the Palmier connection or ask AI after Palmier is available.";
  }
  return "Palmier is this project's source of truth. Sniper timeline controls are read-only; review or edit in Palmier, or use Ask AI to create a governed candidate.";
}

/** Fail closed until the shared project run state proves timeline writes are safe. */
export function editorRunLockReason(
  status: ProjectStatus | null,
  error: string | null,
): string | null {
  const treatment = treatmentCheckpointLockReason(status?.run);
  if (treatment) return treatment;
  if (status?.run?.status === "cut_accepted") {
    return "Your cut is accepted; continuation is pending. Timeline changes stay locked until its worker starts or the checkpoint is explicitly canceled.";
  }
  if (status?.run?.status === "awaiting_cut_approval") {
    return "Review the exact cut preview before continuing. Timeline changes are locked while this cut checkpoint awaits your decision.";
  }
  if (status?.run?.status === "running") {
    const summary = projectCardSummary(status.stages, status.run);
    return `${summary.working} ${summary.next} You can watch and inspect the project, but timeline changes stay locked until the job finishes or you stop and keep its checkpoint.`;
  }
  if (error) return "Sniper could not verify whether this project is still running, so timeline changes remain locked.";
  if (!status) return "Checking whether another Sniper job is changing this project…";
  return null;
}
