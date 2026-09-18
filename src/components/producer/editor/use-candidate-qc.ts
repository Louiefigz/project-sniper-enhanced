"use client";

import { useCallback, useEffect, useState } from "react";
import type { CandidateQcAction } from "@/lib/producer/candidate-qc-action";
import { readEventStream } from "@/lib/producer/sse";

export interface CandidateQcState {
  state: "none" | "pending" | "prepared" | "checking" | "approved" | "stale" | "rejected" | "quarantined";
  canRunQc: boolean;
  canPromote: boolean;
  canDiscard: boolean;
  detail: string;
  run: {
    active: boolean;
    action: CandidateQcAction | null;
    step: string | null;
    message: string | null;
  };
}

export type { CandidateQcAction } from "@/lib/producer/candidate-qc-action";

async function loadState(dir: string): Promise<CandidateQcState | null> {
  const response = await fetch(
    `/api/producer/palmier/candidate-qc?dir=${encodeURIComponent(dir)}`,
  );
  return response.ok ? await response.json() as CandidateQcState : null;
}

async function streamAction(
  dir: string,
  action: CandidateQcAction,
  onMessage: (message: string) => void,
): Promise<void> {
  const response = await fetch("/api/producer/palmier/candidate-qc", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dir, action }),
  });
  if (!response.ok) {
    const value = await response.json().catch(() => ({})) as { error?: string };
    throw new Error(value.error || `Candidate ${action} ${response.status}`);
  }
  let completed = false;
  await readEventStream(response, (event) => {
    if (event.event === "error") throw new Error(String(event.message));
    if (event.event === "candidate_qc_progress") onMessage(String(event.message));
    if (event.event === "candidate_qc_approved" || event.event === "candidate_promoted"
        || event.event === "candidate_discarded") {
      completed = true;
      onMessage(String(event.message));
    }
  });
  if (!completed) throw new Error("Candidate action ended without a verified result.");
}

function useCandidateRefresh(active: boolean, refresh: () => Promise<void>): void {
  useEffect(() => {
    const timer = window.setInterval(() => void refresh(), active ? 5_000 : 10_000);
    return () => window.clearInterval(timer);
  }, [active, refresh]);
}

export function useCandidateQc(dir: string, onChanged: () => void) {
  const [state, setState] = useState<CandidateQcState | null>(null);
  const [working, setWorking] = useState<CandidateQcAction | null>(null);
  const [message, setMessage] = useState("");
  const refresh = useCallback(async () => setState(await loadState(dir)), [dir]);
  useEffect(() => { void refresh(); }, [refresh]);
  useCandidateRefresh(state?.run.active === true, refresh);
  const act = useCallback(async (action: CandidateQcAction) => {
    setWorking(action);
    setMessage(action === "run_qc" ? "Starting candidate QC…"
      : action === "promote" ? "Rechecking candidate and parent…"
        : "Archiving candidate evidence and restoring its parent…");
    try {
      await streamAction(dir, action, setMessage);
      await refresh();
      onChanged();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Candidate action failed safely.");
      await refresh();
    } finally {
      setWorking(null);
    }
  }, [dir, onChanged, refresh]);
  return { state, working, message, act };
}
