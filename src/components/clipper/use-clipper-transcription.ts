"use client";

import { useState } from "react";
import type { TranscriptEntry, VideoMetadata } from "@/lib/clipper/types";
import {
  consumeTranscriptionResponse,
  type TranscriptionEvent,
} from "@/lib/clipper/transcription-stream";
import { derror, dlog, dlogLocal, summarize } from "@/lib/debug";

export type TxStatus = "extracting_audio" | "chunking_audio" | "transcribing" | "done" | "error";
export type ChannelState = "idle" | "extracting" | "transcribing" | "done";

export interface PendingComplete {
  transcript: TranscriptEntry[];
  media: VideoMetadata;
  stereo: boolean;
  lavMode: boolean;
}

interface TranscriptionRequest {
  filePath: string;
  cameraName: string;
  guestCameraName?: string;
  hostLavPath?: string;
  guestLavPath?: string;
  hostLavName?: string;
  guestLavName?: string;
}

interface TxState {
  txStatus: TxStatus;
  txStatusText: string;
  txProgress: number;
  txError: string | null;
  isStereo: boolean;
  isLavMode: boolean;
  leftChState: ChannelState;
  rightChState: ChannelState;
  pendingComplete: PendingComplete | null;
}

const INITIAL: TxState = {
  txStatus: "extracting_audio", txStatusText: "", txProgress: 0,
  txError: null, isStereo: false, isLavMode: false,
  leftChState: "idle", rightChState: "idle", pendingComplete: null,
};

function formatTime(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

function chunkProgress(event: TranscriptionEvent, stereo: boolean, lavMode: boolean): Partial<TxState> {
  const chunk = Number(event.chunk);
  const total = Number(event.total);
  const txProgress = total > 1 ? Math.round(45 + (chunk / total) * 45) : 60;
  if (!(stereo || lavMode) || total !== 2) {
    const text = total > 1 ? `Transcribing chunk ${chunk} / ${total}...` : "Transcribing audio...";
    return { txStatus: "transcribing", txProgress, txStatusText: text };
  }
  const first = chunk === 1;
  const txStatusText = first
    ? (lavMode ? "Transcribing host mic..." : "Transcribing host channel (left)...")
    : (lavMode ? "Transcribing guest mic..." : "Transcribing caller channel (right)...");
  return {
    txStatus: "transcribing", txProgress, txStatusText,
    leftChState: first ? "transcribing" : "done",
    rightChState: first ? "idle" : "transcribing",
  };
}

function progressPatch(event: TranscriptionEvent, stereo: boolean, lavMode: boolean): Partial<TxState> {
  if (event.status === "extracting_channels") return {
    isStereo: true, leftChState: "extracting", rightChState: "extracting",
    txStatusText: "Stereo detected — splitting channels...", txProgress: 20,
  };
  if (event.status === "audio_extracted" && stereo) {
    return { leftChState: "idle", rightChState: "idle", txProgress: 35 };
  }
  if (event.status === "extracting_audio") {
    return { txStatus: "extracting_audio", txStatusText: "Extracting audio...", txProgress: 20 };
  }
  if (event.status === "audio_extracted") {
    return { txStatusText: `Audio ready (${String(event.size_mb)} MB)`, txProgress: 35 };
  }
  if (event.status === "chunking_audio") {
    return { txStatus: "chunking_audio", txStatusText: "Splitting into chunks...", txProgress: 40 };
  }
  if (event.status === "chunking_complete") {
    return { txStatusText: `Split into ${String(event.chunks)} chunks`, txProgress: 45 };
  }
  return event.status === "transcribing_chunk" ? chunkProgress(event, stereo, lavMode) : {};
}

function requestBody(request: TranscriptionRequest, lavMode: boolean): string {
  return JSON.stringify({
    filePath: request.filePath,
    ...(lavMode ? { hostLavPath: request.hostLavPath, guestLavPath: request.guestLavPath } : {}),
  });
}

export function useClipperTranscription() {
  const [state, setState] = useState<TxState>(INITIAL);

  const start = async (request: TranscriptionRequest): Promise<void> => {
    const lavMode = !!(request.hostLavPath && request.guestLavPath);
    dlog("clipper:transcribe", "start", {
      mode: lavMode ? "lavs (host+guest mics)" : "camera (Host cam audio)",
      hostCam: request.cameraName, guestCam: request.guestCameraName || null,
      hostMic: request.hostLavName || null, guestMic: request.guestLavName || null,
    });
    setState({ ...INITIAL, isLavMode: lavMode, txProgress: 10,
      txStatusText: lavMode ? "Preparing host + guest mics..." : "Extracting audio from video..." });
    let stereo = false;
    try {
      const response = await fetch("/api/clipper/transcribe", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: requestBody(request, lavMode),
      });
      const done = await consumeTranscriptionResponse(response, (event) => {
        if (event.stderr) { dlogLocal("clipper:transcribe", "py stderr", event.stderr); return; }
        dlog("clipper:transcribe", `SSE ${event.status ?? "msg"}`, event.status === "done"
          ? { language: event.language, sample: summarize(event.transcript) } : event);
        if (event.status === "extracting_channels") stereo = true;
        setState((current) => ({ ...current, ...progressPatch(event, stereo, lavMode) }));
      });
      const complete: PendingComplete = { transcript: done.transcript, media: done.media, stereo, lavMode };
      setState((current) => ({ ...current, txStatus: "done", txProgress: 100,
        txStatusText: `Done — ${done.transcript.length} utterances, ${formatTime(done.media.duration)}`,
        leftChState: stereo || lavMode ? "done" : current.leftChState,
        rightChState: stereo || lavMode ? "done" : current.rightChState,
        pendingComplete: complete }));
    } catch (error) {
      const message = error instanceof Error ? error.message : "Transcription failed";
      setState((current) => ({ ...current, txStatus: "error", txError: message, pendingComplete: null }));
      derror("clipper:transcribe", "stream/fetch failed", error);
    }
  };

  return { ...state, start };
}
