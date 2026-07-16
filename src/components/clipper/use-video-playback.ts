"use client";

import { useCallback, useEffect, useRef } from "react";
import type { MutableRefObject, RefObject } from "react";
import type { PlaybackControls, TimeClip } from "./video-editor-types";

const PLAYBACK_TOLERANCE = 0.05;

function stopPlayback(video: HTMLVideoElement, boundary: MutableRefObject<number | null>): void {
  video.pause();
  boundary.current = null;
}

function skipRemovedRegion(
  video: HTMLVideoElement,
  boundary: MutableRefObject<number | null>,
  clips: TimeClip[],
  time: number,
): boolean {
  if (!clips.length) return false;
  const insideClip = clips.some((clip) =>
    time >= clip.start - PLAYBACK_TOLERANCE && time < clip.end + PLAYBACK_TOLERANCE,
  );
  if (insideClip) return false;
  const next = clips.find((clip) => clip.start > time + PLAYBACK_TOLERANCE);
  if (!next) {
    stopPlayback(video, boundary);
    return true;
  }
  const end = boundary.current;
  if (end !== null && next.start >= end - PLAYBACK_TOLERANCE) {
    stopPlayback(video, boundary);
    return true;
  }
  video.currentTime = next.start;
  return false;
}

function tickPlayback(
  video: HTMLVideoElement,
  boundary: MutableRefObject<number | null>,
  playableClips: MutableRefObject<TimeClip[]>,
): void {
  if (video.paused) return;
  const time = video.currentTime;
  if (skipRemovedRegion(video, boundary, playableClips.current, time)) return;
  const end = boundary.current;
  if (end !== null && time >= end - PLAYBACK_TOLERANCE) {
    stopPlayback(video, boundary);
  }
}

function usePlaybackLoop(
  videoRef: RefObject<HTMLVideoElement | null>,
  onFrame: (video: HTMLVideoElement) => void,
  onNativePlay: () => void,
): void {
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let frameId = 0;
    const tick = () => {
      onFrame(video);
      frameId = requestAnimationFrame(tick);
    };
    const onPlay = () => {
      onNativePlay();
      cancelAnimationFrame(frameId);
      frameId = requestAnimationFrame(tick);
    };
    const onPause = () => cancelAnimationFrame(frameId);
    video.addEventListener("play", onPlay);
    video.addEventListener("pause", onPause);
    return () => {
      video.removeEventListener("play", onPlay);
      video.removeEventListener("pause", onPause);
      cancelAnimationFrame(frameId);
    };
  }, [onFrame, onNativePlay, videoRef]);
}

export function useVideoPlayback(keptClips: TimeClip[]): PlaybackControls {
  const videoRef = useRef<HTMLVideoElement>(null);
  const boundary = useRef<number | null>(null);
  const keptClipsRef = useRef<TimeClip[]>([]);
  const playableClips = useRef<TimeClip[]>([]);
  useEffect(() => {
    keptClipsRef.current = keptClips;
    if (boundary.current === null) playableClips.current = keptClips;
  }, [keptClips]);
  const playRange = useCallback((start: number, end: number, clips?: TimeClip[]) => {
    const video = videoRef.current;
    if (!video) return;
    boundary.current = end;
    playableClips.current = clips ?? keptClipsRef.current;
    video.currentTime = Math.max(0, start);
    video.play().catch(() => {});
  }, []);
  const playCurrentSegment = useCallback((fromTime?: number) => {
    const clips = keptClipsRef.current;
    const remaining = fromTime == null ? clips : clips.filter((clip) => clip.end > fromTime);
    const start = fromTime == null ? (clips[0]?.start ?? 0) : Math.max(fromTime, remaining[0]?.start ?? fromTime);
    const end = clips[clips.length - 1]?.end ?? 0;
    if (start < end) playRange(start, end, remaining.length ? remaining : clips);
  }, [playRange]);
  const seekTo = useCallback((time: number) => {
    if (videoRef.current) videoRef.current.currentTime = Math.max(0, time);
  }, []);
  const pause = useCallback(() => {
    if (videoRef.current) stopPlayback(videoRef.current, boundary);
  }, []);
  const togglePlayback = useCallback((fromTime?: number) => {
    if (videoRef.current?.paused === false) pause();
    else playCurrentSegment(fromTime);
  }, [pause, playCurrentSegment]);
  const onFrame = useCallback((video: HTMLVideoElement) => {
    tickPlayback(video, boundary, playableClips);
  }, []);
  const onNativePlay = useCallback(() => {
    if (boundary.current === null) playableClips.current = keptClipsRef.current;
  }, []);
  usePlaybackLoop(videoRef, onFrame, onNativePlay);
  return { videoRef, playCurrentSegment, playRange, seekTo, pause, togglePlayback };
}
