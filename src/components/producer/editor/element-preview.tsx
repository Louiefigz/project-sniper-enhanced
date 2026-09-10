"use client";

import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
import type { CompCanvas, CompCatalogEntry } from "@/lib/producer/comps-catalog";
import { parseDims, parseRootDuration, useCompHtml } from "./use-comp-html";
import { usePreviewHealth } from "./use-preview-health";

// LIVE ELEMENT PREVIEW — the ELEMENTS panel's mini comp player. Every catalog
// comp registers a PAUSED GSAP timeline (window.__timelines) and never
// auto-plays, so a plain iframe would freeze on frame 0. Instead the panel owns
// ONE rAF loop (usePreviewLoop) that posts {type:"hf-seek", t} into every
// registered iframe with t = elapsed % (authored duration + a short end-pose
// hold) — the same hf-seek listener graphic-preview drives from playback time.
// Cards register only while IN VIEW (IntersectionObserver) and the drawer
// unmounts on close, so 12 iframes never animate in the background.

const HOLD_TAIL_S = 0.8; // rest on the comp's end pose before the loop restarts
const POST_INTERVAL_MS = 33; // ~30fps seek posts — plenty at preview size
const DEFAULT_DURATION_S = 4;

export interface PreviewLoop {
  register: (id: string, getWin: () => Window | null, duration: number) => void;
  unregister: (id: string) => void;
}

interface LoopEntry {
  getWin: () => Window | null;
  duration: number;
  startedAt: number;
}

/** One rAF driver for every live preview; idle (no scheduled frame) when empty. */
export function usePreviewLoop(): PreviewLoop {
  const loop = useRef<ReturnType<typeof createLoop> | null>(null);
  loop.current ??= createLoop();
  useEffect(() => {
    const l = loop.current;
    return () => l?.dispose();
  }, []);
  return loop.current;
}

function createLoop(): PreviewLoop & { dispose: () => void } {
  const entries = new Map<string, LoopEntry>();
  let raf = 0;
  let lastPost = 0;
  const tick = (now: number) => {
    raf = entries.size ? requestAnimationFrame(tick) : 0;
    if (now - lastPost < POST_INTERVAL_MS) return;
    lastPost = now;
    entries.forEach((e) => {
      const win = e.getWin();
      if (!win) return;
      const elapsed = (now - e.startedAt) / 1000;
      const t = Math.min(elapsed % (e.duration + HOLD_TAIL_S), e.duration);
      win.postMessage({ type: "hf-seek", t }, "*");
    });
  };
  return {
    register(id, getWin, duration) {
      entries.set(id, { getWin, duration, startedAt: performance.now() });
      if (!raf) raf = requestAnimationFrame(tick);
    },
    unregister(id) {
      entries.delete(id);
    },
    dispose() {
      cancelAnimationFrame(raf);
      raf = 0;
      entries.clear();
    },
  };
}

/** In-view flag (drives the loop) + a sticky "seen" latch (lazy iframe mount). */
function useInView(ref: RefObject<HTMLDivElement | null>) {
  const [inView, setInView] = useState(false);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => {
        setInView(e.isIntersecting);
        if (e.isIntersecting) setSeen(true);
      },
      { threshold: 0.15 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [ref]);
  return { inView, seen };
}

/** The wrapper's layout width — the drawer is fixed-width, the showcase is not. */
function useWidth(ref: RefObject<HTMLDivElement | null>): number {
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return width;
}

interface PreviewProps {
  kind: string;
  spec: Record<string, unknown>;
  canvas: CompCanvas; // the comp's authored aspect — sizes the stage pre-fetch
  maxHeight: number;
  loop: PreviewLoop;
  loopId: string; // unique per surface (card:<kind> vs showcase:<kind>)
  onClick?: () => void;
  className?: string;
}

