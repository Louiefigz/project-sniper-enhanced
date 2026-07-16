import type { EditableWord } from "@/lib/clipper/types";
import type { TimeClip, WordGroup } from "./video-editor-types";

const WORD_GAP_TOLERANCE = 0.05;

export function formatTimestamp(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remaining = Math.floor(seconds % 60);
  return `${minutes}:${remaining.toString().padStart(2, "0")}`;
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const remaining = Math.round(seconds % 60);
  return remaining > 0 ? `${minutes}m ${remaining}s` : `${minutes}m`;
}

export function groupWords(words: EditableWord[]): WordGroup[] {
  const grouped = new Map<number, EditableWord[]>();
  for (const word of words) {
    const utterance = grouped.get(word.utteranceIdx) ?? [];
    utterance.push(word);
    grouped.set(word.utteranceIdx, utterance);
  }
  return Array.from(grouped.entries())
    .sort(([left], [right]) => left - right)
    .map(([utteranceIdx, utterance]) => ({
      utteranceIdx,
      speaker: utterance[0]?.speaker,
      words: utterance,
    }));
}

export function buildClips(words: EditableWord[]): TimeClip[] {
  const clips: TimeClip[] = [];
  for (const word of words) {
    const previous = clips[clips.length - 1];
    if (previous && word.start - previous.end <= WORD_GAP_TOLERANCE) {
      previous.end = word.end;
    } else {
      clips.push({ start: word.start, end: word.end });
    }
  }
  return clips;
}

export function buildKeptClips(words: EditableWord[]): TimeClip[] {
  const kept = words.filter((word) => !word.removed).sort((left, right) => left.start - right.start);
  return buildClips(kept);
}

export function buildSelectedClips(words: EditableWord[], ids: Set<string>): TimeClip[] {
  return buildClips(words.filter((word) => ids.has(word.id) && !word.removed));
}

export function getTimeRange(words: EditableWord[], ids: Set<string>): TimeClip | null {
  const selected = words.filter((word) => ids.has(word.id));
  if (!selected.length) return null;
  return {
    start: Math.min(...selected.map((word) => word.start)),
    end: Math.max(...selected.map((word) => word.end)),
  };
}

export function buildRangeIds(words: EditableWord[], anchorIdx: number, currentIdx: number): Set<string> {
  const [start, end] = anchorIdx <= currentIdx
    ? [anchorIdx, currentIdx]
    : [currentIdx, anchorIdx];
  return new Set(words.slice(start, end + 1).map((word) => word.id));
}

export function setWordsRemoved(words: EditableWord[], ids: Set<string>, removed: boolean): EditableWord[] {
  return words.map((word) => ids.has(word.id) ? { ...word, removed } : word);
}

export function toggleGroup(words: EditableWord[], group: WordGroup): EditableWord[] {
  const removeGroup = group.words.every((word) => !word.removed);
  const groupIds = new Set(group.words.map((word) => word.id));
  return setWordsRemoved(words, groupIds, removeGroup);
}
