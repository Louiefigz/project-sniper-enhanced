"use client";

import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import type { GraphicEntry } from "@/lib/producer/edit-plan";
import {
  contentBBoxFrom,
  dragPlacement,
  inSafeRect,
  isShortsCanvas,
  previewTransform,
  type ContentBBox,
  type Placement,
  type SnappedPlacement,
  type SnappedScale,
} from "@/lib/producer/placement-geometry";
import SafeZoneGuides from "./safe-zone-guides";
import ScaleHandles from "./scale-handles";
import { parseDims, useCompHtml, useContentOrigin } from "./use-comp-html";

// INSTANT GRAPHICS PREVIEW — client-preview / server-truth. While a graphic is
// selected and the playhead sits inside its [outStart, outEnd) window (or the
// properties panel forces preview), a sandboxed srcdoc iframe overlays the
// player pane with the comp's LIVE HTML (served by /api/producer/comp-html with
// the spec injected exactly like graphics_render.py's --variables). Every
// timeupdate posts {type:"hf-seek", t: currentTime - outStart} so the comp's
// registered window.__timelines play in lockstep with the video — no re-render.
//
// DRAG-TO-PLACE: a NON-own-screen graphic's preview is draggable (pointer
// capture on the wrapper; the iframe stays pointer-events:none). `placement`
// is the point where the comp's rendered CONTENT top-left lands (the
// compositor pins the measured alpha bbox there — graphics_stage.
// _explicit_offset), so the preview measures the comp's painted-content
// origin in-iframe (useContentOrigin) and translates the canvas by
// (placement − origin); drags are disabled until the origin is known so a
// commit can never record canvas-translate coordinates. The pointer delta
// converts video-display px → comp-canvas px (placement-geometry, pure),
// live-moves the overlay, and the release commits `placement {x, y}` in ONE
// mutatePlan (undo = the whole gesture). Corner grips (scale-handles.tsx)
// scale the comp uniformly about the placement pin and commit
// `placement.scale` the same way. Double-click resets to auto (deletes
// placement — scale included → anchor fallback). On the shorts canvas the SAFE_BOX guides show
// while dragging, the point soft-snaps to the safe edges (Alt disables), and an
// unsafe release raises the editor's amber warning strip. The render pipeline
// stays the truth: this is labelled PREVIEW, and free-band comps without a
// resolved placement carry an "approximate placement" hint (the compositor may
// still offset them face-relative at render time; a placed one is accurate to
// the comp's soft-shadow margin — layout rects exclude what the alpha probe
// includes).

interface Props {
  graphic: GraphicEntry;
  currentTime: number;
  videoRef: RefObject<HTMLVideoElement | null>;
  forced: boolean; // the properties panel's Preview toggle — show even outside the window
  /**
   * Release → ONE commit; null = reset to auto (clears scale too); unsafe =
   * outside the shorts SAFE_BOX. Move commits preserve the committed scale;
   * corner-grip commits carry the new scale (omitted when exactly 1).
   * `contentBBox` = the in-iframe measured painted-content bbox (comp-canvas
   * px, unscaled) stamped onto the entry with the placement so the plan
   * lint's SAFE_BOX check has a real box (v3 item #6e); null = unmeasured
   * (the commit leaves any previous stamp untouched).
   */
  onCommitPlacement: (
    p: (Placement & { scale?: number }) | null,
    unsafe: boolean,
    contentBBox?: ContentBBox | null,
  ) => void;
}

interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

interface Gesture {
  pointerId: number;
  originX: number;
  originY: number;
  base: Placement; // committed placement at pointerdown ({0,0} when auto)
  live: SnappedPlacement | null; // null until the 3px threshold — a click, not a drag
}

/**
 * The video element's layout box relative to the player pane (both the <video>
 * and this overlay share PlayerPane's `relative` root, so offset* is the local
 * geometry). Polled at 500ms + on resize — survives the vVersion remount of
 * the <video> without holding a stale element reference.
 */
