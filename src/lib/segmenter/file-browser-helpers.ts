import type { SegmentGroup, TranscriptEntry } from "@/lib/types";

export type SlotKey = "a" | "b" | "c" | "lav1" | "lav2";
export type PickedFile = { path: string; name: string };
export type FileSlots = Record<SlotKey, PickedFile | null>;
export type SegmentPromptTemplateId = "topics" | "coaching" | "custom";

export const SLOT_LABELS: Record<SlotKey, string> = {
  a: "main video",
  b: "extra camera 1",
  c: "extra camera 2",
  lav1: "microphone audio 1",
  lav2: "microphone audio 2",
};

export const EMPTY_SLOTS: FileSlots = {
  a: null,
  b: null,
  c: null,
  lav1: null,
  lav2: null,
};

const TOPIC_CHANGES_PROMPT =
  "Find a new clip whenever the main topic or story clearly changes. Keep each clip understandable on its own. " +
  "Start at the first complete thought about that topic and end after its final useful thought. " +
  "Do not include setup chatter, long pauses, repeated takes, or transitions that belong to the next topic. " +
  "Give every clip a short, specific title that describes what a viewer will learn.";

const COACHING_CONVERSATIONS_PROMPT =
  "This is a coaching show where guests pitch their business to a host. Segment based on each new guest's CONVERSATION with the host.\n\n" +
  "A guest segment STARTS at the exact word where the host first directly addresses the guest by name " +
  "(e.g. 'Hey Alex', 'Welcome Sarah', 'Alright Sebastian'), OR at the guest's first word if the host doesn't address them by name first. " +
  "Use word-level precision — pick the EXACT word from the [WORDS] data.\n\n" +
  "Inside the guest segment, the conversation typically follows the pattern: guest introduces themselves ('my name is X', 'I own a Y business', " +
  "'I'm doing Z in revenue', 'what's stopping me is B'), host coaches them, then they wrap up.\n\n" +
  "A guest segment ENDS at the LAST word of the wrap-up exchange — phrases like 'thank you so much', 'rock and roll', 'go crush it', " +
  "'appreciate you'. Trailing banter or transition to the next guest is NOT part of this segment.\n\n" +
  "Everything between guest conversations is filler — including host pump-up ('alright let's rock', 'let's slay the day'), " +
  "calling for the next guest ('Jamie, pull him up'), technical setup ('can you hear me', 'unmute yourself' before the guest actually replies), " +
  "reading prep notes about the next guest, ad reads, and banter. Each filler stretch gets its OWN segment with title prefixed 'Filler – ' " +
  "(e.g. 'Filler – Pre-Sebastian transition'). Do NOT include any filler at the start or end of a guest segment.\n\n" +
  "Label each guest segment with the guest's name if mentioned, otherwise a short description of their business " +
  "(e.g. 'Sebastian – Netherlands relocation services').";

export const SEGMENT_PROMPT_TEMPLATES: ReadonlyArray<{
  id: SegmentPromptTemplateId;
  label: string;
  description: string;
}> = [
  {
    id: "topics",
    label: "Topic changes",
    description: "Recommended for interviews, podcasts, lessons, and talking-head videos.",
  },
  {
    id: "coaching",
    label: "Coaching conversations",
    description: "One clip per host-and-guest coaching conversation; transitions become filler.",
  },
  {
    id: "custom",
    label: "Custom",
    description: "Describe your own clip boundaries in plain language.",
  },
];

export function segmentPromptForTemplate(id: SegmentPromptTemplateId): string {
  if (id === "coaching") return COACHING_CONVERSATIONS_PROMPT;
  if (id === "custom") return "";
  return TOPIC_CHANGES_PROMPT;
}

export const DEFAULT_SEGMENT_PROMPT = TOPIC_CHANGES_PROMPT;

const VIDEO_EXT = /\.(mp4|mov|m4v|avi|mkv|mpg|mpeg|webm|wmv|flv)$/i;
const AUDIO_EXT = /\.(wav|mp3|m4a|aac|flac|ogg|opus|aif|aiff|caf|wma)$/i;

