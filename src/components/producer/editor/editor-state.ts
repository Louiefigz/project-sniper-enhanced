"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { planDuration, type EditPlan } from "@/lib/producer/edit-plan";
import type { PalmierView } from "./palmier-bar";

export interface EditorPaths {
  base: string;
  videoPath: string;
  proxyPath: string;
  planPath: string;
  srtPath: string;
}

export interface DragWindow {
  id: string;
  start: number;
  end: number;
}

export function editorPaths(dir: string): EditorPaths {
  const base = dir.replace(/\/$/, "");
  return {
    base,
    videoPath: `${base}/final.mp4`,
    proxyPath: `${base}/final.proxy.mp4`,
    planPath: `${base}/edit_plan.json`,
    srtPath: `${base}/captions.srt`,
  };
}

export function useEditorPlayback(initialPlan: EditPlan) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const timeRef = useRef(0);
  const [duration, setDuration] = useState(planDuration(initialPlan));
  const durationRef = useRef(duration);

  const onTime = useCallback((time: number) => {
    timeRef.current = time;
    setCurrentTime(time);
  }, []);
  useEffect(() => {
    durationRef.current = duration;
  }, [duration]);
  const seek = useCallback((time: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = Math.max(0, Math.min(time, duration || video.duration || time));
    onTime(video.currentTime);
  }, [duration, onTime]);

  return { videoRef, currentTime, timeRef, duration, durationRef, setDuration, onTime, seek };
}

export function useEditorUiState() {
  const [selected, setSelected] = useState<string | null>(null);
  const [previewForced, setPreviewForced] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [dragWindow, setDragWindow] = useState<DragWindow | null>(null);
  const [askPrefill, setAskPrefill] = useState<{ text: string; nonce: number } | null>(null);
  const [railRequest, setRailRequest] = useState<{ id: "elements"; nonce: number } | null>(null);
  const [palmierView, setPalmierView] = useState<PalmierView>("internal");
  const [palmierVersion, setPalmierVersion] = useState(0);

  return {
    selected, setSelected, previewForced, setPreviewForced, aiBusy, setAiBusy,
    dragWindow, setDragWindow, askPrefill, setAskPrefill, railRequest, setRailRequest,
    palmierView, setPalmierView, palmierVersion, setPalmierVersion,
  };
}