function useVideoBox(videoRef: RefObject<HTMLVideoElement | null>, active: boolean): Box | null {
  const [box, setBox] = useState<Box | null>(null);
  useEffect(() => {
    if (!active) return;
    const measure = () => {
      const v = videoRef.current;
      if (!v || !v.offsetWidth || !v.offsetHeight) return;
      const next = { left: v.offsetLeft, top: v.offsetTop, width: v.offsetWidth, height: v.offsetHeight };
      setBox((prev) =>
        prev &&
        prev.left === next.left &&
        prev.top === next.top &&
        prev.width === next.width &&
        prev.height === next.height
          ? prev
          : next,
      );
    };
    measure();
    const timer = setInterval(measure, 500);
    window.addEventListener("resize", measure);
    return () => {
      clearInterval(timer);
      window.removeEventListener("resize", measure);
    };
  }, [videoRef, active]);
  return active ? box : null;
}

export default function GraphicPreview({ graphic, currentTime, videoRef, forced, onCommitPlacement }: Props) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [gesture, setGesture] = useState<Gesture | null>(null);
  const [liveScale, setLiveScale] = useState<SnappedScale | null>(null); // corner-grip gesture
  const inWindow = currentTime >= graphic.outStart && currentTime < graphic.outEnd;
  const visible = forced || inWindow;
  const durationS = Math.max(0.1, Math.round((graphic.outEnd - graphic.outStart) * 100) / 100);
  const specJson = useMemo(() => JSON.stringify(graphic.spec ?? {}), [graphic.spec]);
  const { html, err } = useCompHtml(graphic.kind, specJson, durationS, visible);
  const box = useVideoBox(videoRef, visible);
  const dims = useMemo(() => parseDims(html), [html]);
  // Painted-content origin + unscaled bbox size (canvas px) — the point the
  // compositor pins at `placement` and the box the corner grips scale.
  // Measured in-iframe after load; drags wait for it.
  const { origin, size, requestMeasure } = useContentOrigin(iframeRef, html, durationS);

  const seekNow = () => {
    const w = iframeRef.current?.contentWindow;
    if (!w) return;
    const t = Math.min(Math.max(currentTime - graphic.outStart, 0), durationS);
    w.postMessage({ type: "hf-seek", t }, "*");
  };
  // Drive the comp's timeline from playback time on every timeupdate/scrub.
  // `origin` is a dep so the measure probes' settled-frame seeks are undone
  // the moment the measurement lands.
  useEffect(seekNow, [visible, html, currentTime, graphic.outStart, durationS, origin]);

  if (!visible || !box) return null;

  const ownScreen = graphic.anchor === "own-screen"; // full-frame — never draggable/placed
  const placement = graphic.placement;
  const placed = typeof placement?.x === "number" && typeof placement?.y === "number";
  const scaleX = box.width / dims.w;
  const scaleY = box.height / dims.h;
  const shorts = isShortsCanvas(dims);
  const draggable = !ownScreen && !!html && !err && origin !== null;
  const approx = !ownScreen && (!placed || !origin) && !gesture?.live;
  // While dragging, the overlay follows the LIVE (converted+snapped) placement.
  // A corner-grip gesture on an UNPLACED comp pins at the measured origin.
  const committedScale = placement?.scale ?? 1;
  const effScale = liveScale?.s ?? committedScale;
  const liveP: Placement | null =
    gesture?.live?.p ??
    (placed ? { x: placement.x, y: placement.y } : liveScale && origin ? origin : null);
  // The iframe transform honors placement as a CONTENT pin at any scale:
  // content sits at `origin` in the authored canvas, so the canvas scales by
  // `s` about its own origin and moves by (placement − s·origin) — exactly
  // the renderer's pin. Pre-measure (origin null) a placed comp falls back to
  // a raw-placement translate — the `approx` hint stays up until it lands.
  const t = previewTransform(liveP, origin, liveP ? effScale : 1);

  const down = (e: React.PointerEvent) => {
    if (!draggable || !origin) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    setGesture({
      pointerId: e.pointerId,
      originX: e.clientX,
      originY: e.clientY,
      // The gesture drags the CONTENT point: an unplaced comp's content
      // currently sits at its measured origin.
      base: placed ? { x: placement.x, y: placement.y } : { x: origin.x, y: origin.y },
      live: null,
    });
  };
  const move = (e: React.PointerEvent) => {
    if (!gesture || e.pointerId !== gesture.pointerId) return;
    const dxPx = e.clientX - gesture.originX;
    const dyPx = e.clientY - gesture.originY;
    if (!gesture.live && Math.hypot(dxPx, dyPx) < 3) return; // click, not a drag (yet)
    setGesture({ ...gesture, live: dragPlacement({ base: gesture.base, dxPx, dyPx, canvas: dims, box, snap: !e.altKey }) });
  };
  const end = (e: React.PointerEvent, cancel = false) => {
    if (!gesture || e.pointerId !== gesture.pointerId) return;
    if (gesture.live && !cancel) {
      // ONE mutatePlan per gesture — a move commit PRESERVES the committed scale.
      const p = { ...gesture.live.p, ...(committedScale !== 1 ? { scale: committedScale } : {}) };
      onCommitPlacement(p, shorts && !inSafeRect(gesture.live.p, dims), contentBBoxFrom(origin, size));
    }
    setGesture(null);
  };
  // Corner-grip release → ONE commit: the pin stays put (placement, or the
  // measured origin when the comp was unplaced), only `scale` changes; exactly
  // 1 drops the key (absent = 1.0 byte-identical). Net-zero gestures (already
  // at the committed scale, or unplaced back at 100%) skip the commit — a
  // no-op must not push a phantom undo step.
  const pin: Placement | null = placed ? { x: placement.x, y: placement.y } : origin;
  const commitScale = (s: SnappedScale) => {
    if (!pin || (placed && s.s === committedScale) || (!placed && s.s === 1)) return;
    const p = { x: Math.round(pin.x), y: Math.round(pin.y), ...(s.s !== 1 ? { scale: s.s } : {}) };
    onCommitPlacement(p, shorts && !inSafeRect(p, dims), contentBBoxFrom(origin, size));
  };

  return (
    <div
      className={`absolute select-none overflow-hidden rounded ${
        draggable ? `touch-none ${gesture?.live ? "cursor-grabbing" : "cursor-grab"}` : "pointer-events-none"
      }`}
      style={{ left: box.left, top: box.top, width: box.width, height: box.height }}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={(e) => end(e)}
      onPointerCancel={(e) => end(e, true)}
      onDoubleClick={() => draggable && placed && onCommitPlacement(null, false)}
      title={
        draggable
          ? "drag to place (Alt = no snap) · double-click = auto position"
          : !ownScreen && html && !err
            ? "measuring comp content…"
            : undefined
      }
    >
      {html && !err && (
        <iframe
          ref={iframeRef}
          sandbox="allow-scripts"
          srcDoc={html}
          onLoad={() => {
            requestMeasure(); // settled-frame probes; origin arrival re-seeks
            seekNow();
          }}
          title={`preview: ${graphic.kind}`}
          style={{
            width: dims.w,
            height: dims.h,
            border: 0,
            pointerEvents: "none", // the wrapper owns the drag; iframes swallow pointers
            transform: `translate(${t.x * scaleX}px, ${t.y * scaleY}px) scale(${scaleX * t.s}, ${scaleY * t.s})`,
            transformOrigin: "0 0",
            background: "transparent",
          }}
        />
      )}
      {draggable && size && pin && (
        <ScaleHandles
          pin={gesture?.live?.p ?? pin}
          content={size}
          scale={effScale}
          base={committedScale}
          canvas={dims}
          box={box}
          onLive={setLiveScale}
          onCommit={commitScale}
        />
      )}
      {gesture?.live && shorts && <SafeZoneGuides canvas={dims} box={box} />}
      {gesture?.live && (
        <span className="pointer-events-none absolute left-1/2 top-1.5 z-10 -translate-x-1/2 whitespace-nowrap rounded border border-neutral-700 bg-neutral-950/95 px-1.5 py-0.5 text-[10px] text-neutral-100">
          x {gesture.live.p.x}
          {gesture.live.snappedX && <span className="text-amber-300">⌁</span>} · y {gesture.live.p.y}
          {gesture.live.snappedY && <span className="text-amber-300">⌁</span>}
          <span className="text-neutral-500"> canvas px</span>
        </span>
      )}
      <span className="pointer-events-none absolute left-1.5 top-1.5 rounded bg-neutral-950/70 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-neutral-300">
        preview{forced && !inWindow ? " · outside window" : ""}
      </span>
      {approx && (
        <span className="pointer-events-none absolute bottom-1.5 left-1.5 rounded bg-neutral-950/70 px-1.5 py-0.5 text-[9px] text-amber-300/90">
          approximate placement — drag to place, render for truth
        </span>
      )}
      {err && (
        <span className="pointer-events-none absolute bottom-1.5 right-1.5 rounded bg-rose-950/80 px-1.5 py-0.5 text-[10px] text-rose-300">
          preview failed: {err}
        </span>
      )}
    </div>
  );
}
