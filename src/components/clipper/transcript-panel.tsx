"use client";

import type { MouseEvent } from "react";
import type { EditableWord } from "@/lib/clipper/types";
import type { WordGroup } from "./video-editor-types";
import { formatTimestamp } from "./video-editor-utils";

interface TranscriptPanelProps {
  groups: WordGroup[];
  selectedIds: Set<string>;
  onSeek: (time: number) => void;
  onToggleGroup: (group: WordGroup) => void;
  onWordMouseDown: (event: MouseEvent, wordId: string) => void;
  onWordMouseEnter: (event: MouseEvent, wordId: string) => void;
}

interface WordTokenProps {
  word: EditableWord;
  selected: boolean;
  onMouseDown: (event: MouseEvent, wordId: string) => void;
  onMouseEnter: (event: MouseEvent, wordId: string) => void;
}

function WordToken({ word, selected, onMouseDown, onMouseEnter }: WordTokenProps) {
  const color = word.removed
    ? selected ? "bg-red-500/20 text-neutral-400" : "text-neutral-400"
    : selected ? "bg-amber-500/30 text-white" : "text-green-300 hover:bg-green-500/10";
  return (
    <span onMouseDown={(event) => onMouseDown(event, word.id)}
      onMouseEnter={(event) => onMouseEnter(event, word.id)}
      className={`px-[3px] py-[1px] rounded text-[15px] leading-7 transition-colors cursor-pointer ${color}`}>
      {word.text}
    </span>
  );
}

interface GroupHeaderProps {
  group: WordGroup;
  onSeek: (time: number) => void;
  onToggle: () => void;
}

function GroupHeader({ group, onSeek, onToggle }: GroupHeaderProps) {
  const start = group.words[0]?.start ?? 0;
  const end = group.words[group.words.length - 1]?.end ?? 0;
  return (
    <div className="flex items-center gap-2 mb-1">
      <button onClick={() => onSeek(start)}
        className="text-[11px] font-mono text-neutral-600 hover:text-neutral-400 transition-colors">
        {formatTimestamp(start)} – {formatTimestamp(end)}
      </button>
      {group.speaker != null && (
        <button onClick={onToggle}
          className="text-[11px] text-neutral-700 hover:text-green-400 transition-colors"
          title="Toggle entire utterance keep/remove">
          Speaker {group.speaker}
        </button>
      )}
    </div>
  );
}

function TranscriptGroup(props: TranscriptPanelProps & { group: WordGroup }) {
  return (
    <div>
      <GroupHeader group={props.group} onSeek={props.onSeek}
        onToggle={() => props.onToggleGroup(props.group)} />
      <div className="flex flex-wrap gap-x-[2px] gap-y-0.5 leading-relaxed">
        {props.group.words.map((word) => (
          <WordToken key={word.id} word={word} selected={props.selectedIds.has(word.id)}
            onMouseDown={props.onWordMouseDown} onMouseEnter={props.onWordMouseEnter} />
        ))}
      </div>
    </div>
  );
}

export function TranscriptPanel(props: TranscriptPanelProps) {
  return (
    <div className="flex flex-col flex-1 min-w-0 min-h-0">
      <div className="overflow-y-auto bg-neutral-900/20 px-4 py-4 flex-1 cursor-text rounded-lg border border-neutral-800">
        <div className="space-y-5">
          {props.groups.map((group) => (
            <TranscriptGroup key={group.utteranceIdx} {...props} group={group} />
          ))}
        </div>
      </div>
    </div>
  );
}
