"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  fitPxPerSec,
  zoomAtCursor,
  type ZoomState,
} from "@/lib/producer/timeline-scale";

// Timeline zoom + scroll state. ONE px-per-second value feeds every lane, the
// ruler, and the playhead (the shared transform lives in timeline-scale.ts).
// userPps === null means "fit" — the zoom tracks the viewport until the
// operator zooms. Zoom-at-cursor writes scrollLeft through pendingScroll so it
// lands AFTER React has widened the content div (a plain el.scrollLeft write
// before the render would clamp against the old width).

export interface TimelineZoom {
  scrollRef: React.RefObject<HTMLDivElement | null>;
  viewportPx: number;
  scrollLeft: number;
  setScrollLeft: (px: number) => void;
  pps: number;
  fit: number;
  isFit: boolean;
  applyZoom: (z: ZoomState) => void;
  zoomToFit: () => void;
  sliderZoom: (targetPps: number) => void; // zoom keeping the viewport center fixed
}

export function useTimelineZoom(duration: number): TimelineZoom {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [viewportPx, setViewportPx] = useState(0);
  const [userPps, setUserPps] = useState<number | null>(null);
  const [scrollLeft, setScrollLeft] = useState(0);
  const pendingScroll = useRef<number | null>(null);

  const fit = viewportPx > 0 && duration > 0 ? fitPxPerSec(viewportPx, duration) : 1;
  const pps = userPps ?? fit;

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    setViewportPx(el.clientWidth);
    const ro = new ResizeObserver(() => setViewportPx(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Apply the zoom's scroll target after the content width has re-rendered.
  // The browser fires a scroll event for the programmatic write, so the
  // scrollLeft STATE syncs through the container's onScroll handler.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el || pendingScroll.current == null) return;
    el.scrollLeft = pendingScroll.current;
    pendingScroll.current = null;
  });

  const applyZoom = useCallback((z: ZoomState) => {
    setUserPps(z.pxPerSec);
    pendingScroll.current = z.scrollLeft;
  }, []);

  const zoomToFit = useCallback(() => {
    setUserPps(null);
    pendingScroll.current = 0;
  }, []);

  const stateRef = useRef({ pps, viewportPx, duration });
  useEffect(() => {
    stateRef.current = { pps, viewportPx, duration }; // wheel/slider handlers read the latest
  });

  const sliderZoom = useCallback(
    (targetPps: number) => {
      const s = stateRef.current;
      const el = scrollRef.current;
      if (!el || s.pps <= 0) return;
      applyZoom(
        zoomAtCursor(
          { pxPerSec: s.pps, scrollLeft: el.scrollLeft },
          s.viewportPx / 2,
          targetPps / s.pps,
          s.viewportPx,
          s.duration,
        ),
      );
    },
    [applyZoom],
  );

  // Wheel: ctrl/cmd-wheel (incl. trackpad pinch — it arrives as ctrl+wheel)
  // zooms centered on the cursor; a plain vertical wheel pans horizontally.
  // Native listener with passive:false — React's onWheel can't preventDefault.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      const s = stateRef.current;
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        const cursorX = e.clientX - el.getBoundingClientRect().left;
        applyZoom(
          zoomAtCursor(
            { pxPerSec: s.pps, scrollLeft: el.scrollLeft },
            cursorX,
            Math.exp(-e.deltaY * 0.008),
            s.viewportPx,
            s.duration,
          ),
        );
      } else if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
        e.preventDefault();
        el.scrollLeft += e.deltaY; // the scroll event syncs scrollLeft state
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [applyZoom]);

  return {
    scrollRef,
    viewportPx,
    scrollLeft,
    setScrollLeft,
    pps,
    fit,
    isFit: userPps === null,
    applyZoom,
    zoomToFit,
    sliderZoom,
  };
}
