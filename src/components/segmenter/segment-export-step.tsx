"use client";

import { useState } from "react";
import { SegmentGroup } from "@/lib/types";
import MulticamStatusPanel from "./multicam-status-panel";
import SaveToWorkspace from "./save-to-workspace";
import SingleCamExportButton from "./single-cam-export-button";
import { useMulticamExport } from "./use-multicam-export";
interface Props {
  segments: SegmentGroup[];
  filePath: string;
  bcamPath: string;
  ccamPath: string;
  lav1Path: string;
  lav2Path: string;
}

const fmtTime = (s: number) =>
  `${Math.floor(s / 60)}:${Math.floor(s % 60).toString().padStart(2, "0")}`;
const isFiller = (title: string) => /^\s*filler\b/i.test(title);

export default function SegmentExportStep({ segments, filePath, bcamPath, ccamPath, lav1Path, lav2Path }: Props) {
  const [selectedIds, setSelectedIds] = useState<Set<number>>(
    () => new Set(segments.filter((s) => !isFiller(s.title)).map((s) => s.id)),
  );
  const exportable = segments.filter((s) => selectedIds.has(s.id));

  const toggleSegment = (id: number) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const selectAll = () => setSelectedIds(new Set(segments.map((s) => s.id)));
  const selectNone = () => setSelectedIds(new Set());

  const hasB = !!bcamPath;
  const hasC = !!ccamPath;
  const hasLav1 = !!lav1Path;
  const hasLav2 = !!lav2Path;
  const multicamEnabled = hasB || hasC || hasLav1 || hasLav2;
  const clipPayload = exportable.map((s) => ({ title: s.title, start: s.start, end: s.end }));
  const multicam = useMulticamExport({ filePath, bcamPath, ccamPath, lav1Path, lav2Path, segments: clipPayload });

  const allSelected = selectedIds.size === segments.length && segments.length > 0;

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-8">
        <h2 className="text-2xl font-bold mb-1">Choose clips and output</h2>
        <p className="text-neutral-400 text-sm">
          {exportable.length} clip{exportable.length !== 1 ? "s" : ""} ready to render as individual MP4s.
        </p>
        <p className="text-xs text-neutral-500 mt-1">
          Downloads include about 5 seconds of extra footage before and after each clip for final trimming.
        </p>
      </div>

      <div className="mb-8 rounded-xl border border-neutral-800 bg-neutral-900/30 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-neutral-800">
          <span className="text-xs text-neutral-500 uppercase tracking-wider font-medium">
            Clips
            <span className="ml-2 text-neutral-600 normal-case tracking-normal">
              {selectedIds.size} of {segments.length} selected
            </span>
          </span>
          <div className="flex items-center gap-3 text-xs">
            <button
              type="button"
              onClick={selectAll}
              disabled={allSelected}
              className="text-neutral-400 hover:text-cyan-300 disabled:opacity-30 disabled:cursor-default transition-colors"
            >
              Select all
            </button>
            <span className="text-neutral-700">·</span>
            <button
              type="button"
              onClick={selectNone}
              disabled={selectedIds.size === 0}
              className="text-neutral-400 hover:text-cyan-300 disabled:opacity-30 disabled:cursor-default transition-colors"
            >
              Clear
            </button>
          </div>
        </div>
        <div className="divide-y divide-neutral-800">
          {segments.map((seg, i) => {
            const filler = isFiller(seg.title);
            const willExport = selectedIds.has(seg.id);
            return (
              <label
                key={seg.id}
                className={`flex items-center justify-between px-4 py-1.5 cursor-pointer hover:bg-neutral-800/30 transition-colors ${willExport ? "" : "opacity-40"}`}
              >
                <div className="flex items-center gap-3 min-w-0">
                  <input
                    type="checkbox"
                    checked={willExport}
                    onChange={() => toggleSegment(seg.id)}
                    className="accent-cyan-500 shrink-0"
                  />
                  <span className="text-xs text-neutral-600 font-mono w-5 text-right shrink-0">{i + 1}</span>
                  <span className={`text-xs truncate ${filler ? "text-neutral-500 italic" : "text-neutral-200"}`}>
                    {seg.title}
                  </span>
                </div>
                <span className="text-xs text-neutral-500 font-mono shrink-0 ml-3">
                  {fmtTime(seg.start)} → {fmtTime(seg.end)}
                  <span className="text-neutral-700 ml-2">({Math.round(seg.end - seg.start)}s)</span>
                </span>
              </label>
            );
          })}
        </div>
      </div>

      <div className="mb-3">
        <h3 className="text-base font-semibold text-neutral-100">What should happen next?</h3>
        <p className="text-xs text-neutral-500">Choose one or more options. Nothing is uploaded automatically.</p>
      </div>
      <SingleCamExportButton filePath={filePath} segments={clipPayload} disabled={multicam.state.loading || !filePath || exportable.length === 0} />
      <button
        type="button"
        onClick={multicam.exportMulticam}
        disabled={multicam.state.loading || !filePath || exportable.length === 0 || !multicamEnabled}
        title={!multicamEnabled ? "Add an extra camera or separate microphone file in Step 1 to enable this option." : undefined}
        className="w-full flex items-center justify-between px-5 py-4 rounded-xl border border-cyan-500/50 bg-cyan-950/30 hover:bg-cyan-950/50 hover:border-cyan-400 disabled:opacity-40 disabled:cursor-not-allowed transition-all group"
      >
        <div className="text-left">
          <p className="text-sm font-semibold text-cyan-200">
            {multicam.state.loading ? "Creating synced files…" : "Download synced camera and audio files (optional)"}
          </p>
          <p className="text-xs text-cyan-400/70 mt-0.5">
            {multicamEnabled
              ? `Main video${hasB ? " + extra camera 1" : ""}${hasC ? " + extra camera 2" : ""}${hasLav1 ? " + microphone 1" : ""}${hasLav2 ? " + microphone 2" : ""} · synchronized in one zip`
              : "Add another camera or microphone file in Step 1 to use this option."}
          </p>
        </div>
        <span className="text-cyan-400 group-hover:text-cyan-200 transition-colors text-lg">
          {multicam.state.loading ? "⏳" : "⬇"}
        </span>
      </button>

      <MulticamStatusPanel s={multicam.state} />

      <SaveToWorkspace
        filePath={filePath}
        segments={clipPayload}
        disabled={multicam.state.loading || !filePath || exportable.length === 0}
      />
    </div>
  );
}
