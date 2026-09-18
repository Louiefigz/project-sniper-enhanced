import type { TranscriptEntry, VideoMetadata } from "@/lib/clipper/types";

export type TranscriptionEvent = Record<string, unknown> & {
  status?: string;
  error?: string;
  stderr?: string;
};

export interface TranscriptionDoneEvent extends TranscriptionEvent {
  status: "done";
  transcript: TranscriptEntry[];
  media: VideoMetadata;
  language?: string;
  model?: string;
}

export interface DecoratedWorkerLine {
  payload: string;
  done: boolean;
}

export function decorateTranscriptionWorkerLine(
  line: string,
  media: VideoMetadata,
): DecoratedWorkerLine {
  try {
    const event = JSON.parse(line) as Record<string, unknown>;
    if (event.status !== "done") return { payload: line, done: false };
    const fps = media.frameRate.numerator / media.frameRate.denominator;
    return { payload: JSON.stringify({ ...event, duration: media.duration, fps, media }), done: true };
  } catch {
    return { payload: line, done: false };
  }
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function isVideoMetadata(value: unknown): value is VideoMetadata {
  if (!value || typeof value !== "object") return false;
  const media = value as Partial<VideoMetadata>;
  const rate = media.frameRate;
  return typeof media.duration === "number" && Number.isFinite(media.duration)
    && media.duration > 0 && isPositiveInteger(media.width)
    && isPositiveInteger(media.height) && !!rate
    && isPositiveInteger(rate.numerator) && isPositiveInteger(rate.denominator);
}

function terminalEvent(event: TranscriptionEvent): TranscriptionDoneEvent | null {
  if (event.status !== "done") return null;
  if (!Array.isArray(event.transcript) || !isVideoMetadata(event.media)) {
    throw new Error("Transcription completed without valid source media metadata");
  }
  return event as TranscriptionDoneEvent;
}

function parseDataLine(line: string): TranscriptionEvent | null {
  if (!line.startsWith("data:")) return null;
  const raw = line.slice(5).trim();
  if (!raw) return null;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    throw new Error("Transcription stream emitted malformed JSON");
  }
  if (!value || typeof value !== "object") {
    throw new Error("Transcription stream emitted an invalid event");
  }
  return value as TranscriptionEvent;
}

async function responseFailure(response: Response): Promise<Error> {
  const text = (await response.text()).trim();
  let detail = text;
  try {
    const parsed = JSON.parse(text) as { error?: unknown };
    if (typeof parsed.error === "string") detail = parsed.error;
  } catch { /* keep the response text */ }
  return new Error(detail || `Transcription request failed (${response.status})`);
}

export async function consumeTranscriptionResponse(
  response: Response,
  onEvent: (event: TranscriptionEvent) => void,
): Promise<TranscriptionDoneEvent> {
  if (!response.ok) throw await responseFailure(response);
  if (!response.body) throw new Error("Transcription response had no stream");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal: TranscriptionDoneEvent | null = null;

  const consumeLine = (line: string) => {
    const event = parseDataLine(line.replace(/\r$/, ""));
    if (!event) return;
    if (typeof event.error === "string" && event.error) throw new Error(event.error);
    onEvent(event);
    const candidate = terminalEvent(event);
    if (candidate) terminal = candidate;
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    lines.forEach(consumeLine);
  }
  buffer += decoder.decode();
  if (buffer.trim()) consumeLine(buffer);
  if (!terminal) throw new Error("Transcription stream ended before a terminal done event");
  return terminal;
}
