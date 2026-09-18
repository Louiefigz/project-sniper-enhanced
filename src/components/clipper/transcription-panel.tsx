"use client";

import { Progress } from "@/components/ui/progress";
import { downloadText } from "@/lib/clipper/download";
import type { TranscriptEntry, WordTiming } from "@/lib/clipper/types";
import type { ChannelState, PendingComplete, TxStatus } from "./use-clipper-transcription";

interface SelectedFile {
  key: string;
  name: string;
  audio: boolean;
}

interface Props {
  txStatus: TxStatus;
  txStatusText: string;
  txProgress: number;
  txError: string | null;
  isStereo: boolean;
  isLavMode: boolean;
  leftChState: ChannelState;
  rightChState: ChannelState;
  pendingComplete: PendingComplete | null;
  selectedFiles: SelectedFile[];
  onBack: () => void;
  onContinue: () => void;
}

function utteranceSpeaker(words: WordTiming[] | undefined): number | null {
  const counts = new Map<number, number>();
  for (const word of words ?? []) {
    if (word.speaker != null) counts.set(word.speaker, (counts.get(word.speaker) ?? 0) + 1);
  }
  if (!counts.size) return null;
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0];
}

function speakerLabel(speaker: number | null, secondLabel: string): string {
  if (speaker === 0) return "Host";
  if (speaker === 1) return secondLabel;
  return speaker != null ? `Speaker ${speaker}` : "Speaker";
}

function downloadTranscript(transcript: TranscriptEntry[], secondLabel: string): void {
  const lines = transcript.map((entry, index) => {
    const label = speakerLabel(utteranceSpeaker(entry.words), secondLabel);
    return `[${index}] ${label}: ${entry.text.trim()}`;
  });
  downloadText(`## Transcript\n${lines.join("\n")}`, "transcript.txt");
}

function ChannelCard({ label, role, state }: { label: string; role: string; state: ChannelState }) {
  const dot = state === "done" ? "bg-green-500" : state === "transcribing"
    ? "bg-blue-500 animate-pulse" : state === "extracting" ? "bg-yellow-500 animate-pulse" : "bg-neutral-700";
  const status = state === "done" ? "Done" : state === "transcribing"
    ? "Transcribing..." : state === "extracting" ? "Extracting..." : "Waiting";
  return <div className="flex-1 rounded-xl border border-neutral-800 bg-neutral-900/50 p-5">
    <div className="flex items-center justify-between mb-3">
      <span className="text-xs text-neutral-500 uppercase tracking-wider font-medium">{label}</span>
      {state === "done" && <span className="text-xs text-green-400 font-medium">✓ Done</span>}
    </div>
    <p className="text-base font-semibold text-white mb-4">{role}</p>
    <div className="flex items-center gap-2"><div className={`w-2.5 h-2.5 rounded-full shrink-0 ${dot}`} />
      <span className="text-sm text-neutral-400">{status}</span></div>
  </div>;
}

function TranscriptPreview({ pending, secondLabel }: { pending: PendingComplete; secondLabel: string }) {
  return <div className="rounded-xl border border-neutral-800 bg-neutral-950 overflow-hidden mb-4">
    <div className="flex items-center justify-between px-3 py-2 border-b border-neutral-800 bg-neutral-900">
      <span className="text-xs font-medium text-neutral-400">Transcript</span>
      <span className="text-xs text-neutral-600">{pending.transcript.length} utterances</span>
    </div>
    <div className="p-3 space-y-2 overflow-y-auto" style={{ maxHeight: "360px" }}>
      {pending.transcript.map((entry, index) => {
        const label = speakerLabel(utteranceSpeaker(entry.words), secondLabel);
        const isRight = label !== "Host";
        return <div key={index} className={`flex flex-col gap-0.5 ${isRight ? "items-end" : "items-start"}`}>
          <span className="text-[9px] text-neutral-600 px-1">{label}</span>
          <div className={`max-w-[85%] rounded-2xl px-3 py-2 text-xs leading-relaxed ${isRight
            ? "bg-amber-600 text-white rounded-br-sm" : "bg-neutral-700 text-neutral-100 rounded-bl-sm"}`}>{entry.text}</div>
        </div>;
      })}
    </div>
  </div>;
}

