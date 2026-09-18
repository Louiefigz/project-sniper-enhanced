"use client";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

export type FlowPhase = "browse" | "transcribing" | "segmenting";
export type TranscriptionStatus = "extracting_audio" | "chunking_audio" | "transcribing" | "done" | "error";

export interface FlowViewState {
  phase: FlowPhase;
  status: TranscriptionStatus;
  statusText: string;
  progress: number;
  transcriptionError: string | null;
  segmentationError: string | null;
}

interface FlowProgressProps {
  state: FlowViewState;
  videoName: string;
  onRetryTranscription: () => void;
  onRetrySegmentation: () => void;
  onBack: () => void;
}

function ErrorActions({ retryLabel, onRetry, onBack }: {
  retryLabel: string;
  onRetry: () => void;
  onBack: () => void;
}) {
  return (
    <div className="mt-4 flex flex-wrap gap-2">
      <Button onClick={onRetry} className="bg-cyan-600 text-white hover:bg-cyan-700">{retryLabel}</Button>
      <Button onClick={onBack} variant="outline">Change files or instructions</Button>
    </div>
  );
}

function TranscriptionProgress({ props }: { props: FlowProgressProps }) {
  const { state } = props;
  const dot = state.status === "done" ? "bg-green-500" : state.status === "error" ? "bg-red-500" : "bg-cyan-500 animate-pulse";
  return (
    <>
      <div className="mb-8">
        <h2 className="mb-1 text-2xl font-bold">Reading the spoken words</h2>
        <p className="text-sm text-neutral-400">This creates a timed transcript so every clip starts and ends cleanly.</p>
      </div>
      <div className="mb-4 rounded-xl border border-neutral-800 bg-neutral-900/30 p-5">
        <div className="mb-3 flex items-center gap-3">
          <div className={`h-2.5 w-2.5 shrink-0 rounded-full ${dot}`} />
          <span className="flex-1 text-sm text-neutral-200">{state.statusText}</span>
        </div>
        {state.status !== "error" && <Progress value={state.progress} className="h-1.5" />}
        {state.transcriptionError && <div className="mt-2 whitespace-pre-wrap rounded-lg border border-red-900/30 bg-red-950/20 p-3 text-sm text-red-400">{state.transcriptionError}</div>}
        {state.transcriptionError && <ErrorActions retryLabel="Retry transcription" onRetry={props.onRetryTranscription} onBack={props.onBack} />}
      </div>
      <div className="flex items-center gap-2 rounded-lg border border-neutral-800 px-3 py-2 text-xs text-neutral-500">
        <span>🎬</span><span className="truncate font-mono">{props.videoName}</span>
      </div>
    </>
  );
}

function SegmentationProgress({ props }: { props: FlowProgressProps }) {
  const failed = !!props.state.segmentationError;
  return (
    <>
      <div className="mb-8">
        <h2 className="mb-1 text-2xl font-bold">Finding your clips</h2>
        <p className="text-sm text-neutral-400">The editor is matching the transcript to your clip instructions.</p>
      </div>
      <div className="rounded-xl border border-neutral-800 bg-neutral-900/30 p-5">
        <div className="flex items-center gap-3">
          <div className={`h-2.5 w-2.5 shrink-0 rounded-full ${failed ? "bg-red-500" : "bg-cyan-500 animate-pulse"}`} />
          <span className="text-sm text-neutral-200">{failed ? "Clip finding stopped" : "Analyzing the transcript…"}</span>
        </div>
      </div>
      {props.state.segmentationError && (
        <div className="mt-3 rounded-lg border border-red-900/30 bg-red-950/20 p-3 text-sm text-red-400">
          {props.state.segmentationError}
        </div>
      )}
      {failed && <ErrorActions retryLabel="Try finding clips again" onRetry={props.onRetrySegmentation} onBack={props.onBack} />}
    </>
  );
}

export function FlowProgress(props: FlowProgressProps) {
  if (props.state.phase === "transcribing") return <TranscriptionProgress props={props} />;
  if (props.state.phase === "segmenting") return <SegmentationProgress props={props} />;
  return null;
}
