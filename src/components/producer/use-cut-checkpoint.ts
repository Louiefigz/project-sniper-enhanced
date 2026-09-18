"use client";

import { useEffect, useRef, useState } from "react";
import { submitCutAcceptance, CUT_ACCEPTANCE_RESPONSE_TIMEOUT_MS, type CutAcceptanceResult } from "@/lib/producer/cut-acceptance-client";
import type { HumanCutSubmissionV1, HumanCutRetryV1 } from "@/lib/producer/contracts/human-cut-acceptance";

/** Keyed reads hide stale project/receipt state immediately and never mutate a checkpoint. */
export function useCutCheckpoint<T>(dir: string, read: (dir: string, signal: AbortSignal) => Promise<T>) {
  const [result, setResult] = useState<{ dir: string; revision: number; data: T | null; error: string | null; elapsedMs: number } | null>(null);
  const [revision, refresh] = useState(0);
  useEffect(() => {
    let active = true;
    const started = performance.now();
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(new Error("Checkpoint verification exceeded 45 seconds; recheck project status")), 45_000);
    read(dir, controller.signal).then((data) => {
      if (active) setResult({ dir, revision, data, error: null, elapsedMs: performance.now() - started });
    }).catch((reason: unknown) => {
      if (active) setResult({ dir, revision, data: null, elapsedMs: performance.now() - started,
        error: reason instanceof Error ? reason.message : "Checkpoint is unavailable" });
    }).finally(() => window.clearTimeout(timeout));
    return () => { active = false; window.clearTimeout(timeout); controller.abort(); };
  }, [dir, revision, read]);
  const current = result?.dir === dir && result.revision === revision ? result : null;
  return { data: current?.data ?? null, error: current?.error ?? null,
    refresh: () => refresh((previous) => previous + 1), revision, elapsedMs: current?.elapsedMs ?? null };
}

/** One user-triggered decision. An aborted/lost response never means the server canceled its work. */
export function useCutDecision(dir: string, onSettled?: () => void, onSubmitted?: () => void) {
  const current = useRef<AbortController | null>(null);
  const [state, setState] = useState<{ running: boolean; error: string | null; result: CutAcceptanceResult | null }>(
    { running: false, error: null, result: null });
  useEffect(() => () => { current.current?.abort(); current.current = null; }, []);
  const run = async (decision: (signal: AbortSignal) => HumanCutSubmissionV1 | HumanCutRetryV1
    | Promise<HumanCutSubmissionV1 | HumanCutRetryV1>) => {
    if (current.current) return;
    const controller = new AbortController(); current.current = controller;
    setState({ running: true, error: null, result: null });
    const timeout = window.setTimeout(() => controller.abort(new Error("Decision response exceeded five minutes. Its result is unknown; recheck status before retrying.")), CUT_ACCEPTANCE_RESPONSE_TIMEOUT_MS);
    try {
      const submission = await decision(controller.signal);
      controller.signal.throwIfAborted();
      onSubmitted?.();
      const result = await submitCutAcceptance({ dir, submission, signal: controller.signal });
      if (current.current === controller) setState({ running: false, error: null, result });
    } catch (error) {
      if (current.current === controller) setState({ running: false, result: null,
        error: error instanceof Error ? error.message : "Decision result is unknown; recheck project status" });
    } finally {
      window.clearTimeout(timeout);
      if (current.current === controller) current.current = null;
      onSettled?.();
    }
  };
  return { ...state, run };
}