export function TranscriptionPanel(props: Props) {
  const twoTrack = props.isStereo || props.isLavMode;
  const secondLabel = props.isLavMode ? "Guest" : "Caller";
  const complete = props.txStatus === "done" && props.pendingComplete;
  return <>
    {(props.txStatus === "done" || props.txStatus === "error") && <button onClick={props.onBack}
      className="mb-4 text-xs text-neutral-400 hover:text-neutral-200 transition-colors">← Back to selected files (your picks stay selected)</button>}
    <div className="mb-8"><h2 className="text-2xl font-bold mb-1">{props.txStatus === "error"
      ? "Transcription failed" : props.txStatus === "done" ? "Transcript ready" : "Transcribing"}</h2>
      <p className="text-neutral-400 text-sm">{props.isLavMode
        ? "Two lav mics — each is transcribed separately for an exact Host/Guest split."
        : props.isStereo ? "Stereo file — each channel is transcribed separately for precise speaker identification."
        : "Word-level timestamps · speaker diarization when supported"}</p></div>
    {twoTrack ? <><div className="flex gap-4 mb-4">
      <ChannelCard label={props.isLavMode ? "Host mic" : "Left Channel"} role="Host" state={props.leftChState} />
      <ChannelCard label={props.isLavMode ? "Guest mic" : "Right Channel"} role={secondLabel} state={props.rightChState} />
    </div><Progress value={props.txProgress} className="h-1.5 mb-4" /></> :
      <div className="rounded-xl border border-neutral-800 bg-neutral-900/30 p-5 mb-4">
        <div className="flex items-center gap-3 mb-3"><div className={`w-2.5 h-2.5 rounded-full shrink-0 ${props.txStatus === "done"
          ? "bg-green-500" : props.txStatus === "error" ? "bg-red-500" : "bg-amber-500 animate-pulse"}`} />
          <span className="text-sm text-neutral-200 flex-1">{props.txStatusText}</span></div>
        {props.txStatus !== "error" && <Progress value={props.txProgress} className="h-1.5" />}
      </div>}
    {props.txStatus === "error" && <div role="alert"
      className="text-red-300 text-sm mb-4 p-3 bg-red-950/30 border border-red-800/50 rounded-lg">
      <p className="font-semibold">Transcription failed</p>
      <p className="mt-1">{props.txError || "The transcription service stopped before returning a transcript."}</p>
      <p className="mt-2 text-xs text-red-300/75">Go back to your selected files, check that they are compatible, then try again.</p>
    </div>}
    {complete && <TranscriptPreview pending={complete} secondLabel={secondLabel} />}
    {complete && <div className="flex gap-3 mt-4 mb-4">
      <button onClick={() => downloadTranscript(complete.transcript, secondLabel)} className="flex-1 text-xs px-4 py-2 rounded-lg border border-neutral-700 bg-neutral-800 hover:bg-neutral-700 text-neutral-300 transition-colors">Download transcript (.txt)</button>
      <button onClick={props.onContinue} className="flex-1 text-xs px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-medium transition-colors">Choose edit instructions →</button>
    </div>}
    <div className={`grid gap-3 text-xs text-neutral-500 ${props.selectedFiles.length > 1 ? "grid-cols-2" : "grid-cols-1"}`}>
      {props.selectedFiles.map((file) => <div key={file.key} className="rounded-lg border border-neutral-800 px-3 py-2 flex items-center gap-2">
        <span>{file.audio ? "🎙️" : "🎬"}</span><span className="truncate font-mono">{file.name}</span>
      </div>)}
    </div>
  </>;
}
