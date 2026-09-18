"use client";

import { useState } from "react";
import { dlog, summarize } from "@/lib/debug";
import { responseError } from "@/lib/segmenter/file-browser-helpers";
import type { MulticamPanelState, SegmentResult } from "./multicam-status-panel";

interface ExportSegment {
  title: string;
  start: number;
  end: number;
}

interface MulticamExportInput {
  filePath: string;
  bcamPath: string;
  ccamPath: string;
  lav1Path: string;
  lav2Path: string;
  segments: ExportSegment[];
}

interface MulticamEvent {
  status?: string;
  error?: string;
  stderr?: string;
  [key: string]: unknown;
}

const INITIAL_STATE: MulticamPanelState = {
  loading: false,
  status: "",
  error: null,
  validation: null,
  offsetB: null,
  offsetC: null,
  offsetLav1: null,
  offsetLav2: null,
  segResults: [],
};

function sourceLabel(value: unknown): string {
  if (value === "b") return "extra camera 1";
  if (value === "c") return "extra camera 2";
  if (value === "lav1") return "microphone audio 1";
  if (value === "lav2") return "microphone audio 2";
  return "source";
}

function statusFor(event: MulticamEvent, total: number): string | undefined {
  if (event.status === "probed_sources") return "Files checked. Finding their sync points…";
  if (event.status === "estimating_offset_coarse") return `Synchronizing ${sourceLabel(event.cam)}…`;
  if (event.status === "estimating_offset_fine") return `Refining sync for ${sourceLabel(event.cam)}…`;
  if (event.status === "offsets_rounded") return "Files synchronized. Creating clips…";
  if (event.status === "segment_cut") return `Created clip ${Number(event.index) + 1} of ${total}`;
  if (event.status === "validation_passed") return "Sync checked. Preparing files…";
  if (event.status === "validation_failed") return "Sync check found a problem.";
  if (event.status === "validation_skipped") return "Preparing files…";
  if (event.status === "zipping") return "Compressing files for download…";
  if (event.status === "zipped") return "Download is almost ready…";
  if (event.status === "done") return "Files created.";
  if (event.status === "ready") return "Download started.";
  return undefined;
}

function validationFor(event: MulticamEvent): string | undefined {
  if (event.status === "validation_passed") return "Camera and audio sync passed.";
  if (event.status === "validation_failed") return `Sync check failed: ${JSON.stringify(event.validation)}`;
  if (event.status === "validation_skipped") return "Automatic sync check was skipped.";
  return undefined;
}

function segmentResultFor(event: MulticamEvent): SegmentResult | undefined {
  if (event.status === "segment_cut") {
    return { index: Number(event.index), available: Array.isArray(event.available) ? event.available as string[] : [] };
  }
  if (event.status !== "segment_skipped" && event.status !== "segment_failed") return undefined;
  const detail = event.reason ?? event.error ?? "skipped";
  return { index: Number(event.index), available: [], error: String(detail) };
}

function eventPatch(event: MulticamEvent, state: MulticamPanelState, total: number): Partial<MulticamPanelState> {
  const result = segmentResultFor(event);
  return {
    status: statusFor(event, total) ?? state.status,
    validation: validationFor(event) ?? state.validation,
    offsetB: typeof event.b_offset === "number" ? event.b_offset : state.offsetB,
    offsetC: typeof event.c_offset === "number" ? event.c_offset : state.offsetC,
    offsetLav1: typeof event.lav1_offset === "number" ? event.lav1_offset : state.offsetLav1,
    offsetLav2: typeof event.lav2_offset === "number" ? event.lav2_offset : state.offsetLav2,
    segResults: result ? [...state.segResults, result] : state.segResults,
  };
}

async function consumeEvents(response: Response, onEvent: (event: MulticamEvent) => void): Promise<void> {
  if (!response.body) throw new Error("The server returned no export progress stream.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const raw = line.slice(6).trim();
      if (!raw) continue;
      let event: MulticamEvent;
      try { event = JSON.parse(raw) as MulticamEvent; } catch { continue; }
      onEvent(event);
    }
  }
}

function requestPayload(input: MulticamExportInput) {
  return {
    acamPath: input.filePath,
    bcamPath: input.bcamPath || undefined,
    ccamPath: input.ccamPath || undefined,
    lav1Path: input.lav1Path || undefined,
    lav2Path: input.lav2Path || undefined,
    segments: input.segments,
  };
}

export function useMulticamExport(input: MulticamExportInput) {
  const [state, setState] = useState<MulticamPanelState>(INITIAL_STATE);
  const exportMulticam = async () => {
    setState({ ...INITIAL_STATE, loading: true, status: "Starting synced export…" });
    const payload = requestPayload(input);
    let downloadTriggered = false;
    try {
      dlog("segmenter:multicam", "export request → /api/segmenter/multicam-export", summarize(payload));
      const response = await fetch("/api/segmenter/multicam-export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw await responseError(response, "Synced camera and audio export");
      await consumeEvents(response, (event) => {
        dlog("segmenter:multicam", `SSE ${event.status ?? (event.error ? "error" : "progress")}`, summarize(event));
        if (event.stderr) return;
        if (event.error) throw new Error(event.error);
        setState((current) => ({ ...current, ...eventPatch(event, current, input.segments.length) }));
        if (event.status !== "ready" || !event.downloadId || downloadTriggered) return;
        downloadTriggered = true;
        window.location.href = `/api/segmenter/multicam-download/${event.downloadId}`;
      });
    } catch (cause) {
      const error = cause instanceof Error ? cause.message : "Synced export failed.";
      setState((current) => ({ ...current, status: "Export stopped.", error }));
    } finally {
      setState((current) => ({ ...current, loading: false }));
    }
  };
  return { state, exportMulticam };
}
