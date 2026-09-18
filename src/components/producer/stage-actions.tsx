"use client";

import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { readEventStream } from "@/lib/producer/sse";
import { intentBadge } from "@/lib/producer/intent-presets";
import { buildAutoEditRequest, buildResumeAutoEditRequest } from "@/lib/producer/intent-flow";
import { approvedOutputEvent } from "@/lib/producer/editor-preview-authority";
import { isTreatmentCheckpoint, TREATMENT_INTEGRATION_NOTICE } from "@/lib/producer/guided-checkpoint-state";
import {
  canResumeAutoEdit,
  nextProjectAction,
  streamProgressMessage,
} from "@/lib/producer/project-state";
import { derror } from "@/lib/debug";
import {
  ActionShell,
  ActiveRun,
  LocalRun,
  Spinner,
  type SseState,
} from "./stage-action-status";
import type { ProjectStatus } from "./use-project-status";
import MissingIntentAction from "./missing-intent-action";
import { CutReviewControl } from "./cut-review-panel";
import { IngestAction, type IngestedPayload } from "./stage-ingest";
import {
  editorBrainLabel,
  launchAutoEditFromHyperframes,
  launchAutoEditFromPalmier,
  useEditorRuntime,
} from "./use-editor-runtime";

export { ingestInto } from "./stage-ingest";
export type { IngestedPayload } from "./stage-ingest";

/** Shared runner state + wrapper so every action button behaves the same. */
function useSseAction(onDone: () => void): [
  SseState,
  (operation: SseState["operation"], fn: () => Promise<void>) => void,
  (event: Record<string, unknown>) => void,
] {
  const [state, setState] = useState<SseState>({ running: false, error: null, progress: null, logs: [] });
  const onEvent = (event: Record<string, unknown>) => {
    const message = streamProgressMessage(event);
    if (!message) return;
    setState((current) => ({
      ...current,
      progress: message,
      logs: [...(current.logs ?? []), message].slice(-12),
    }));
  };
  const run = (operation: SseState["operation"], fn: () => Promise<void>) => {
    setState({ running: true, error: null, progress: "Starting…", logs: [], operation });
    fn()
      .then(() => setState((current) => ({ ...current, running: false, error: null })))
      .catch((e) => {
        derror("producer:stage-action", "failed", e);
        const error = e instanceof Error ? e.message : String(e);
        setState((current) => ({ ...current, running: false, error, progress: `Error · ${error}` }));
      })
      .finally(onDone);
  };
  return [state, run, onEvent];
}

interface ActionCtx {
  status: ProjectStatus;
  state: SseState;
  run: (operation: SseState["operation"], fn: () => Promise<void>) => void;
  onEvent: (event: Record<string, unknown>) => void;
  primary: boolean;
  brain: string;
}

async function runControllerAutoEdit(
  c: Pick<ActionCtx, "status" | "onEvent">,
  request: Record<string, unknown>,
  onEvent: (event: Record<string, unknown>) => void = c.onEvent,
  launch = launchAutoEditFromHyperframes,
): Promise<void> {
  const mode = c.status.intent?.mode;
  if (!mode) throw new Error("Choose Short or Long before starting the edit.");
  const response = await launch({
    dir: c.status.producerDir,
    mode,
    request,
  });
  await readEventStream(response, (event) => {
    onEvent(event as Record<string, unknown>);
    if (event.event === "error") throw new Error(String(event.message ?? "stream error"));
  }, undefined, request.workflowPolicy === "cut-first" ? ["outputs", "awaiting_cut_approval"] : "outputs");
}

function reviewSavedPlan(c: ActionCtx): Promise<void> {
  return runControllerAutoEdit(
    c,
    { dir: c.status.producerDir, reviewSavedPlan: true },
    (event) => {
      c.onEvent(event);
      approvedOutputEvent(event);
    },
  );
}

