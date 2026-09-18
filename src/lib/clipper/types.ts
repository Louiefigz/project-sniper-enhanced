// Word-level timestamp from Deepgram
export interface WordTiming {
  word: string;
  start: number;
  end: number;
  confidence?: number;
  speaker?: number | null;
}

// Transcript entry (utterance from Deepgram)
export interface TranscriptEntry {
  start: number;
  end: number;
  text: string;
  words?: WordTiming[];
}

// LLM edit decisions — per transcript utterance
export type SegmentAction = "keep" | "remove" | "trim";

export interface LineDecision {
  index: number;
  action: SegmentAction;
  text?: string; // trimmed text when action === "trim"
  /** Set by the fragment-validation pass when the output text appears to start mid-sentence. */
  fragmentWarning?: boolean;
  /** Brief rationale from the LLM explaining the decision, parsed from inline // comment. */
  rationale?: string;
}

// A single word in the editable transcript.
// Every word carries its own Deepgram start/end timestamp.
// Removing a word excludes exactly that time range from the FCPXML.
export interface EditableWord {
  id: string;
  text: string;
  removed: boolean;
  start: number;           // word-level timestamp from Deepgram (required)
  end: number;             // word-level timestamp from Deepgram (required)
  utteranceIdx: number;    // which source utterance this word belongs to (display grouping only)
  confidence?: number;
  speaker?: number | null;
  /** Propagated from LineDecision.fragmentWarning — marks the first word of a potentially mid-sentence utterance. */
  fragmentWarning?: boolean;
  /** LLM rationale for this word's utterance decision, propagated to the first word of each utterance. */
  rationale?: string;
}

// Speaker name map: Deepgram speaker ID → human-readable label (e.g. "Host", "Guest")
export type SpeakerMap = Record<number, string>;

// Exact source timebase as reported by ffprobe (for example 30000/1001).
// `fps` remains on Source as a convenient derived display value, while export
// math uses this rational value so NTSC and other fractional rates do not drift.
export interface FrameRate {
  numerator: number;
  denominator: number;
}

export interface VideoMetadata {
  duration: number;
  frameRate: FrameRate;
  width: number;
  height: number;
}

// One physical camera file in the recording.
// Exactly one angle in a Source has audioSource:true — that file's audio is what
// gets transcribed, and is the only audio routed in the exported FCPXML.
export interface CamAngle {
  id: "A" | "B";
  filePath: string;
  audioSource: boolean;
}

// A recording — A-only (single-cam) or A+B (dual-cam). Angles are pre-synced
// upstream so segment timestamps apply identically to every angle.
export interface Source {
  angles: CamAngle[];   // length 1 (A-only) or 2 (A+B)
  duration: number;
  fps: number;
  frameRate: FrameRate;
  width: number;
  height: number;
  // Channels routed on the primary angle's audio (only used when audioMode is
  // "camera"). 2 = channel-isolated stereo (Host on srcCh=1, Caller on srcCh=2);
  // 1 = mono or cross-talk stereo downmixed during transcription. Drives FCPXML
  // audio-channel-source emission.
  audioChannels: 1 | 2;
  // Where the exported FCPXML's dialogue audio comes from:
  //   "camera" (default) — the primary angle's own audio channels (audioChannels above).
  //   "lavs"             — two clean lav mics replace the cameras' audio. lav1Path
  //                        (Host, speaker 0) and lav2Path (Guest, speaker 1) are
  //                        attached as separate audio assets on Host/Guest roles,
  //                        and the cameras' audio is muted.
  audioMode?: "camera" | "lavs";
  // Host lav (speaker 0) / Guest lav (speaker 1). Captured by the file browser;
  // become the export audio sources when audioMode === "lavs".
  lav1Path?: string;
  lav2Path?: string;
}

// Result of transcription, passed from the file browser to the page so it can set
// the speaker map. `twoSpeakers` means we know exactly two speakers (stereo
// channels or two lav mics) and they map to speaker 0/1; `speakerKind` labels the
// second speaker ("guest" for lav mode, "caller" for channel-isolated stereo).
export interface TranscribeCompleteInfo {
  twoSpeakers: boolean;
  speakerKind: "guest" | "caller" | "diarized";
  audioMode: "camera" | "lavs";
}

// App step flow
export type AppStep = "browse" | "prompt" | "edit" | "export";
