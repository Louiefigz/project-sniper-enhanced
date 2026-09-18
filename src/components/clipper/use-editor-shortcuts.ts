"use client";

import { useEffect } from "react";
import type { EditableWord } from "@/lib/clipper/types";

interface ShortcutOptions {
  words: EditableWord[];
  selectedIds: Set<string>;
  onCut: () => void;
  onRestore: () => void;
  onClear: () => void;
  onTogglePlayback: (fromTime?: number) => void;
}

function isTypingTarget(target: EventTarget | null): boolean {
  const tagName = (target as HTMLElement | null)?.tagName;
  return tagName === "INPUT" || tagName === "TEXTAREA";
}

function selectedStart(words: EditableWord[], selectedIds: Set<string>): number | undefined {
  const starts = words.filter((word) => selectedIds.has(word.id)).map((word) => word.start);
  return starts.length ? Math.min(...starts) : undefined;
}

export function useEditorShortcuts(options: ShortcutOptions): void {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target)) return;
      if (event.key === " ") {
        event.preventDefault();
        options.onTogglePlayback(selectedStart(options.words, options.selectedIds));
      } else if (event.key === "Backspace" || event.key === "Delete") {
        event.preventDefault();
        options.onCut();
      } else if (event.key === "r" || event.key === "R") {
        event.preventDefault();
        options.onRestore();
      } else if (event.key === "Escape") {
        options.onClear();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [options]);
}
