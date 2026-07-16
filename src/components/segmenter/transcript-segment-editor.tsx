"use client";

import { useState } from "react";
import { TranscriptEntry, SegmentGroup } from "@/lib/types";
import { dlog } from "@/lib/debug";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";

interface Props {
  transcript: TranscriptEntry[];
  segments: SegmentGroup[];
  onChange: (segments: SegmentGroup[]) => void;
  onContinue: () => void;
}

function fmtTime(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

/**
 * Render only the portion of a line that falls within [segStart, segEnd].
 * For the first/last line of a segment this trims discarded leading/trailing
 * filler so the editor matches the exported cut.
 */
function lineDisplay(
  entry: TranscriptEntry,
  segStart: number,
  segEnd: number,
): { text: string; start: number; trimmed: boolean } {
  const eps = 0.01;
  const fullyInside = entry.start >= segStart - eps && entry.end <= segEnd + eps;
  if (fullyInside || !entry.words || entry.words.length === 0) {
    return { text: entry.text, start: entry.start, trimmed: false };
  }
  const visible = entry.words.filter(
    (w) => w.start >= segStart - eps && w.end <= segEnd + eps,
  );
  if (visible.length === 0) {
    return { text: entry.text, start: entry.start, trimmed: false };
  }
  const text = visible
    .map((w) => w.word)
    .join(" ")
    .replace(/\s+([.,!?;:])/g, "$1");
  return { text, start: visible[0].start, trimmed: true };
}

const SEGMENT_COLORS = [
  "border-l-cyan-500 bg-cyan-500/5",
  "border-l-emerald-500 bg-emerald-500/5",
  "border-l-orange-500 bg-orange-500/5",
  "border-l-pink-500 bg-pink-500/5",
  "border-l-amber-500 bg-amber-500/5",
  "border-l-yellow-500 bg-yellow-500/5",
  "border-l-sky-500 bg-sky-500/5",
  "border-l-red-500 bg-red-500/5",
];

const BADGE_COLORS = [
  "bg-cyan-500/20 text-cyan-400",
  "bg-emerald-500/20 text-emerald-400",
  "bg-orange-500/20 text-orange-400",
  "bg-pink-500/20 text-pink-400",
  "bg-amber-500/20 text-amber-400",
  "bg-yellow-500/20 text-yellow-400",
  "bg-sky-500/20 text-sky-400",
  "bg-red-500/20 text-red-400",
];

const FILLER_SEGMENT_COLOR = "border-l-neutral-600 bg-neutral-500/5";
const FILLER_BADGE_COLOR = "bg-neutral-700/40 text-neutral-400";

function isFiller(title: string): boolean {
  return /^\s*filler\b/i.test(title);
}

export default function TranscriptSegmentEditor({ transcript, segments, onChange, onContinue }: Props) {
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState("");

  const getSegmentForLine = (lineIdx: number): number => {
    for (let i = segments.length - 1; i >= 0; i--) {
      if (lineIdx >= segments[i].startLine) return i;
    }
    return 0;
  };

  const addBreakBefore = (lineIdx: number) => {
    if (lineIdx === 0 || segments.some((s) => s.startLine === lineIdx)) return;
    const updated = [...segments];
    const segIdx = getSegmentForLine(lineIdx);
    const oldSeg = { ...updated[segIdx] };
    const newSeg: SegmentGroup = {
      id: 0,
      title: "New Segment",
      startLine: lineIdx,
      endLine: oldSeg.endLine,
      start: transcript[lineIdx].start,
      end: oldSeg.end,
      summary: "",
    };
    updated[segIdx] = { ...oldSeg, endLine: lineIdx - 1, end: transcript[lineIdx - 1].end };
    updated.splice(segIdx + 1, 0, newSeg);
    updated.forEach((s, i) => (s.id = i + 1));
    dlog("segmenter:edit", "split segment", { atLine: lineIdx, segments: updated.length });
    onChange(updated);
  };

  const removeBreak = (segIdx: number) => {
    if (segIdx === 0) return;
    const updated = [...segments];
    updated[segIdx - 1] = {
      ...updated[segIdx - 1],
      endLine: updated[segIdx].endLine,
      end: updated[segIdx].end,
    };
    updated.splice(segIdx, 1);
    updated.forEach((s, i) => (s.id = i + 1));
    dlog("segmenter:edit", "merge segment", { mergedIdx: segIdx, segments: updated.length });
    onChange(updated);
  };

  const startEdit = (segIdx: number) => {
    setEditingIdx(segIdx);
    setEditTitle(segments[segIdx].title);
  };

  const saveEdit = () => {
    if (editingIdx === null) return;
    const updated = [...segments];
    updated[editingIdx] = { ...updated[editingIdx], title: editTitle.trim() || updated[editingIdx].title };
    dlog("segmenter:edit", "rename segment", { idx: editingIdx, title: updated[editingIdx].title, segments: updated.length });
    onChange(updated);
    setEditingIdx(null);
  };

  return (
    <div>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold mb-1">Review clips</h2>
          <p className="text-neutral-400 text-sm">
            {segments.length} clip{segments.length !== 1 ? "s" : ""}. Click a title to rename it, use scissors to split, or remove a boundary to merge.
          </p>
        </div>
        <Button
          onClick={onContinue}
          className="bg-cyan-600 hover:bg-cyan-700 text-white px-6 shrink-0 ml-4"
        >
          Choose output →
        </Button>
      </div>

      <div className="border border-neutral-800 rounded-xl overflow-hidden">
        <ScrollArea className="h-[640px]">
          <div className="p-3 space-y-1">
            {segments.map((seg, segIdx) => {
              const filler = isFiller(seg.title);
              const segColor = filler ? FILLER_SEGMENT_COLOR : SEGMENT_COLORS[segIdx % SEGMENT_COLORS.length];
              const badgeColor = filler ? FILLER_BADGE_COLOR : BADGE_COLORS[segIdx % BADGE_COLORS.length];
              return (
              <div key={`seg-${segIdx}-${seg.startLine}`}>
                {/* Segment header */}
                <div className={`flex items-center gap-2 px-3 py-2 rounded-t-lg border-l-4 ${segColor}`}>
                  {editingIdx === segIdx ? (
                    <div className="flex items-center gap-2 flex-1">
                      <input
                        autoFocus
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter") saveEdit(); if (e.key === "Escape") setEditingIdx(null); }}
                        className="flex-1 bg-neutral-950 border border-cyan-500/50 rounded px-2 py-0.5 text-sm font-medium text-white outline-none"
                      />
                      <button type="button" onClick={saveEdit} className="text-xs px-2 py-0.5 rounded bg-cyan-600 hover:bg-cyan-700 text-white">Save</button>
                      <button type="button" onClick={() => setEditingIdx(null)} className="text-xs px-2 py-0.5 rounded bg-neutral-700 hover:bg-neutral-600 text-neutral-300">Cancel</button>
                    </div>
                  ) : (
                    <>
                      <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${badgeColor}`}>{seg.id}</span>
                      <button
                        type="button"
                        className={`flex-1 text-left text-sm font-medium transition-colors hover:text-cyan-300 ${filler ? "text-neutral-400 italic" : "text-white"}`}
                        onClick={() => startEdit(segIdx)}
                        aria-label={`Rename ${seg.title}`}
                      >
                        {seg.title}
                      </button>
                      <span className="text-xs text-neutral-500 font-mono">
                        {fmtTime(seg.start)} → {fmtTime(seg.end)}
                      </span>
                      {segIdx > 0 && (
                        <button
                          type="button"
                          onClick={() => removeBreak(segIdx)}
                          className="text-neutral-600 hover:text-red-400 transition-colors text-xs ml-1"
                          title="Merge with previous segment"
                          aria-label={`Merge ${seg.title} with the previous clip`}
                        >✕</button>
                      )}
                    </>
                  )}
                </div>

                {/* Transcript lines */}
                <div className={`border-l-4 ${segColor}`}>
                  {transcript.slice(seg.startLine, seg.endLine + 1).map((entry, lineOffset) => {
                    const lineIdx = seg.startLine + lineOffset;
                    const isFirst = lineOffset === 0;
                    const display = lineDisplay(entry, seg.start, seg.end);
                    return (
                      <div key={lineIdx} className="group flex items-start gap-3 px-3 py-1.5 hover:bg-neutral-800/30 transition-colors">
                        <span className="text-xs text-neutral-600 font-mono pt-0.5 shrink-0 w-[80px]">
                          {fmtTime(display.start)}
                        </span>
                        <span className="flex-1 text-sm text-neutral-300 leading-relaxed">
                          {display.text}
                          {display.trimmed && (
                            <span className="ml-2 text-[10px] text-neutral-600 uppercase tracking-wider">trimmed</span>
                          )}
                        </span>
                        {!isFirst && (
                          <button
                            type="button"
                            onClick={() => addBreakBefore(lineIdx)}
                            className="opacity-0 group-hover:opacity-100 focus:opacity-100 text-neutral-500 hover:text-cyan-400 transition-all text-sm shrink-0 pt-0.5"
                            title="Split segment here"
                            aria-label={`Start a new clip at ${fmtTime(display.start)}`}
                          >✂️</button>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
            })}
          </div>
        </ScrollArea>
      </div>

      <div className="mt-4 flex justify-end">
        <Button
          onClick={onContinue}
          className="bg-cyan-600 hover:bg-cyan-700 text-white px-8"
        >
          Choose output →
        </Button>
      </div>
    </div>
  );
}
