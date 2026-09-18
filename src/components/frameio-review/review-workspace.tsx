"use client";

import { RefObject, useCallback, useRef } from "react";
import { ReviewConfig } from "@/lib/frameio/types";
import { ReviewDiagnostics } from "./review-diagnostics";
import { ReviewFindings } from "./review-findings";
import { ReviewRunState } from "./review-run-state";
import { ReviewStatusPanel } from "./review-status-panel";
import { useReviewRun } from "./use-review-run";

interface ReviewWorkspaceProps {
  filePath: string;
  fileName: string | null;
  config: ReviewConfig;
}

interface PlayerColumnProps {
  filePath: string;
  videoRef: RefObject<HTMLVideoElement | null>;
  state: ReviewRunState;
  logs: ReturnType<typeof useReviewRun>["logs"];
  onRun: (confirmed: boolean) => void;
}

export default function ReviewWorkspace({ filePath, fileName, config }: ReviewWorkspaceProps) {
  const review = useReviewRun({ filePath, fileName, config });
  const videoRef = useRef<HTMLVideoElement>(null);
  const seekTo = useCallback((timestamp: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = timestamp;
    video.pause();
    video.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, []);
  return (
    <div className="rise-in">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <PlayerColumn
          filePath={filePath}
          videoRef={videoRef}
          state={review}
          logs={review.logs}
          onRun={review.run}
        />
        <ReviewFindings flags={review.flags} phase={review.phase} onSeek={seekTo} />
      </div>
    </div>
  );
}

function PlayerColumn({ filePath, videoRef, state, logs, onRun }: PlayerColumnProps) {
  return (
    <div className="space-y-4">
      <video
        ref={videoRef}
        src={`/api/frameio-review/video?path=${encodeURIComponent(filePath)}`}
        controls
        className="w-full rounded-lg border border-border bg-black"
      />
      <ReviewStatusPanel state={state} onRun={onRun} />
      <ReviewDiagnostics logs={logs} />
    </div>
  );
}
