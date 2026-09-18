"use client";

import { useState } from "react";
import Link from "next/link";
import { dlog, derror } from "@/lib/debug";

interface Props {
  filePath: string;
  segments: { title: string; start: number; end: number }[];
  disabled: boolean;
}

// "Save to workspace" — alongside (not replacing) the zip download. Segments
// are stream-copied server-side into a NEW workspace project's segments/ dir
// (POST /api/segmenter/save-to-workspace); the producer page's Recent-edits
// card then offers per-segment "Ingest → edit".
export default function SaveToWorkspace({ filePath, segments, disabled }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<{ projectRoot: string; segments: string[] } | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      dlog("segmenter:workspace", "save request", { filePath, segments: segments.length });
      const res = await fetch("/api/segmenter/save-to-workspace", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filePath, segments }),
      });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || `save failed (${res.status})`);
      setSaved({ projectRoot: data.projectRoot, segments: data.segments });
    } catch (e) {
      derror("segmenter:workspace", "save failed", e);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={save}
        disabled={disabled || busy}
        className="w-full flex items-center justify-between px-5 py-4 rounded-xl border border-emerald-500/50 bg-emerald-950/30 hover:bg-emerald-950/50 hover:border-emerald-400 disabled:opacity-40 disabled:cursor-not-allowed transition-all group"
      >
        <div className="text-left">
          <p className="text-sm font-semibold text-emerald-200">
            {busy ? "Saving clips for Producer…" : "Save clips for editing in Producer"}
          </p>
          <p className="text-xs text-emerald-400/70 mt-0.5">
            Creates a new local project with one MP4 per selected clip. You choose when to start editing.
          </p>
        </div>
        <span className="text-emerald-400 group-hover:text-emerald-200 transition-colors text-lg">
          {busy ? "⏳" : "⇥"}
        </span>
      </button>
      {saved && (
        <div className="mt-2 rounded-lg border border-emerald-800/50 bg-emerald-950/20 p-3">
          <p className="text-sm text-emerald-300">
            Saved {saved.segments.length} clip{saved.segments.length !== 1 ? "s" : ""} for Producer.
          </p>
          <p className="mt-1 break-all font-mono text-[10px] text-neutral-500">{saved.projectRoot}</p>
          <Link href="/producer" className="mt-3 inline-flex rounded-md bg-emerald-600 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-500">
            Open Producer →
          </Link>
        </div>
      )}
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-400 p-3 bg-red-950/20 border border-red-900/30 rounded-lg">{error}</p>
      )}
    </div>
  );
}