function LaunchAction({ c, children, caption }: { c: ActionCtx; children: ReactNode; caption?: string }) {
  return (
    <span className="flex flex-col items-end gap-0.5">
      {children}
      <span className="text-right text-[9px] text-muted-foreground">
        {caption ?? <>{c.brain} · HyperFrames review · QC-approved MP4</>}
      </span>
    </span>
  );
}

function AutoEditAction({ c, label = "Create first edit" }: { c: ActionCtx; label?: string }) {
  const intent = c.status.intent;
  if (!intent) return <MissingIntentAction dir={c.status.producerDir} state={c.state} run={c.run} primary={c.primary} />;
  return (
    <ActionShell state={c.state}>
      <LaunchAction c={c}>
        <Button
          variant={c.primary ? "default" : "ghost"}
          size="xs"
          disabled={c.state.running}
          title={`The configured AI editor authors edit_plan.json honoring the stored intent (${intentBadge(intent)}), then assemble renders it (SSE)`}
          onClick={() => c.run("auto_edit", () => runControllerAutoEdit(
            c,
            buildAutoEditRequest(c.status.producerDir, intent),
          ))}
        >
          <Spinner on={c.state.running} /> {c.state.running ? "Generating…" : label}
        </Button>
        <span className="text-[9px] uppercase tracking-wide text-muted-foreground" title="Stored operator intent">
          {intentBadge(intent)}
        </span>
      </LaunchAction>
    </ActionShell>
  );
}

/** Resume the journal's proved delivery route; unknown policy never becomes a fresh run. */
export async function resumeSavedAutoEdit(
  status: ProjectStatus,
  onEvent: (event: Record<string, unknown>) => void,
): Promise<void> {
  const policy = status.run?.deliveryPolicy;
  if (!canResumeAutoEdit(status.run) || (policy !== "mp4-only" && policy !== "palmier-hybrid")) {
    throw new Error("The saved delivery policy is unavailable. Inspect the durable job journal before resuming.");
  }
  if (!status.intent) throw new Error("Stored edit intent is missing.");
  await runControllerAutoEdit({ status, onEvent },
    buildResumeAutoEditRequest(status.producerDir, status.intent, policy, status.run?.workflowPolicy), onEvent,
    policy === "palmier-hybrid" ? launchAutoEditFromPalmier : launchAutoEditFromHyperframes);
}

function ResumeEditAction({ c }: { c: ActionCtx }) {
  const intent = c.status.intent;
  if (!intent) {
    return <MissingIntentAction dir={c.status.producerDir} state={c.state} run={c.run} primary={c.primary} />;
  }
  const policy = c.status.run?.deliveryPolicy;
  const legacy = policy === "palmier-hybrid";
  const known = legacy || policy === "mp4-only";
  const caption = !known ? "Saved policy unavailable · inspect the job journal"
    : legacy ? `${c.brain} · Legacy Palmier · original delivery policy` : undefined;
  const resume = () => resumeSavedAutoEdit(c.status, c.onEvent);
  return (
    <ActionShell state={c.state}>
      <LaunchAction c={c} caption={caption}>
        <Button
          type="button"
          variant={c.primary ? "default" : "ghost"}
          size="xs"
          disabled={c.state.running || !known}
          title={known ? "Continue this interrupted edit with its original delivery policy"
            : "The durable job's delivery policy could not be verified; inspect it before resuming"}
          onClick={() => c.run("resume_edit", resume)}
        >
          <Spinner on={c.state.running} /> {!known ? "Resume unavailable"
            : legacy ? "Resume legacy Palmier edit" : "Resume Edit"}
        </Button>
      </LaunchAction>
    </ActionShell>
  );
}

function RenderPlanAction({ c, label = "Start render & QC" }: { c: ActionCtx; label?: string }) {
  return (
    <ActionShell state={c.state}>
      <LaunchAction c={c}>
        <Button
          variant={c.primary ? "default" : "ghost"}
          size="xs"
          disabled={c.state.running || !c.status.intent}
          title={c.status.intent
            ? "Review the saved plan, render an isolated candidate, and promote it only after QC approval"
            : "Stored edit intent is missing"}
          onClick={() => c.run("render", () => reviewSavedPlan(c))}
        >
          <Spinner on={c.state.running} /> {c.state.running ? "Rendering…" : label}
        </Button>
      </LaunchAction>
    </ActionShell>
  );
}

