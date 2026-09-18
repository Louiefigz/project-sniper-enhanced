"use client";

import { useLiveBuildController } from "./use-live-build";

function statusMessage(message: string, error?: string): string {
  return message || error || "";
}

export default function LiveBuildControls({
  dir,
  disabled,
  onChanged,
}: {
  dir: string;
  disabled: boolean;
  onChanged: () => void;
}) {
  const live = useLiveBuildController(dir, onChanged);
  const { state, working, message, operations, expanded } = live;
  const resumable = state && state.status !== "complete";
  const status = statusMessage(message, state?.error);
  return (
    <span className="relative flex items-center gap-1">
      <button type="button" disabled={disabled || working}
        onClick={() => void live.start()}
        title="Build a visible editable candidate from the approved plan, then export and QC that exact timeline before promotion."
        className="rounded border border-violet-700 px-2 py-0.5 text-violet-300 disabled:cursor-not-allowed disabled:opacity-40">
        {working ? "Building live…" : state?.status === "complete"
          ? "Build current approved plan" : resumable ? "Resume live build" : "Build live in Palmier"}
      </button>
      {working && (
        <button type="button" onClick={live.stop}
          className="rounded border border-neutral-700 px-2 py-0.5 text-neutral-300">
          Stop & keep candidate
        </button>
      )}
      {(status || operations.length > 0) && (
        <button type="button" onClick={() => live.setExpanded(!expanded)}
          className="max-w-80 truncate text-left text-neutral-400" title={status}>
          {status || `${operations.length} Palmier operations`}
        </button>
      )}
      {expanded && operations.length > 0 && (
        <span className="absolute left-0 top-7 z-30 w-96 rounded border border-neutral-700 bg-neutral-950 p-2 shadow-xl">
          {operations.map((row) => (
            <span key={row.id} className="flex justify-between gap-3 py-0.5 text-neutral-300">
              <span className="truncate">{row.summary}</span>
              <span className={row.status === "failed" ? "text-red-400" : "text-neutral-500"}>
                {row.status}
              </span>
            </span>
          ))}
        </span>
      )}
    </span>
  );
}
