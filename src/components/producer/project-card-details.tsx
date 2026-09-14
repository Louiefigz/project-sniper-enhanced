"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { isGuidedCheckpoint } from "@/lib/producer/guided-checkpoint-state";
import { projectPhaseCopy } from "@/lib/producer/project-state";
import { eventTimestamp, plainRunFailureMessage } from "@/lib/producer/run-status-copy";
import type { IntentCapabilityDecision } from "@/lib/producer/intent-capabilities";
import { ingestInto, type IngestedPayload } from "./stage-actions";
import StageStrip from "./stage-strip";
import ProjectTimingDetails from "./project-timing-details";
import type { ProjectStatus } from "./use-project-status";

function PlanRefitReceipt({ status }: { status: ProjectStatus }) {
  const receipt = status.planRefit;
  if (!receipt) return null;
  const tone = receipt.dropped ? "border-amber-500/30 bg-amber-500/5" : "border-border/70 bg-background/30";
  return (
    <details className={`mt-2 rounded border p-2 ${tone}`}>
      <summary className="cursor-pointer text-foreground">
        Cut update receipt · {receipt.remapped} remapped · {receipt.dropped} removed
      </summary>
      <p className="mt-1">
        Output-timed elements were deterministically rebased before lint and review.
        {receipt.dropped ? " Removed items lost all of their source content in the new cut." : " No elements were dropped."}
      </p>
      {receipt.changes.length > 0 && (
        <ul className="mt-1 space-y-0.5 font-mono text-[10px]">
          {receipt.changes.map((change, index) => (
            <li key={`${change.track}:${change.index}:${index}`}>
              {change.action} · {change.track}[{change.index}]
              {change.reason ? ` · ${change.reason}` : ""}
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

export function ProjectDetails({ status }: { status: ProjectStatus }) {
  const copy = projectPhaseCopy(status.stages, status.run);
  const failed = status.run?.status === "failed";
  const detail = status.palmier.state === "approved_working_head"
    ? status.palmier.detail
    : status.run?.status === "failed"
    ? plainRunFailureMessage(status.run.message)
    : copy.detail;
  return (
    <div className="mt-2 rounded border border-border/70 bg-background/30 p-2 text-[11px] text-muted-foreground">
      <StageStrip status={status} />
      <p><span className="text-foreground">Current state:</span> {detail}</p>
      <p><span className="text-foreground">Palmier:</span> {status.palmier.detail}</p>
      {status.finalArtifact.state === "unapproved" && (
        <p className="text-amber-300"><span className="text-foreground">Review render:</span>{" "}
          Exists, but is not the approved delivery. {status.finalArtifact.reason}
        </p>
      )}
      {failed && (
        <details className="mt-1 text-[10px]">
          <summary className="cursor-pointer text-muted-foreground">Technical failure details</summary>
          <p className="mt-1 break-words font-mono text-destructive">{status.run?.message}</p>
        </details>
      )}
      {status.intentDecisions.map((decision) => (
        <p key={decision.code} className={decision.status === "blocked" ? "mt-1 text-amber-300" : "mt-1 text-muted-foreground"}>
          <span className="text-foreground">{decision.status === "blocked" ? "Choice needed:" : "Media note:"}</span> {decision.message}
        </p>
      ))}
      <p className="mt-1 truncate font-mono text-[10px]" title={status.producerDir}>{status.producerDir}</p>
      <PlanRefitReceipt status={status} />
      <ProjectTimingDetails report={status.timing} />
      {status.run?.events.length ? (
        <details className="mt-2 border-t border-border/60 pt-2 text-[10px]">
          <summary className="cursor-pointer text-muted-foreground">
            Technical progress log ({status.run.events.length})
          </summary>
          <div className="mt-1 space-y-0.5 font-mono">
            {status.run.events.map((item, index) => (
              <div key={`${index}:${item.at}:${item.message}`} className="grid gap-2 sm:grid-cols-[10.5rem_1fr]">
                <time dateTime={item.at} className="text-muted-foreground/70">{eventTimestamp(item.at)}</time>
                <span>{item.message}</span>
              </div>
            ))}
          </div>
        </details>
      ) : null}
    </div>
  );
}

export function CutawayDecision({ decision, status, onRevealSource, onIngested }: {
  decision: IntentCapabilityDecision;
  status: ProjectStatus;
  onRevealSource: () => void;
  onIngested?: (payload: IngestedPayload) => void;
}) {
  const [rescanning, setRescanning] = useState(false);
  const [error, setError] = useState("");
  const blocked = status.run?.status === "running" || isGuidedCheckpoint(status.run);
  const rescan = () => {
    if (!status.sourceDir || blocked) return;
    setRescanning(true);
    setError("");
    ingestInto(status.sourceDir, status.projectRoot, onIngested, { reuseTranscripts: true })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Could not rescan media"))
      .finally(() => setRescanning(false));
  };
  return (
    <div role="status" className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-100">
      <p className="font-medium text-foreground">No cutaways found</p>
      <p className="mt-1 text-muted-foreground">{decision.message}</p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <span className="rounded border border-emerald-500/30 bg-emerald-500/5 px-2 py-1 text-emerald-200">
          Continue without cutaways · selected
        </span>
        <Button type="button" variant="outline" size="xs" disabled={!status.sourceDir} onClick={onRevealSource}>
          Open source folder
        </Button>
        <Button type="button" variant="outline" size="xs"
          disabled={blocked || rescanning || !status.sourceDir}
          title={blocked ? "Add or rescan supporting media before accepting the cut, or use a new project" : undefined}
          onClick={rescan}>
          {rescanning ? <Loader2 className="size-3 animate-spin" /> : null}
          Rescan after adding
        </Button>
        <Button type="button" variant="ghost" size="xs" disabled title="Higgsfield generation is not connected yet">
          Generate with Higgsfield · Not connected
        </Button>
      </div>
      <p className="mt-1.5 text-[10px] text-muted-foreground">
        {blocked
          ? "This project is using a fixed asset list. Add supporting media before accepting the cut, or use a new project."
          : <>
              To add your own, place video or image files in a <span className="font-mono">broll/</span> folder inside the source folder, then rescan. This keeps the current transcript; prepare a new Short brief afterward.
            </>}
      </p>
      {error && <p role="alert" className="mt-1 text-destructive">{error}</p>}
    </div>
  );
}

export function SegmentRows({
  segments,
  projectRoot,
  runActive,
  primaryFirst = false,
  onIngested,
}: {
  segments: { name: string; path: string }[];
  projectRoot: string | null;
  runActive: boolean;
  primaryFirst?: boolean;
  onIngested?: (payload: IngestedPayload) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ingest = (inputPath: string) => {
    if (runActive) return;
    setBusy(inputPath);
    setError("");
    ingestInto(inputPath, projectRoot, onIngested)
      .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setBusy(null));
  };
  return (
    <div className="mt-1.5 border-l border-border pl-3">
      {runActive && (
        <p className="mb-1 text-[10px] text-muted-foreground">
          Stop & keep checkpoint before creating another edit from these source clips.
        </p>
      )}
      {error && <p className="text-[10px] text-destructive">{error}</p>}
      <ul className="space-y-1">
        {segments.map((segment, index) => (
          <li key={segment.path} className="flex items-center gap-2">
            <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-muted-foreground">
              {segment.name}
            </span>
            <Button
              variant={primaryFirst && index === 0 ? "default" : "ghost"}
              size="xs"
              disabled={runActive || busy !== null}
              title={runActive ? "Stop and keep the current checkpoint before changing project media" : undefined}
              onClick={() => ingest(segment.path)}
            >
              {busy === segment.path ? <Loader2 className="size-3 animate-spin" /> : null}
              Create video from this clip
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}
