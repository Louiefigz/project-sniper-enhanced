"use client";

import { useState } from "react";
import { ArchiveRestore, ExternalLink, Loader2, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  candidateActionLabel,
  candidateActionTitle,
} from "@/lib/producer/candidate-qc-action";
import { palmierActionLabel } from "@/lib/producer/project-card-state";
import { readEventStream } from "@/lib/producer/sse";
import type { ProjectStatus } from "./use-project-status";

interface PalmierResult {
  error?: string;
  message?: string;
}

export default function ProjectPalmierButton({
  status,
  title,
  onMessage,
  onChanged,
  primary = false,
}: {
  status: ProjectStatus;
  title: string;
  onMessage: (message: string) => void;
  onChanged?: () => void;
  primary?: boolean;
}) {
  const [opening, setOpening] = useState(false);
  const mode = status.intent?.mode ?? status.requestedIntent?.mode;
  const hasWorkspace = status.palmier.state !== "no_workspace";
  const durableAction = status.palmier.candidateQc?.active === true
    ? status.palmier.candidateQc.action : null;
  const candidateBusy = status.palmier.candidateQc?.active === true;
  const ready = !candidateBusy
    && (status.palmier.canOpen || Boolean(!hasWorkspace && status.manifestPath && mode));
  const label = palmierActionLabel(status.palmier, status.stages.final);
  const promoting = status.palmier.state === "approved_candidate";

  const open = async () => {
    setOpening(true);
    onMessage(promoting ? "Rechecking the approved candidate and its parent…"
      : hasWorkspace ? `Opening ${label.toLowerCase()}…` : "Creating the labeled Palmier working view…");
    try {
      if (promoting) {
        const response = await fetch("/api/producer/palmier/candidate-qc", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ dir: status.producerDir, action: "promote" }),
        });
        if (!response.ok) throw new Error(`Candidate promotion ${response.status}`);
        let promoted = false;
        await readEventStream(response, (event) => {
          if (event.event === "error") throw new Error(String(event.message));
          if (event.event === "candidate_promoted") {
            promoted = true;
            onMessage(String(event.message));
          }
        });
        if (!promoted) throw new Error("Candidate promotion ended without a verified result.");
        onChanged?.();
        return;
      }
      const viewed = await post("/api/producer/palmier/view", {
        dir: status.producerDir,
      });
      const result = !hasWorkspace && viewed.response.status === 409
        ? await post("/api/producer/palmier/workspace", {
            dir: status.producerDir,
            mode,
            name: title,
          })
        : viewed;
      if (!result.response.ok) {
        throw new Error(result.body.error || `Palmier ${result.response.status}`);
      }
      onMessage(result.body.message || "Palmier is showing this project.");
    } catch (reason) {
      onMessage(reason instanceof Error ? reason.message : "Could not open Palmier");
    } finally {
      setOpening(false);
    }
  };

  return (
    <Button
      variant={primary ? "default" : "ghost"}
      size="xs"
      disabled={!ready || opening}
      onClick={() => void open()}
      title={candidateBusy ? candidateActionTitle(durableAction)
        : ready ? status.palmier.detail : hasWorkspace
        ? "This Palmier workspace record cannot be opened safely."
        : "Prepare media and choose Short or Long before creating a Palmier view"}
    >
      {opening || candidateBusy
        ? <Loader2 className="size-3 animate-spin" /> : <ExternalLink className="size-3" />}
      {candidateBusy ? candidateActionLabel(durableAction)
        : opening ? (promoting ? "Promoting candidate…" : "Opening Palmier…") : label}
    </Button>
  );
}

async function post(url: string, body: Record<string, unknown>) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const result = await response.json().catch(() => ({})) as PalmierResult;
  return { response, body: result };
}

export function ProjectCandidateQcButton({
  status,
  onMessage,
  onChanged,
}: {
  status: ProjectStatus;
  onMessage: (message: string) => void;
  onChanged: () => void;
}) {
  const [running, setRunning] = useState<"run_qc" | "discard" | null>(null);
  const showQc = status.palmier.state === "pending_candidate"
    && status.palmier.candidateQc?.canRunQc === true;
  const showDiscard = status.palmier.candidateQc?.canDiscard === true;
  const active = status.palmier.candidateQc?.active === true;
  if (active || (!showQc && !showDiscard)) return null;
  const run = async (action: "run_qc" | "discard") => {
    setRunning(action);
    try {
      await runProjectCandidateAction(status.producerDir, action, onMessage);
      onChanged();
    } catch (reason) {
      onMessage(reason instanceof Error ? reason.message : "Candidate action failed safely.");
    } finally {
      setRunning(null);
    }
  };
  return (
    <>
      {showQc && <Button variant="default" size="xs" disabled={running !== null || active}
        onClick={() => void run("run_qc")}>
        {running === "run_qc" || active ? <Loader2 className="size-3 animate-spin" /> : <ShieldCheck className="size-3" />}
        {running === "run_qc" ? candidateActionLabel("run_qc") : "Run candidate QC"}
      </Button>}
      {showDiscard && <Button variant="ghost" size="xs" disabled={running !== null || active}
        onClick={() => void run("discard")}>
        {running === "discard" ? <Loader2 className="size-3 animate-spin" /> : <ArchiveRestore className="size-3" />}
        {running === "discard" ? candidateActionLabel("discard") : "Discard candidate & keep parent"}
      </Button>}
    </>
  );
}

async function runProjectCandidateAction(
  dir: string,
  action: "run_qc" | "discard",
  onMessage: (message: string) => void,
): Promise<void> {
  onMessage(action === "run_qc" ? "Preparing the exact candidate export for QC…"
    : "Archiving candidate evidence and restoring its exact parent…");
  const response = await fetch("/api/producer/palmier/candidate-qc", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dir, action }),
  });
  if (!response.ok) throw new Error(`Candidate ${action} ${response.status}`);
  const expected = action === "run_qc" ? "candidate_qc_approved" : "candidate_discarded";
  let completed = false;
  await readEventStream(response, (event) => {
    if (event.event === "error") throw new Error(String(event.message));
    if (event.event === "candidate_qc_progress") onMessage(String(event.message));
    if (event.event === expected) {
      completed = true;
      onMessage(String(event.message));
    }
  });
  if (!completed) throw new Error(`Candidate ${action} ended without a verified result.`);
}
