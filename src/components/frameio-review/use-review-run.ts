"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { ReviewConfig, ReviewEvent } from "@/lib/frameio/types";
import { derror, dlog } from "@/lib/debug";
import { clockStamp, logsForReviewEvent, ReviewLogKind, ReviewLogLine } from "./review-logs";
import { createInitialReviewState, reviewRunReducer } from "./review-run-state";

interface UseReviewRunOptions {
  filePath: string;
  fileName: string | null;
  config: ReviewConfig;
}

interface ReviewRequestOptions {
  filePath: string;
  config: ReviewConfig;
  confirmed: boolean;
  signal: AbortSignal;
}

function requestBody(options: ReviewRequestOptions) {
  const { filePath, config, confirmed } = options;
  return {
    filePath,
    fps: config.fps,
    mode: config.mode,
    fuzz: config.fuzz,
    maxReps: config.maxReps,
    maxFrames: config.maxFrames,
    hamming: config.hamming,
    model: config.model,
    confirmThreshold: config.confirmThreshold,
    yes: confirmed,
    paidApiConsent: config.paidApiConsent,
  };
}

function parseReviewEvent(chunk: string): ReviewEvent | null {
  const line = chunk.split("\n").find((item) => item.startsWith("data: "));
  const payload = line?.slice(6).trim();
  if (!payload) return null;
  try {
    return JSON.parse(payload) as ReviewEvent;
  } catch {
    return null;
  }
}

function emitReviewEvents(chunks: string[], onEvent: (event: ReviewEvent) => void) {
  chunks.forEach((chunk) => {
    const event = parseReviewEvent(chunk);
    if (event) onEvent(event);
  });
}

async function readReviewStream(response: Response, onEvent: (event: ReviewEvent) => void) {
  if (!response.body) throw new Error("Review response had no event stream");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    emitReviewEvents(chunks, onEvent);
  }
  if (buffer.trim()) emitReviewEvents([buffer], onEvent);
}

async function requestReview(
  options: ReviewRequestOptions,
  onEvent: (event: ReviewEvent) => void,
) {
  const response = await fetch("/api/frameio-review/review", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(requestBody(options)),
    signal: options.signal,
  });
  if (!response.ok) {
    const detail = (await response.clone().json().catch(() => null)) as { error?: string } | null;
    throw new Error(detail?.error || `Review request failed (${response.status})`);
  }
  let terminalSeen = false;
  await readReviewStream(response, (event) => {
    if (event.event === "done" || event.event === "error" || event.event === "needs_confirm") terminalSeen = true;
    onEvent(event);
  });
  if (!terminalSeen) throw new Error("The text review ended before producing a result. Retry the review.");
}

export function useReviewRun({ filePath, fileName, config }: UseReviewRunOptions) {
  const [state, dispatch] = useReducer(reviewRunReducer, undefined, createInitialReviewState);
  const [logs, setLogs] = useState<ReviewLogLine[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const pushLog = useCallback((kind: ReviewLogKind, text: string) => {
    setLogs((previous) => [...previous, { t: clockStamp(), kind, text }]);
  }, []);

  const handleEvent = useCallback((event: ReviewEvent) => {
    const nextLogs = logsForReviewEvent(event).map((line) => ({ ...line, t: clockStamp() }));
    if (nextLogs.length) setLogs((previous) => [...previous, ...nextLogs]);
    if (event.event !== "log") dlog("frameio:review", `event:${event.event}`);
    dispatch({ type: "event", event });
  }, []);

  const run = useCallback(async (confirmed: boolean) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    dispatch({ type: "reset", confirmed });
    try {
      await requestReview({ filePath, config, confirmed, signal: controller.signal }, handleEvent);
    } catch (error) {
      if ((error as Error).name === "AbortError") return;
      derror("frameio:review", "stream failed", error);
      const message = error instanceof Error ? error.message : "Review failed";
      dispatch({ type: "stream_error", message });
      pushLog("error", `✗ stream failed: ${message}`);
    }
  }, [config, filePath, handleEvent, pushLog]);

  useEffect(() => {
    dlog("frameio:review", "start run", { fileName, config });
    run(false);
    return () => abortRef.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { ...state, logs, run };
}
