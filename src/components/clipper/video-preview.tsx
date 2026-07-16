"use client";

import type { RefObject } from "react";

interface VideoPreviewProps {
  videoSrc: string;
  videoRef: RefObject<HTMLVideoElement | null>;
  onPlay: () => void;
  onPause: () => void;
}

export function VideoPreview({ videoSrc, videoRef, onPlay, onPause }: VideoPreviewProps) {
  return (
    <div className="w-[38%] shrink-0 sticky top-0 self-start space-y-2">
      <video ref={videoRef} src={videoSrc} controls className="w-full rounded-lg bg-black" />
      <button onClick={() => onPlay()}
        className="w-full py-2 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-sm font-semibold transition-colors">
        ▶ Play Clip
      </button>
      <button onClick={() => onPause()}
        className="w-full py-2 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-neutral-300 text-sm font-semibold transition-colors">
        ⏸ Pause
      </button>
    </div>
  );
}
