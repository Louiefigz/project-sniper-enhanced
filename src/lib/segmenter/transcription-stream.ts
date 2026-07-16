import type { TranscriptEntry } from "@/lib/types";
import { validateTranscript } from "./file-browser-helpers";

export interface TranscriptionMessage {
  status?: string;
  error?: string;
  stderr?: string;
  transcript?: unknown;
  duration?: number;
  size_mb?: number;
  chunks?: number;
  chunk?: number;
  total?: number;
}

interface StreamAccumulator {
  done: boolean;
  transcript?: unknown;
  duration?: number;
  stderr: string[];
}

interface ConsumeOptions {
  onMessage: (message: TranscriptionMessage) => void;
}

export interface TranscriptionResult {
  transcript: TranscriptEntry[];
  duration?: number;
}

export function parseSseDataLine(line: string): TranscriptionMessage | null {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith(":")) return null;
  if (!trimmed.startsWith("data:")) return null;
  const raw = trimmed.slice(5).trim();
  if (!raw) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("Transcription returned a malformed stream event.");
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Transcription returned an invalid stream event.");
  }
  return parsed as TranscriptionMessage;
}

function acceptMessage(
  state: StreamAccumulator,
  message: TranscriptionMessage | null,
  onMessage: ConsumeOptions["onMessage"],
): void {
  if (!message) return;
  if (typeof message.error === "string" && message.error.trim()) throw new Error(message.error);
  if (typeof message.stderr === "string") state.stderr.push(message.stderr);
  if (message.status === "done") {
    state.done = true;
    state.transcript = message.transcript;
    state.duration = message.duration;
  }
  onMessage(message);
}

function incompleteStreamError(stderr: string[]): Error {
  const tail = stderr.join("\n").slice(-1000).trim();
  const detail = tail ? ` Last process output:\n${tail}` : " No process output was provided.";
  return new Error(`Transcription stream ended before its terminal done event.${detail}`);
}

export async function consumeTranscriptionStream(
  response: Response,
  options: ConsumeOptions,
): Promise<TranscriptionResult> {
  if (!response.body) throw new Error("Transcription returned no response stream.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const state: StreamAccumulator = { done: false, stderr: [] };
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      acceptMessage(state, parseSseDataLine(line), options.onMessage);
    }
  }

  buffer += decoder.decode();
  if (buffer.trim()) acceptMessage(state, parseSseDataLine(buffer), options.onMessage);
  if (!state.done) throw incompleteStreamError(state.stderr);
  return { transcript: validateTranscript(state.transcript), duration: state.duration };
}
