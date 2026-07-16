"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CutSegment, sourceToOutput } from "@/lib/producer/edit-plan";

export interface SourceWord {
  sourceId: string;
  word: string;
  start: number; // SOURCE seconds
  end: number;
}

export interface CutRange {
  sourceId: string;
  start: number;
  end: number;
}

type WordStatus = "loading" | "ready" | "error";

interface Props {
  dir: string;
  cutTrack: CutSegment[];
  currentTime: number;
  onSeek: (t: number) => void;
  onCutRanges: (ranges: CutRange[]) => void;
  onRestoreRanges: (ranges: CutRange[]) => void; // un-cut: add struck SOURCE ranges back
  locked?: boolean;
}

/** Group the selected words into one SOURCE-seconds range per sourceId. */
function rangesFor(words: SourceWord[]): CutRange[] {
  const bySource = new Map<string, CutRange>();
  for (const w of words) {
    const r = bySource.get(w.sourceId);
    if (!r) bySource.set(w.sourceId, { sourceId: w.sourceId, start: w.start, end: w.end });
    else {
      r.start = Math.min(r.start, w.start);
      r.end = Math.max(r.end, w.end);
    }
  }
  return [...bySource.values()];
}

// Script mode — the Opus-Clip strike-to-cut surface. Words are SOURCE-time;
// each is mapped through the cutTrack (deterministic TS arithmetic, same
// piecewise map as cutWindows): unmapped words render struck-through (already
// cut). Click a kept word to seek; click+drag or click→shift-click to select
// a range, then "Cut selection" removes it from plan.cutTrack via
// removeSourceRange — and a selection holding struck (dim) words offers
// "Restore selection" (addSourceRange puts them back). Both undo-able.
export default function ScriptWords({ dir, cutTrack, currentTime, onSeek, onCutRanges, onRestoreRanges, locked }: Props) {
  const [words, setWords] = useState<SourceWord[]>([]);
  const [status, setStatus] = useState<WordStatus>("loading");
  const [error, setError] = useState<string>("");
  const [attempt, setAttempt] = useState(0);
  const requestKey = `${dir}\u0000${attempt}`;
  const [settledKey, setSettledKey] = useState("");
  const [anchor, setAnchor] = useState<number | null>(null);
  const [focus, setFocus] = useState<number | null>(null);
  const dragging = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/producer/words?dir=${encodeURIComponent(dir)}`, { signal: controller.signal })
      .then(async (r) => {
        const d = await r.json().catch(() => ({})) as { words?: SourceWord[]; error?: string };
        if (!r.ok) throw new Error(d.error || `words ${r.status}`);
        setWords(Array.isArray(d.words) ? d.words : []);
        setError("");
        setStatus("ready");
        setSettledKey(requestKey);
        setAnchor(null);
        setFocus(null);
      })
      .catch((e) => {
        if (e instanceof Error && e.name === "AbortError") return;
        setError(e instanceof Error ? e.message : "Failed to load words");
        setStatus("error");
        setSettledKey(requestKey);
      });
    return () => controller.abort();
  }, [dir, requestKey]);

  useEffect(() => {
    const up = () => (dragging.current = false);
    window.addEventListener("mouseup", up);
    return () => window.removeEventListener("mouseup", up);
  }, []);

  // Per-word output time (null = the word's midpoint is cut out of the edit).
  const outTimes = useMemo(
    () => words.map((w) => sourceToOutput(cutTrack, w.sourceId, (w.start + w.end) / 2)),
    [words, cutTrack],
  );

  // Output time is NOT monotonic in transcript order (a reordered cutTrack can
  // pull a hook from later in the raw take) — sort the kept words by outTime
  // once, then binary-search the last outTime <= currentTime.
  const sortedOutTimes = useMemo(() => {
    const arr: { outTime: number; idx: number }[] = [];
    outTimes.forEach((t, idx) => {
      if (t !== null) arr.push({ outTime: t, idx });
    });
    arr.sort((a, b) => a.outTime - b.outTime);
    return arr;
  }, [outTimes]);

  const activeIdx = useMemo(() => {
    let lo = 0;
    let hi = sortedOutTimes.length - 1;
    let best = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (sortedOutTimes[mid].outTime <= currentTime) {
        best = mid;
        lo = mid + 1;
      } else {
        hi = mid - 1;
      }
    }
    return best === -1 ? -1 : sortedOutTimes[best].idx;
  }, [sortedOutTimes, currentTime]);

  const sel: [number, number] | null =
    anchor !== null && focus !== null
      ? [Math.min(anchor, focus), Math.max(anchor, focus)]
      : null;
  const selWords = sel ? words.slice(sel[0], sel[1] + 1) : [];
  const selSpanS = selWords.length
    ? Math.max(...selWords.map((w) => w.end)) - Math.min(...selWords.map((w) => w.start))
    : 0;

  const clearSel = () => {
    setAnchor(null);
    setFocus(null);
  };

  const wordDown = (i: number, e: React.MouseEvent) => {
    e.preventDefault();
    if (locked) {
      const out = outTimes[i];
      if (out !== null) onSeek(out);
      return;
    }
    if (e.shiftKey && anchor !== null) {
      setFocus(i);
      return;
    }
    dragging.current = true;
    setAnchor(i);
    setFocus(i);
  };

  const wordUp = (i: number, e: React.MouseEvent) => {
    dragging.current = false;
    const plainClick = !e.shiftKey && anchor === i && focus === i;
    const out = outTimes[i];
    if (plainClick && out !== null) onSeek(out);
  };

  // A mixed selection offers both actions, each scoped to ITS words: Cut takes
  // the kept words, Restore takes the struck ones.
  const selKept = selWords.filter((_, j) => sel && outTimes[sel[0] + j] !== null);
  const selStruck = selWords.filter((_, j) => sel && outTimes[sel[0] + j] === null);

  const cutSelection = () => {
    if (!selKept.length || locked) return;
    onCutRanges(rangesFor(selKept));
    clearSel();
  };

  const restoreSelection = () => {
    if (!selStruck.length || locked) return;
    onRestoreRanges(rangesFor(selStruck));
    clearSel();
  };

  const visibleStatus = settledKey === requestKey ? status : "loading";
  if (visibleStatus === "loading") {
    return <p className="px-1 text-xs text-neutral-500" aria-live="polite">Loading words…</p>;
  }
  if (visibleStatus === "error") {
    return (
      <div className="space-y-2 px-1 text-xs" role="alert">
        <p className="text-rose-400">Couldn&apos;t load the word transcript. {error}</p>
        <button onClick={() => setAttempt((n) => n + 1)} className="text-sky-300 hover:text-sky-200">
          Try again
        </button>
      </div>
    );
  }
  if (words.length === 0) {
    return (
      <div className="space-y-1 px-1 text-xs text-neutral-500">
        <p>No word-level transcript is available for this edit.</p>
        <p className="text-[10px]">The video can still play, but word-based cuts require a transcript.</p>
      </div>
    );
  }

  return (
    <div className="relative">
      <div className="select-none leading-7">
        {words.map((w, i) => {
          const cut = outTimes[i] === null;
          const inSel = sel !== null && i >= sel[0] && i <= sel[1];
          return (
            <span
              key={i}
              onMouseDown={(e) => wordDown(i, e)}
              onMouseEnter={() => dragging.current && setFocus(i)}
              onMouseUp={(e) => wordUp(i, e)}
              className={`cursor-pointer rounded-sm px-0.5 ${
                inSel
                  ? "bg-sky-500/40 text-sky-50"
                  : cut
                    ? "text-neutral-600 line-through decoration-neutral-600"
                    : i === activeIdx
                      ? "bg-amber-400/20 text-amber-100"
                      : "text-neutral-200 hover:bg-neutral-800/70"
              }`}
            >
              {w.word}{" "}
            </span>
          );
        })}
      </div>

      {selWords.length > 0 && (
        <div className="sticky bottom-0 mt-2 flex items-center gap-2 rounded-md border border-neutral-700 bg-neutral-900/95 px-2 py-1.5 shadow-lg">
          <span className="text-[11px] text-neutral-400">
            {selWords.length} word{selWords.length === 1 ? "" : "s"} · ~{selSpanS.toFixed(1)}s
          </span>
          {selKept.length > 0 && (
            <button
              onClick={cutSelection}
              disabled={locked}
              className="rounded border border-rose-500/50 px-2 py-0.5 text-[11px] text-rose-300 enabled:hover:bg-rose-500/10 disabled:opacity-40"
            >
              Cut selection
            </button>
          )}
          {selStruck.length > 0 && (
            <button
              onClick={restoreSelection}
              disabled={locked}
              title="Restore these words to the edit (choose Render updated video to apply)"
              className="rounded border border-emerald-500/50 px-2 py-0.5 text-[11px] text-emerald-300 enabled:hover:bg-emerald-500/10 disabled:opacity-40"
            >
              Restore selection
            </button>
          )}
          <button onClick={clearSel} className="text-[11px] text-neutral-500 hover:text-neutral-300">
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