export function ElementPreview({ kind, spec, canvas, maxHeight, loop, loopId, onClick, className }: PreviewProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const { inView, seen } = useInView(wrapRef);
  const width = useWidth(wrapRef);
  const specJson = useMemo(() => JSON.stringify(spec), [spec]);
  const { html, err } = useCompHtml(kind, specJson, null, seen);
  const dims = useMemo(() => parseDims(html), [html]);
  const durationS = useMemo(() => parseRootDuration(html, DEFAULT_DURATION_S), [html]);
  const health = usePreviewHealth(iframeRef, html);

  // Drive the shared loop ONLY while visible and booted; scrolling the card out
  // of view (or unmounting — panel/showcase close) unregisters it.
  useEffect(() => {
    if (!inView || !html || err || health.error) return;
    loop.register(loopId, () => iframeRef.current?.contentWindow ?? null, durationS);
    return () => loop.unregister(loopId);
  }, [inView, html, err, health.error, durationS, loop, loopId]);

  const [bw, bh] = canvas === "16:9" ? [16, 9] : [9, 16];
  const stageH = width ? Math.min((width * bh) / bw, maxHeight) : 0;
  const scale = stageH ? Math.min(((stageH * bw) / bh) / dims.w, stageH / dims.h) : 0;

  return (
    <div
      ref={wrapRef}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      aria-label={onClick ? `Preview ${kind}` : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        onClick();
      } : undefined}
      title={onClick ? "Expand preview" : undefined}
      data-preview-state={err || health.error ? "failed" : health.ready ? "ready" : "loading"}
      className={`relative flex w-full items-center justify-center overflow-hidden rounded border border-neutral-800 bg-gradient-to-br from-neutral-800/70 via-neutral-900 to-neutral-950 ${
        onClick ? "cursor-zoom-in hover:border-neutral-600" : ""
      } ${className ?? ""}`}
      style={{ height: stageH || 96 }}
    >
      {seen && html && !err && (
        <PreviewStage kind={kind} html={html} dims={dims} scale={scale} iframeRef={iframeRef}
          onLoad={health.requestHealth} />
      )}
      {(err || health.error) && (
        <span role="alert" className="absolute inset-0 flex items-center justify-center bg-neutral-950/90 p-2 text-center text-[10px] text-rose-300">
          preview failed: {err || health.error}
        </span>
      )}
    </div>
  );
}

interface StageProps {
  kind: string;
  html: string;
  dims: { w: number; h: number };
  scale: number;
  iframeRef: RefObject<HTMLIFrameElement | null>;
  onLoad: () => void;
}

/** The scaled, sandboxed comp iframe (pointer-events off — clicks belong to the wrapper). */
function PreviewStage({ kind, html, dims, scale, iframeRef, onLoad }: StageProps) {
  return (
    <div className="relative overflow-hidden" style={{ width: dims.w * scale, height: dims.h * scale }}>
      <iframe
        ref={iframeRef}
        sandbox="allow-scripts"
        srcDoc={html}
        title={`element preview: ${kind}`}
        onLoad={onLoad}
        style={{
          width: dims.w,
          height: dims.h,
          border: 0,
          transform: `scale(${scale})`,
          transformOrigin: "0 0",
          background: "transparent",
          pointerEvents: "none",
        }}
      />
    </div>
  );
}

/**
 * The one insert affordance (card + showcase): disabled on canvas mismatch.
 * When the ruler armed a pending insert window, the label says so — the add
 * targets that window, not the playhead.
 */
export function AddAtPlayheadButton({ entry, planCanvas, playhead, pendingInsert, onAdd, className }: {
  entry: CompCatalogEntry;
  planCanvas: CompCanvas;
  playhead: number;
  pendingInsert?: { start: number; end: number } | null;
  onAdd: (entry: CompCatalogEntry) => void;
  className: string; // size classes (px/py/text) — card and showcase differ
}) {
  const mismatch = entry.canvas !== planCanvas;
  return (
    <button
      onClick={() => onAdd(entry)}
      disabled={mismatch}
      title={mismatch ? `${entry.canvas}-canvas comp — can't insert into a ${planCanvas} plan` : undefined}
      className={`rounded border border-emerald-500/40 text-emerald-200 enabled:hover:bg-emerald-500/10 disabled:cursor-not-allowed disabled:border-neutral-700 disabled:text-neutral-500 ${className}`}
    >
      {pendingInsert
        ? `Add at ${pendingInsert.start.toFixed(1)}–${pendingInsert.end.toFixed(1)}s`
        : `Add at playhead (${playhead.toFixed(1)}s)`}
    </button>
  );
}

/** The card/showcase badge row — FULL-FRAME + canvas flags, one source of truth. */
export function ElementBadges({ entry, planCanvas }: { entry: CompCatalogEntry; planCanvas: CompCanvas }) {
  const mismatch = entry.canvas !== planCanvas;
  return (
    <>
      {entry.ownScreen && (
        <span
          className="rounded bg-violet-500/25 px-1 py-px text-[9px] text-violet-200"
          title="Hard-cuts the full frame for its window (cutaway), not an overlay"
        >
          FULL-FRAME
        </span>
      )}
      {mismatch ? (
        <span
          className="rounded bg-amber-500/20 px-1 py-px text-[9px] text-amber-300"
          title={`Authored on a ${entry.canvas} canvas — it would composite half-frame in this ${planCanvas} plan`}
        >
          {entry.canvas} only
        </span>
      ) : (
        entry.canvas === "9:16" && (
          <span
            className="rounded bg-neutral-700/60 px-1 py-px text-[9px] text-neutral-300"
            title="Authored on a vertical (9:16) canvas — best in shorts"
          >
            9:16
          </span>
        )
      )}
    </>
  );
}