function camHintScore(name: string): number {
  const normalized = name.toLowerCase();
  if (/master|\ba[\s_-]?cam\b|\bcam[\s_-]?a\b|\bacam\b/.test(normalized)) return 0;
  if (/\bb[\s_-]?cam\b|\bcam[\s_-]?b\b|\bbcam\b/.test(normalized)) return 1;
  if (/\bc[\s_-]?cam\b|\bcam[\s_-]?c\b|\bccam\b/.test(normalized)) return 2;
  return 1.5;
}

export function autoAssign(files: PickedFile[]): {
  assigned: Partial<Record<SlotKey, PickedFile>>;
  leftovers: PickedFile[];
} {
  const videos = files.filter((file) => VIDEO_EXT.test(file.name));
  const audios = files.filter((file) => AUDIO_EXT.test(file.name));
  const unknown = files.filter((file) => !VIDEO_EXT.test(file.name) && !AUDIO_EXT.test(file.name));
  videos.sort((a, b) => camHintScore(a.name) - camHintScore(b.name) || a.name.localeCompare(b.name));
  audios.sort((a, b) => a.name.localeCompare(b.name));

  const assigned: Partial<Record<SlotKey, PickedFile>> = {};
  (["a", "b", "c"] as SlotKey[]).forEach((slot, index) => {
    if (videos[index]) assigned[slot] = videos[index];
  });
  (["lav1", "lav2"] as SlotKey[]).forEach((slot, index) => {
    if (audios[index]) assigned[slot] = audios[index];
  });
  return { assigned, leftovers: [...videos.slice(3), ...audios.slice(2), ...unknown] };
}

export function formatTime(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  if (hours > 0) return `${hours}:${minutes.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  return `${minutes}:${secs.toString().padStart(2, "0")}`;
}

export function validateTranscript(value: unknown): TranscriptEntry[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error("Transcription returned 0 utterances. Check that the source has audible speech.");
  }
  for (const [index, entry] of value.entries()) {
    const candidate = entry as Partial<TranscriptEntry>;
    const validTimes = Number.isFinite(candidate.start) && Number.isFinite(candidate.end);
    if (!validTimes || candidate.end! < candidate.start! || typeof candidate.text !== "string") {
      throw new Error(`Transcription returned an invalid utterance at position ${index + 1}.`);
    }
  }
  return value as TranscriptEntry[];
}

function isValidSegment(segment: Partial<SegmentGroup>, transcriptLength: number): boolean {
  return Number.isInteger(segment.id)
    && typeof segment.title === "string"
    && segment.title.trim().length > 0
    && Number.isInteger(segment.startLine)
    && Number.isInteger(segment.endLine)
    && segment.startLine! >= 0
    && segment.endLine! >= segment.startLine!
    && segment.endLine! < transcriptLength
    && Number.isFinite(segment.start)
    && Number.isFinite(segment.end)
    && segment.end! > segment.start!
    && typeof segment.summary === "string";
}

export function validateSegments(value: unknown, transcriptLength: number): SegmentGroup[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error("The editor returned no segments. Adjust the instructions and retry.");
  }
  let previousEndLine = -1;
  for (const [index, entry] of value.entries()) {
    const segment = entry as Partial<SegmentGroup>;
    if (!isValidSegment(segment, transcriptLength) || segment.startLine! <= previousEndLine) {
      throw new Error(`The editor returned an invalid segment at position ${index + 1}.`);
    }
    previousEndLine = segment.endLine!;
  }
  return value as SegmentGroup[];
}

export function segmentsFromPayload(value: unknown, transcriptLength: number): SegmentGroup[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Segmentation returned an invalid response.");
  }
  const payload = value as { error?: unknown; segments?: unknown };
  if (payload.error !== undefined && payload.error !== null) {
    const message = typeof payload.error === "string" && payload.error.trim()
      ? payload.error : "Segmentation returned an error.";
    throw new Error(message);
  }
  return validateSegments(payload.segments, transcriptLength);
}

export async function responseError(response: Response, operation: string): Promise<Error> {
  const text = await response.text();
  try {
    const data = JSON.parse(text) as { error?: unknown };
    if (typeof data.error === "string" && data.error.trim()) return new Error(data.error);
  } catch {
    // Fall through to the HTTP status when the response is not JSON.
  }
  return new Error(`${operation} failed (${response.status} ${response.statusText || "HTTP error"}).`);
}
