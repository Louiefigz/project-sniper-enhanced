"use client";

// Live status panel under the multicam export button — extracted verbatim from
// segment-export-step.tsx (presentation only; all state stays in the step).

export interface SegmentResult {
  index: number;
  available: string[];
  error?: string;
}

export interface MulticamPanelState {
  loading: boolean;
  status: string;
  error: string | null;
  validation: string | null;
  offsetB: number | null;
  offsetC: number | null;
  offsetLav1: number | null;
  offsetLav2: number | null;
  segResults: SegmentResult[];
}

function sourceName(source: string): string {
  const key = source.toLowerCase();
  if (key === "a" || key === "acam") return "main video";
  if (key === "b" || key === "bcam") return "extra camera 1";
  if (key === "c" || key === "ccam") return "extra camera 2";
  if (key === "lav1") return "microphone 1";
  if (key === "lav2") return "microphone 2";
  return source;
}

export default function MulticamStatusPanel({ s }: { s: MulticamPanelState }) {
  const anyOffset =
    s.offsetB !== null || s.offsetC !== null || s.offsetLav1 !== null || s.offsetLav2 !== null;
  if (!(s.loading || s.status || s.error || s.validation || s.segResults.length > 0)) return null;
  return (
    <div className="mt-4 rounded-xl border border-neutral-800 bg-neutral-900/30 p-4 space-y-3">
      {s.status && (
        <div className="flex items-center gap-3">
          <div
            className={`w-2.5 h-2.5 rounded-full shrink-0 ${s.error ? "bg-red-500" : s.loading ? "bg-cyan-500 animate-pulse" : "bg-green-500"}`}
          />
          <span className="text-sm text-neutral-200 flex-1">{s.status}</span>
        </div>
      )}
      {anyOffset && (
        <div className="text-xs text-neutral-400 pl-5 flex flex-wrap gap-x-4 gap-y-1">
          {s.offsetB !== null && <span>Extra camera 1 adjustment: {s.offsetB.toFixed(3)}s</span>}
          {s.offsetC !== null && <span>Extra camera 2 adjustment: {s.offsetC.toFixed(3)}s</span>}
          {s.offsetLav1 !== null && <span>Microphone 1 adjustment: {s.offsetLav1.toFixed(3)}s</span>}
          {s.offsetLav2 !== null && <span>Microphone 2 adjustment: {s.offsetLav2.toFixed(3)}s</span>}
        </div>
      )}
      {s.segResults.length > 0 && (
        <div className="text-xs space-y-1 pl-5 max-h-40 overflow-y-auto">
          {s.segResults.map((r) => (
            <div key={r.index} className="flex items-center gap-2 font-mono">
              <span className="text-neutral-500 w-10">#{r.index + 1}</span>
              {r.error ? (
                <span className="text-amber-400">skipped — {r.error}</span>
              ) : (
                <span className="text-neutral-300">
                  {r.available.map(sourceName).join(" + ") || "No synchronized files"}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
      {s.validation && <p className="text-xs text-cyan-400/80 pl-5">{s.validation}</p>}
      {s.error && (
        <p role="alert" className="text-sm text-red-400 mt-2 p-3 bg-red-950/20 border border-red-900/30 rounded-lg">
          {s.error}
        </p>
      )}
    </div>
  );
}
