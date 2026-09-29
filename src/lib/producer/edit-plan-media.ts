/** Audio, framing, and caption contracts attached to an ordinary edit plan. */
export interface AudioGainEntry {
  id?: string;
  outStart: number;
  outEnd: number;
  dB: number;
}

export interface AudioEnhance {
  preset: "voice" | "voice-rnn" | "voice-strong" | "separate";
}

export interface MusicSpec {
  enabled: boolean;
  path?: string;
  assetId?: string;
  duck?: boolean;
  gapDb?: number;
}

/** Normalized [x, y, w, h] rect on the source frame. */
export type CropRect = [number, number, number, number];

export interface SplitCell {
  crop?: CropRect;
  frac?: number;
}

export interface ReframeSpec {
  strategy?: string;
  layout?: "fill" | "split";
  crop?: CropRect;
  split?: { top?: SplitCell; bottom?: SplitCell };
  track?: boolean;
}

export interface CaptionGroupV1 {
  groupId: string;
  anchor: { kind: "word-range"; wordIds: string[] };
  styleId: string;
  mode: "line" | "karaoke-word" | "karaoke-phrase";
  placement: "bottom-center" | "lower-third" | "center" | "top-center";
  language?: string;
  suppressUnderSceneIds?: string[];
}

export interface CaptionTrackV1 {
  schemaVersion: 1;
  source: "kept-transcript";
  defaultPolicy: "off" | "line" | "karaoke";
  groups: CaptionGroupV1[];
  transcriptCorrectionHash?: string;
}

export interface CaptionCorrectionV1 {
  correctionId: string;
  sourceWordIds: string[];
  displayTokens: string[];
  timingPolicy: "proportional-codepoints";
  reason?: string;
}

export interface CaptionCorrectionLedgerV1 {
  schemaVersion: 1;
  kind: "caption-correction-ledger";
  corrections: CaptionCorrectionV1[];
}

export interface CaptionChapterV1 {
  chapterId: string;
  title: string;
  wordId: string;
}
