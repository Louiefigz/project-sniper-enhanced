"use client";

import { AlertTriangle, FileJson, FileText, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { KeptFrameInfo } from "@/lib/frameio/types";
import { ReviewRunState } from "./review-run-state";

interface ReviewStatusPanelProps {
  state: ReviewRunState;
  onRun: (confirmed: boolean) => void;
}

function frameUrl(thumb: string) {
  return `/api/frameio-review/frame?path=${encodeURIComponent(thumb)}`;
}

function isRunning(state: ReviewRunState) {
  return state.phase === "extracting" || state.phase === "deduping" || state.phase === "analyzing";
}

export function ReviewStatusPanel({ state, onRun }: ReviewStatusPanelProps) {
  const running = isRunning(state);
  return (
    <div className="rounded-lg border border-border bg-card/50 p-4">
      <div className="flex items-center gap-2">
        {running && <Loader2 className="size-4 animate-spin text-signal" />}
        <span aria-live="polite" className="text-sm text-foreground">
          {state.statusLine}
        </span>
      </div>
      <ProgressDetails state={state} />
      {state.phase === "needs_confirm" && (
        <ConfirmPanel
          estimate={state.estimate ?? 0}
          keptFrames={state.keptFrames}
          onProceed={() => onRun(true)}
        />
      )}
      {state.phase === "error" && <ReviewError error={state.error} onRetry={() => onRun(false)} />}
      {state.failures > 0 && state.phase === "done" && (
        <p className="mt-2 text-xs text-amber-400/90">
          {state.failures} frame(s) failed after retries and were skipped.
        </p>
      )}
      {state.saved && <SavedResults saved={state.saved} />}
    </div>
  );
}

function ProgressDetails({ state }: { state: ReviewRunState }) {
  const extraction = state.extractProgress;
  const analysis = state.analyzeProgress;
  const extractPercent = extraction.total ? (extraction.done / extraction.total) * 100 : 0;
  const analyzePercent = analysis.total ? (analysis.done / analysis.total) * 100 : 0;
  if (state.phase === "extracting" && extraction.total > 0) {
    return <Progress value={extractPercent} className="mt-3" />;
  }
  const showAnalysis = state.phase === "analyzing" || (state.phase === "done" && analysis.total > 0);
  if (!showAnalysis) return null;
  return (
    <div className="mt-3">
      <Progress value={analyzePercent} className="mb-1" />
      <div className="label text-muted-foreground/70">
        {analysis.done}/{analysis.total} frames · {state.flags.length} possible issue(s)
      </div>
    </div>
  );
}

function ConfirmPanel({
  estimate,
  keptFrames,
  onProceed,
}: {
  estimate: number;
  keptFrames: KeptFrameInfo[];
  onProceed: () => void;
}) {
  return (
    <div className="mt-3 rounded-md border border-amber-500/30 bg-amber-500/5 p-3">
      <p className="text-sm font-semibold text-amber-400">Review paused — approval needed</p>
      <p className="text-sm text-foreground">
        The scan selected <span className="font-semibold text-amber-400">{estimate}</span>{" "}
        images for AI review, which is over the safety limit. Nothing is running while this is
        paused. Check the images below, then choose whether to continue.
      </p>
      {keptFrames.length > 0 && <KeptFramePreview frames={keptFrames} />}
      <Button onClick={onProceed} size="sm" className="mt-3">
        Approve and continue review
      </Button>
    </div>
  );
}

function KeptFramePreview({ frames }: { frames: KeptFrameInfo[] }) {
  return (
    <div className="mt-3 flex max-h-28 flex-wrap gap-1.5 overflow-y-auto">
      {frames.slice(0, 40).map((frame) => (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          key={frame.index}
          src={frameUrl(frame.thumb)}
          alt=""
          title={`${frame.t_start}s`}
          className="h-10 w-16 rounded border border-border object-cover"
        />
      ))}
    </div>
  );
}

function ReviewError({ error, onRetry }: { error: string | null; onRetry: () => void }) {
  return (
    <div role="alert" className="mt-3 rounded-md border border-destructive/40 bg-destructive/5 p-3">
      <p className="flex items-start gap-2 text-sm font-medium text-destructive">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
        Review stopped before it could finish
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        {error || "An unexpected error stopped the review."} Your video was not changed.
      </p>
      <Button onClick={onRetry} size="sm" className="mt-3">
        Retry text review
      </Button>
    </div>
  );
}

function SavedResults({ saved }: { saved: { results: string; report: string } }) {
  return (
    <div className="mt-3 space-y-1 border-t border-border pt-3">
      <div className="label text-muted-foreground/70">Saved next to your video</div>
      <SavedPath icon={<FileJson className="size-3.5" />} path={saved.results} />
      <SavedPath icon={<FileText className="size-3.5" />} path={saved.report} />
    </div>
  );
}

function SavedPath({ icon, path }: { icon: React.ReactNode; path: string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span className="text-signal">{icon}</span>
      <code className="truncate">{path}</code>
    </div>
  );
}
