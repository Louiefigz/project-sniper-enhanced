import type { EditableWord } from "@/lib/clipper/types";
import type { MouseEvent, RefObject } from "react";

export interface VideoEditorProps {
  words: EditableWord[];
  onChange: (words: EditableWord[]) => void;
  onContinue: () => void;
  videoSrc?: string;
  fileName?: string;
  duration?: number;
}

export interface WordGroup {
  utteranceIdx: number;
  speaker?: number | null;
  words: EditableWord[];
}

export interface TimeClip {
  start: number;
  end: number;
}

export interface PlaybackControls {
  videoRef: RefObject<HTMLVideoElement | null>;
  playCurrentSegment: (fromTime?: number) => void;
  playRange: (startTime: number, endTime: number, clips?: TimeClip[]) => void;
  seekTo: (time: number) => void;
  pause: () => void;
  togglePlayback: (fromTime?: number) => void;
}

export interface SelectionControls {
  selectedIds: Set<string>;
  selectionHasRemoved: boolean;
  cutSelection: () => void;
  restoreSelection: () => void;
  clearSelection: () => void;
  onWordMouseDown: (event: MouseEvent, wordId: string) => void;
  onWordMouseEnter: (event: MouseEvent, wordId: string) => void;
}
