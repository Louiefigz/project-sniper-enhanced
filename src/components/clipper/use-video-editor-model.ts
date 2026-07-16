"use client";

import { useCallback, useEffect, useMemo } from "react";
import type { EditableWord } from "@/lib/clipper/types";
import { computeFinalClips, generateDebugTXT } from "@/lib/clipper/export";
import { downloadText } from "@/lib/clipper/download";
import { dlog } from "@/lib/debug";
import type { VideoEditorProps, WordGroup } from "./video-editor-types";
import { buildKeptClips, groupWords, toggleGroup } from "./video-editor-utils";
import { useEditorShortcuts } from "./use-editor-shortcuts";
import { useVideoPlayback } from "./use-video-playback";
import { useWordSelection } from "./use-word-selection";

function useMountLog(words: EditableWord[], duration: number, videoSrc?: string): void {
  useEffect(() => {
    dlog("clipper:edit", "editor mounted", {
      words: words.length,
      durationSec: Math.round(duration),
      videoSrc,
    });
    // The mount event intentionally records the editor's initial payload once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

function useEditorData(words: EditableWord[]) {
  const groups = useMemo(() => groupWords(words), [words]);
  const finalClips = useMemo(() => computeFinalClips(words), [words]);
  const exportDuration = useMemo(() => finalClips.reduce(
    (total, clip) => total + clip.end - clip.start, 0,
  ), [finalClips]);
  const keptClips = useMemo(() => buildKeptClips(words), [words]);
  const canExport = finalClips.length > 0 && words.some((word) => !word.removed);
  return { groups, exportDuration, keptClips, canExport };
}

export function useVideoEditorModel(props: VideoEditorProps) {
  const { words, onChange, duration = 0, fileName = "clip", videoSrc } = props;
  useMountLog(words, duration, videoSrc);
  const data = useEditorData(words);
  const playback = useVideoPlayback(data.keptClips);
  const selection = useWordSelection({ words, onChange, playRange: playback.playRange });
  useEditorShortcuts({
    words, selectedIds: selection.selectedIds,
    onCut: selection.cutSelection, onRestore: selection.restoreSelection,
    onClear: selection.clearSelection, onTogglePlayback: playback.togglePlayback,
  });
  const onToggleGroup = useCallback((group: WordGroup) => {
    onChange(toggleGroup(words, group));
  }, [onChange, words]);
  const onDebugDownload = useCallback(() => {
    const report = generateDebugTXT(words, fileName, duration);
    downloadText(report, `${fileName.replace(/\.[^.]+$/, "")}-debug.txt`);
  }, [duration, fileName, words]);
  return { data, playback, selection, onToggleGroup, onDebugDownload };
}
