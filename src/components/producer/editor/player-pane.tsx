"use client";

import { useState, type RefObject } from "react";
import { dlog } from "@/lib/debug";
import {
  previewAuthorityMessage,
  type PreviewAuthority,
} from "@/lib/producer/editor-preview-authority";

interface Props {
  videoRef: RefObject<HTMLVideoElement | null>;
  videoPath: string; // full-res deliverable (final.mp4)
  proxyPath: string; // derived preview (final.proxy.mp4, written by assemble)
  vVersion: number; // bumped per re-render → cache-bust + retry the proxy
  previewAuthority: PreviewAuthority;
  onTime: (t: number) => void;
  onDuration: (d: number) => void;
  children?: React.ReactNode; // overlays over the video box (e.g. the live graphic preview)
}

// The editor's video pane. PREFERS the proxy (fast scrubbing) through the same
// /api/clipper/video streamer and falls back to full-res via onError — an
// acceptable player-source fallback: the proxy is derived, full-res remains
// the deliverable + Reveal target. A badge marks proxy playback so the
// operator knows scrub quality ≠ deliverable quality.
//
// Both flags are DERIVED against the current version (no reset effects): a new
// vVersion invalidates the stored fallback (retry the proxy — a fresh
// re-render may have rewritten it) and the stored ready mark.
export default function PlayerPane({
  videoRef,
  videoPath,
  proxyPath,
  vVersion,
  previewAuthority,
  onTime,
  onDuration,
  children,
}: Props) {
  const [fallbackV, setFallbackV] = useState<number | null>(null); // vVersion whose proxy 404'd
  const [readySrc, setReadySrc] = useState<string | null>(null); // key of the loaded source
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const hasDistinctProxy = Boolean(proxyPath && proxyPath !== videoPath);
  const playable = previewAuthority === "current" || previewAuthority === "unapproved";
  const useProxy = hasDistinctProxy && fallbackV !== vVersion;
  const sourceKey = `${previewAuthority}:${vVersion}:${attempt}:${useProxy ? "proxy" : "full"}`;
  const ready = readySrc === sourceKey;
  const failed = failedSrc === sourceKey;

  const playerPath = useProxy ? proxyPath : videoPath;
  const src = playable
    ? `/api/clipper/video?path=${encodeURIComponent(playerPath)}&v=${vVersion}&attempt=${attempt}`
    : undefined;
  const retry = () => {
    setFallbackV(null);
    setFailedSrc(null);
    setReadySrc(null);
    setAttempt((n) => n + 1);
  };

  return (
    <div className="relative flex min-w-0 flex-1 items-center justify-center bg-black p-4">
      <video
        key={sourceKey}
        ref={videoRef}
        src={src}
        controls
        aria-label="Rendered video preview"
        onTimeUpdate={(e) => onTime(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => {
          setReadySrc(sourceKey);
          setFailedSrc(null);
          onDuration(e.currentTarget.duration);
        }}
        onError={() => {
          if (useProxy) {
            dlog("producer:editor", "proxy preview unavailable — falling back to final.mp4");
            setFallbackV(vVersion);
            return;
          }
          dlog("producer:editor", "full video preview unavailable", { videoPath });
          setFailedSrc(sourceKey);
        }}
        className={`max-h-full max-w-full rounded ${playable ? "" : "invisible"}`}
      />
      {!playable && (
        <div
          className="absolute inset-4 z-20 flex flex-col items-center justify-center rounded border border-amber-500/30 bg-neutral-950 px-6 text-center"
          role="status"
          aria-live="polite"
        >
          <p className="text-sm font-medium text-amber-200">
            {previewAuthority === "checking" ? "Verifying preview" : "Video needs an approved render"}
          </p>
          <p className="mt-1 max-w-md text-xs leading-relaxed text-neutral-400">
            {previewAuthorityMessage(previewAuthority)}
          </p>
        </div>
      )}
      {previewAuthority === "unapproved" && (
        <div className="absolute inset-x-6 top-6 z-20 rounded border border-amber-500/40 bg-neutral-950/90 px-3 py-2 text-center shadow-lg">
          <p className="text-xs font-medium text-amber-200">Unapproved review copy</p>
          <p className="mt-0.5 text-[10px] text-neutral-400">{previewAuthorityMessage(previewAuthority)}</p>
        </div>
      )}
      {playable && useProxy && ready && proxyPath !== videoPath && (
        <span
          className="absolute right-6 top-6 rounded bg-neutral-900/80 px-1.5 py-0.5 text-[10px] text-neutral-400"
          title="playing final.proxy.mp4 — scrub quality ≠ deliverable quality; Reveal targets the full-res final.mp4"
        >
          proxy preview
        </span>
      )}
      {playable && failed && (
        <div
          className="absolute inset-4 z-20 flex flex-col items-center justify-center rounded border border-rose-500/30 bg-neutral-950/95 px-6 text-center"
          role="alert"
        >
          <p className="text-sm font-medium text-rose-200">Video preview unavailable</p>
          <p className="mt-1 max-w-md text-xs leading-relaxed text-neutral-400">
            {hasDistinctProxy
              ? "Neither the fast preview nor the full-quality video could be loaded."
              : "The rendered video could not be loaded."}{" "}
            The file may be missing or incomplete. Choose Render updated video, or retry after checking the file.
          </p>
          <button
            onClick={retry}
            className="mt-3 rounded border border-neutral-600 px-3 py-1 text-xs text-neutral-100 hover:bg-neutral-800"
          >
            Retry preview
          </button>
        </div>
      )}
      {previewAuthority === "current" ? children : null}
    </div>
  );
}
