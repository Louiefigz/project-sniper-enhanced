"use client";

import { useEffect, useRef, useState } from "react";
import ScriptWords, { CutRange } from "./script-words";
import SpeechCleanup from "./speech-cleanup";
import type { CutSegment } from "@/lib/producer/edit-plan";
import type { StreamEvent } from "@/lib/producer/types";

interface Cue {
  start: number;
  end: number;
  text: string;
}

type CaptionStatus = "loading" | "ready" | "unavailable" | "error";

interface CaptionState {
  status: CaptionStatus;
  cues: Cue[];
  message?: string;
  requestKey?: string;
}

interface Props {
  srtPath: string; // absolute path to <render dir>/captions.srt
  dir: string; // the render out dir (base.fingerprint.json → source words)
  cutTrack: CutSegment[];
  currentTime: number;
  onSeek: (t: number) => void;
  onCutRanges: (ranges: CutRange[]) => void;
  onRestoreRanges: (ranges: CutRange[]) => void;
  onApplyCutTrack: (cutTrack: CutSegment[]) => void;
  onWarning?: (ev: StreamEvent) => void; // warning-class stream statuses → the editor's strip
  locked?: boolean;
}

async function fetchCaptions(
  srtPath: string,
  attempt: number,
  signal: AbortSignal,
): Promise<CaptionState> {
  const response = await fetch(
    `/api/producer/transcript?path=${encodeURIComponent(srtPath)}&attempt=${attempt}`,
    { signal },
  );
  const data = await response.json().catch(() => ({})) as {
    available?: boolean;
    cues?: Cue[];
    error?: string;
  };
  if (response.status === 404 || data.available === false) {
    return { status: "unavailable", cues: [], message: data.error };
  }
  if (!response.ok) throw new Error(data.error || `Caption request failed (${response.status})`);
  return { status: "ready", cues: Array.isArray(data.cues) ? data.cues : [] };
}

function useCaptionCues(srtPath: string, attempt: number): CaptionState {
  const [state, setState] = useState<CaptionState>({ status: "loading", cues: [] });
  const requestKey = `${srtPath}\u0000${attempt}`;
  useEffect(() => {
    const controller = new AbortController();
    fetchCaptions(srtPath, attempt, controller.signal)
      .then((next) => setState({ ...next, requestKey }))
      .catch((error) => {
        if (error instanceof Error && error.name === "AbortError") return;
        setState({
          status: "error",
          cues: [],
          message: error instanceof Error ? error.message : "Caption request failed",
          requestKey,
        });
      });
    return () => controller.abort();
  }, [srtPath, attempt, requestKey]);
  return state.requestKey === requestKey ? state : { status: "loading", cues: [] };
}

function CaptionCues({ srtPath, currentTime, onSeek }: Pick<Props, "srtPath" | "currentTime" | "onSeek">) {
  const [attempt, setAttempt] = useState(0);
  const { status, cues, message } = useCaptionCues(srtPath, attempt);
  const activeRef = useRef<HTMLButtonElement>(null);

  const activeIdx = cues.findIndex((c) => currentTime >= c.start && currentTime < c.end);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeIdx]);

  if (status === "loading") {
    return <p className="text-neutral-500" aria-live="polite">Loading captions…</p>;
  }
  if (status === "unavailable") {
    return (
      <div className="space-y-2 text-neutral-500">
        <p>{message || "No caption transcript is available for this render yet."}</p>
        <p className="text-[10px]">Choose Render updated video to generate captions, then try again.</p>
        <button type="button" onClick={() => setAttempt((n) => n + 1)} className="text-xs text-sky-300 hover:text-sky-200">
          Check again
        </button>
      </div>
    );
  }
  if (status === "error") {
    return (
      <div className="space-y-2" role="alert">
        <p className="text-rose-300">Couldn&apos;t load captions. {message}</p>
        <button type="button" onClick={() => setAttempt((n) => n + 1)} className="text-xs text-sky-300 hover:text-sky-200">
          Try again
        </button>
      </div>
    );
  }
  if (cues.length === 0) {
    return <p className="text-neutral-500">The caption file loaded, but it contains no readable lines.</p>;
  }

  return (
    <div className="space-y-1 leading-relaxed">
      {cues.map((c, i) => (
        <button
          type="button"
          key={i}
          ref={i === activeIdx ? activeRef : undefined}
          onClick={() => onSeek(c.start)}
          className={`block w-full rounded px-1.5 py-0.5 text-left transition-colors ${
            i === activeIdx
              ? "bg-amber-400/15 text-amber-100"
              : "text-neutral-300 hover:bg-neutral-800/60"
          }`}
        >
          <span className="mr-2 select-none font-mono text-[9px] text-neutral-600">
            {c.start.toFixed(1)}
          </span>
          {c.text}
        </button>
      ))}
    </div>
  );
}

// Left panel — two views of the same speech: Captions (OUTPUT-time captions.srt,
// click to seek) and Script (SOURCE-time words, strike-to-cut). The Speech
// cleanup button proposes a pause/retake cutTrack; cutting words or applying a
// proposal edits plan.cutTrack — Re-render rebuilds the cut AND the captions.
export default function TranscriptPanel(props: Props) {
  const { srtPath, dir, cutTrack, currentTime, onSeek, onCutRanges, onRestoreRanges, onApplyCutTrack, onWarning, locked } =
    props;
  const [mode, setMode] = useState<"captions" | "script">("captions");

  const tab = (id: "captions" | "script", label: string) => (
    <button
      type="button"
      onClick={() => setMode(id)}
      className={`rounded px-1.5 py-px text-[10px] uppercase tracking-wide ${
        mode === id ? "bg-neutral-800 text-neutral-100" : "text-neutral-500 hover:text-neutral-300"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex shrink-0 flex-wrap items-center gap-1.5">
        {tab("captions", "Captions")}
        {tab("script", "Script")}
        <div className="ml-auto min-w-0">
          <SpeechCleanup dir={dir} onApply={onApplyCutTrack} onWarning={onWarning} locked={locked} />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        {mode === "captions" ? (
          <CaptionCues srtPath={srtPath} currentTime={currentTime} onSeek={onSeek} />
        ) : (
          <ScriptWords
            dir={dir}
            cutTrack={cutTrack}
            currentTime={currentTime}
            onSeek={onSeek}
            onCutRanges={onCutRanges}
            onRestoreRanges={onRestoreRanges}
            locked={locked}
          />
        )}
      </div>

      <p className="mt-2 shrink-0 border-t border-neutral-800 pt-2 text-[10px] leading-snug text-neutral-600">
        Cut words → Render updated video rebuilds the cut and regenerates matching captions (it&apos;s the
        same transcript).
      </p>
    </div>
  );
}