function RerenderAction({ c }: { c: ActionCtx }) {
  return (
    <ActionShell state={c.state}>
      <LaunchAction c={c}>
        <Button
          variant={c.primary ? "default" : "ghost"}
          size="xs"
          disabled={c.state.running || !c.status.intent}
          title={c.status.intent
            ? "Review the saved plan, render an isolated candidate, and promote it only after QC approval"
            : "Stored edit intent is missing"}
          onClick={() => c.run("render", () => reviewSavedPlan(c))}
        >
          <Spinner on={c.state.running} /> {c.state.running ? "Reviewing & rendering…" : "Resume review & QC"}
        </Button>
      </LaunchAction>
    </ActionShell>
  );
}

function RecoveryActions({ c }: { c: ActionCtx }) {
  const { status } = c;
  const canOfferAlternative = status.run?.workflowPolicy !== "cut-first";
  let alternative: ReactNode = null;
  if (canOfferAlternative && status.run?.status === "failed" && status.stages.plan) {
    alternative = <RenderPlanAction c={{ ...c, primary: false }} label="Resume review & QC" />;
  }
  if (canOfferAlternative && status.run?.status !== "failed" && status.intent) {
    alternative = <AutoEditAction c={{ ...c, primary: false }} label="Retry fresh" />;
  }
  return <div className="flex flex-wrap items-start justify-end gap-1"><ResumeEditAction c={c} />{alternative}</div>;
}

export function StageActionButton({
  status,
  onIngested,
  onRefresh,
  primary = false,
}: {
  status: ProjectStatus;
  onIngested?: (p: IngestedPayload) => void;
  onRefresh: () => void;
  primary?: boolean;
}) {
  const [state, run, onEvent] = useSseAction(onRefresh);
  const runtime = useEditorRuntime();
  if (status.run?.status === "running") {
    return <ActiveRun run={status.run} dir={status.producerDir} onStopped={onRefresh} />;
  }
  if (isTreatmentCheckpoint(status.run)) return <Button variant="ghost" size="xs"
    title={TREATMENT_INTEGRATION_NOTICE} onClick={onRefresh}>Recheck guided checkpoint</Button>;
  if (status.run?.status === "awaiting_cut_approval") return <CutReviewControl dir={status.producerDir} onStatusChanged={onRefresh} />;
  if (status.run?.status === "cut_accepted") return <CutReviewControl dir={status.producerDir} accepted onStatusChanged={onRefresh} />;
  if (state.running) return <LocalRun state={state} />;
  const action = nextProjectAction(status.stages);
  const c: ActionCtx = { status, state, run, onEvent, primary, brain: editorBrainLabel(runtime) };
  if (canResumeAutoEdit(status.run)) return <RecoveryActions c={c} />;
  if (!status.intent && ["generate", "render_plan", "assemble"].includes(action)) {
    return <MissingIntentAction dir={status.producerDir} state={state} run={run} primary={primary} />;
  }
  if (action === "ingest") {
    return <IngestAction status={status} state={state} run={run} onEvent={onEvent}
      primary={primary} reingest={status.stages.ingested} onIngested={onIngested} />;
  }
  if (action === "generate") return <AutoEditAction c={c} />;
  if (action === "render_plan") {
    return (
      <div className="flex flex-wrap items-start justify-end gap-1">
        <AutoEditAction c={{ ...c, primary: false }} label="Regenerate edit" />
        <RenderPlanAction c={c} />
      </div>
    );
  }
  if (action === "assemble") return <RerenderAction c={c} />;
  if (action === "repair") {
    return <Button variant={primary ? "default" : "ghost"} size="xs" onClick={onRefresh}>Check project files</Button>;
  }
  return null;
}
