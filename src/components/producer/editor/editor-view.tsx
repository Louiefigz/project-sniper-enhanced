"use client";

import type { EditPlan } from "@/lib/producer/edit-plan";
import { projectCardSummary } from "@/lib/producer/project-state";
import { useProjectStatus, type ProjectStatus } from "../use-project-status";
import EditorSurface from "./editor-view-sections";
import { useEditorController } from "./use-editor-controller";

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
  return (
    <EditorSurface
      editor={editor}
      title={title}
      onBack={onBack}
      onProjectStatusChanged={project.refresh}
    />
  );
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
  if (status?.run?.status === "running") {
    const summary = projectCardSummary(status.stages, status.run);
    return `${summary.working} ${summary.next} You can watch and inspect the project, but timeline changes stay locked until the job finishes or you stop and keep its checkpoint.`;
  }
  if (error) return "Sniper could not verify whether this project is still running, so timeline changes remain locked.";
  if (!status) return "Checking whether another Sniper job is changing this project…";
  return null;
}
