"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent } from "react";
import type { EditableWord } from "@/lib/clipper/types";
import type { SelectionControls, TimeClip } from "./video-editor-types";
import {
  buildRangeIds,
  buildSelectedClips,
  getTimeRange,
  setWordsRemoved,
} from "./video-editor-utils";

interface SelectionOptions {
  words: EditableWord[];
  onChange: (words: EditableWord[]) => void;
  playRange: (start: number, end: number, clips?: TimeClip[]) => void;
}

function resolveSelectionIds(
  words: EditableWord[],
  selectedIds: Set<string>,
  wordId: string,
  extend: boolean,
): Set<string> {
  if (!extend || !selectedIds.size) return new Set([wordId]);
  const currentIdx = words.findIndex((word) => word.id === wordId);
  const anchorIdx = words.findIndex((word) => selectedIds.has(word.id));
  return buildRangeIds(words, anchorIdx, currentIdx);
}

export function useWordSelection(options: SelectionOptions): SelectionControls {
  const { words, onChange, playRange } = options;
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const isDragging = useRef(false);
  const dragAnchorIdx = useRef(-1);
  const clearSelection = useCallback(() => setSelectedIds(new Set()), []);
  const cutSelection = useCallback(() => {
    if (!selectedIds.size) return;
    onChange(setWordsRemoved(words, selectedIds, true));
    clearSelection();
  }, [clearSelection, onChange, selectedIds, words]);
  const restoreSelection = useCallback(() => {
    if (!selectedIds.size) return;
    onChange(setWordsRemoved(words, selectedIds, false));
    clearSelection();
  }, [clearSelection, onChange, selectedIds, words]);
  const onWordMouseDown = useCallback((event: MouseEvent, wordId: string) => {
    event.preventDefault();
    const ids = resolveSelectionIds(words, selectedIds, wordId, event.shiftKey);
    isDragging.current = true;
    dragAnchorIdx.current = words.findIndex((word) => word.id === wordId);
    setSelectedIds(ids);
    const range = getTimeRange(words, ids);
    if (!range) return;
    const clips = buildSelectedClips(words, ids);
    playRange(range.start, range.end, clips.length ? clips : undefined);
  }, [playRange, selectedIds, words]);
  const onWordMouseEnter = useCallback((_event: MouseEvent, wordId: string) => {
    if (!isDragging.current) return;
    const currentIdx = words.findIndex((word) => word.id === wordId);
    setSelectedIds(buildRangeIds(words, dragAnchorIdx.current, currentIdx));
  }, [words]);
  useEffect(() => {
    const stopDragging = () => { isDragging.current = false; };
    window.addEventListener("mouseup", stopDragging);
    return () => window.removeEventListener("mouseup", stopDragging);
  }, []);
  const selectionHasRemoved = useMemo(() =>
    selectedIds.size > 0 && words.some((word) => selectedIds.has(word.id) && word.removed),
  [selectedIds, words]);
  return {
    selectedIds, selectionHasRemoved, cutSelection, restoreSelection,
    clearSelection, onWordMouseDown, onWordMouseEnter,
  };
}
