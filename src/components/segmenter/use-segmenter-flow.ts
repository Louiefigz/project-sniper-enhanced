"use client";

import { useCallback, useState, type Dispatch, type SetStateAction } from "react";
import { dlog, summarize } from "@/lib/debug";
import type { SegmentGroup, TranscriptEntry } from "@/lib/types";
import {
  formatTime,
  responseError,
  segmentsFromPayload,
  type FileSlots,
} from "@/lib/segmenter/file-browser-helpers";
import {
  consumeTranscriptionStream,
  type TranscriptionMessage,
} from "@/lib/segmenter/transcription-stream";
import type { FlowViewState } from "./flow-progress";

export interface SegmenterFlowResult {
  transcript: TranscriptEntry[];
  segments: SegmentGroup[];
  paths: {
    video: string;
    bcam: string;
    ccam: string;
    lav1: string;
    lav2: string;
  };
}

export type CompleteHandler = (result: SegmenterFlowResult) => void;

interface FlowOptions {
  files: FileSlots;
  prompt: string;
  onComplete: CompleteHandler;
}

type SetView = Dispatch<SetStateAction<FlowViewState>>;

const INITIAL_VIEW: FlowViewState = {
  phase: "browse",
  status: "extracting_audio",
  statusText: "",
  progress: 0,
  transcriptionError: null,
  segmentationError: null,
};

function messageProgress(message: TranscriptionMessage): Partial<FlowViewState> {
  if (message.status === "extracting_audio") return { status: "extracting_audio", statusText: "Extracting audio...", progress: 20 };
  if (message.status === "audio_extracted") return { statusText: `Audio extracted (${message.size_mb} MB)`, progress: 35 };
  if (message.status === "chunking_audio") return { status: "chunking_audio", statusText: "Splitting into chunks...", progress: 40 };
  if (message.status === "chunking_complete") return { statusText: `Split into ${message.chunks} chunks`, progress: 45 };
  if (message.status !== "transcribing_chunk") return {};
  const total = message.total ?? 1;
  const chunk = message.chunk ?? 1;
  const progress = total > 1 ? Math.round(45 + (chunk / total) * 45) : 60;
  const statusText = total > 1 ? `Transcribing chunk ${chunk} / ${total}...` : "Transcribing audio...";
  return { status: "transcribing", statusText, progress };
}

async function readSegments(response: Response, transcriptLength: number): Promise<SegmentGroup[]> {
  if (!response.ok) throw await responseError(response, "Segmentation");
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new Error("Segmentation returned an invalid JSON response.");
  }
  return segmentsFromPayload(data, transcriptLength);
}

function pathFor(files: FileSlots, key: keyof FileSlots): string {
  return files[key]?.path ?? "";
}

function useSegmentationRunner(options: FlowOptions, setView: SetView) {
  const [lastTranscript, setLastTranscript] = useState<TranscriptEntry[] | null>(null);
  const run = useCallback(async (transcript: TranscriptEntry[]) => {
    setLastTranscript(transcript);
    setView((state) => ({ ...state, phase: "segmenting", segmentationError: null }));
    try {
      dlog("segmenter:segment", "request → /api/segmenter/segment", {
        transcriptLines: transcript.length,
        prompt: summarize(options.prompt),
      });
      const response = await fetch("/api/segmenter/segment", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transcript, prompt: options.prompt }),
      });
      const segments = await readSegments(response, transcript.length);
      dlog("segmenter:segment", "validated response", summarize(segments));
      options.onComplete({
        transcript,
        segments,
        paths: {
          video: pathFor(options.files, "a"),
          bcam: pathFor(options.files, "b"),
          ccam: pathFor(options.files, "c"),
          lav1: pathFor(options.files, "lav1"),
          lav2: pathFor(options.files, "lav2"),
        },
      });
      setView(INITIAL_VIEW);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "Segmentation failed";
      setView((state) => ({ ...state, phase: "segmenting", segmentationError: message }));
    }
  }, [options, setView]);
  return { run, retry: () => lastTranscript && void run(lastTranscript) };
}

function useTranscriptionRunner(filePath: string, runSegmentation: (value: TranscriptEntry[]) => Promise<void>, setView: SetView) {
  return useCallback(async () => {
    if (!filePath) return;
    setView({ ...INITIAL_VIEW, phase: "transcribing", statusText: "Extracting audio from source...", progress: 10 });
    try {
      const response = await fetch("/api/segmenter/transcribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filePath }),
      });
      if (!response.ok) throw await responseError(response, "Transcription");
      const result = await consumeTranscriptionStream(response, {
        onMessage: (message) => {
          dlog("segmenter:transcribe", `SSE ${message.status ?? "event"}`, summarize(message));
          setView((state) => ({ ...state, ...messageProgress(message) }));
        },
      });
      const duration = result.duration && result.duration > 0
        ? result.duration : result.transcript[result.transcript.length - 1].end;
      setView((state) => ({ ...state, status: "done", progress: 100, statusText: `Done — ${result.transcript.length} utterances, ${formatTime(duration)}` }));
      await runSegmentation(result.transcript);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "Transcription failed";
      setView((state) => ({ ...state, phase: "transcribing", status: "error", transcriptionError: message }));
    }
  }, [filePath, runSegmentation, setView]);
}

export function useSegmenterFlow(options: FlowOptions) {
  const [state, setState] = useState<FlowViewState>(INITIAL_VIEW);
  const segmentation = useSegmentationRunner(options, setState);
  const startTranscription = useTranscriptionRunner(pathFor(options.files, "a"), segmentation.run, setState);
  const backToBrowse = useCallback(() => {
    setState((current) => ({ ...current, phase: "browse", transcriptionError: null, segmentationError: null }));
  }, []);
  return {
    state,
    startTranscription,
    retrySegmentation: segmentation.retry,
    backToBrowse,
  };
}
