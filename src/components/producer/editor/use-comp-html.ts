"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";

// Shared comp-html plumbing for every live-preview surface: the player overlay
// (graphic-preview.tsx) and the ELEMENTS panel card/showcase previews
// (element-preview.tsx). /api/producer/comp-html serves the comp's HTML with
// the spec injected exactly like graphics_render.py's --variables, plus an
// hf-seek postMessage listener that scrubs every registered window.__timelines.

/**
 * Fetch the injected comp HTML for an iframe srcdoc; refetch per kind/spec/
 * duration (duration null = keep the comp's authored data-duration). The result
 * is keyed by its URL, so a stale response for a previous request never
 * renders — no synchronous state reset needed in the effect.
 */
export function useCompHtml(
  kind: string,
  specJson: string,
  durationS: number | null,
  active: boolean,
) {
  const [res, setRes] = useState<{ url: string; html?: string; err?: string } | null>(null);
  const url = active
    ? `/api/producer/comp-html?kind=${encodeURIComponent(kind)}` +
      `&spec=${encodeURIComponent(specJson)}` +
      (durationS !== null ? `&duration=${durationS}` : "")
    : null;
  useEffect(() => {
    if (!url) return;
    let alive = true;
    fetch(url)
      .then(async (r) => {
        if (!r.ok) {
          const e = await r.json().catch(() => ({}));
          throw new Error((e as { error?: string }).error || `comp-html ${r.status}`);
        }
        return r.text();
      })
      .then((t) => alive && setRes({ url, html: t }))
      .catch((e) => alive && setRes({ url, err: e instanceof Error ? e.message : "preview failed" }));
    return () => {
      alive = false;
    };
  }, [url]);
  const current = res && res.url === url ? res : null;
  return { html: current?.html ?? null, err: current?.err ?? "" };
}

// The settled probe times of graphics_anchors._content_bbox, as fractions of
// the clip — past any entrance animation, matching the render's measurement.
const MEASURE_FRACS = [0.72, 0.85, 0.95] as const;

interface OriginMsg {
  type?: string;
  nonce?: number;
  x0?: number;
  y0?: number;
  x1?: number;
  y1?: number;
  empty?: boolean;
}

/**
 * The comp's painted-content ORIGIN (top-left, canvas px) and unscaled SIZE
 * (bbox w/h, canvas px), measured inside the preview iframe by the injected
 * shim (comp-html/preview-shim.ts) at the same settled times the render
 * probes. The compositor pins the measured CONTENT top-left at
 * entry.placement (graphics_stage._explicit_offset), so the preview must
 * translate the comp canvas by (placement − origin) — using raw placement
 * mis-previews every comp whose content isn't authored at the canvas origin.
 * `size` feeds the corner scale grips (the scaled box is size × scale about
 * the pin). Both null until measured (or when the comp paints nothing —
 * callers keep drag-to-place OFF rather than committing wrong coordinates).
 *
 * Call `requestMeasure` from the iframe's onLoad; the probes briefly seek the
 * comp, so re-seek to the playhead when `origin` lands.
 */
export function useContentOrigin(
  iframeRef: RefObject<HTMLIFrameElement | null>,
  html: string | null,
  durationS: number,
) {
  // The measurement is stored WITH the html it was taken against, and exposed
  // only while that html is still current — a new comp/spec (new footprint)
  // derives back to null with no reset effect, and a late reply for a
  // superseded document can never leak through.
  const [measured, setMeasured] = useState<{
    html: string;
    x: number;
    y: number;
    w: number;
    h: number;
  } | null>(null);
  const nonceRef = useRef(0);
  const current = measured && measured.html === html ? measured : null;
  const origin = useMemo(() => (current ? { x: current.x, y: current.y } : null), [current]);
  const size = useMemo(() => (current ? { w: current.w, h: current.h } : null), [current]);

  useEffect(() => {
    if (!html) return;
    const onMsg = (e: MessageEvent) => {
      const d = e.data as OriginMsg | null;
      if (!d || d.type !== "hf-content-origin" || d.nonce !== nonceRef.current) return;
      if (e.source !== iframeRef.current?.contentWindow) return;
      const nums = [d.x0, d.y0, d.x1, d.y1];
      if (d.empty || nums.some((n) => typeof n !== "number")) {
        console.warn("comp preview: no painted content measured — drag-to-place stays off");
        return; // origin stays null — never guess an origin (fail loud)
      }
      const [x0, y0, x1, y1] = nums as [number, number, number, number];
      setMeasured({ html, x: x0, y: y0, w: x1 - x0, h: y1 - y0 });
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [iframeRef, html]);

  const requestMeasure = useCallback(() => {
    const w = iframeRef.current?.contentWindow;
    if (!w) return;
    nonceRef.current += 1;
    const ts = MEASURE_FRACS.map((f) => f * durationS);
    w.postMessage({ type: "hf-measure", nonce: nonceRef.current, ts }, "*");
  }, [iframeRef, durationS]);

  return { origin, size, requestMeasure };
}

/** The comp's authored canvas (data-width/height on the composition root). */
export function parseDims(html: string | null): { w: number; h: number } {
  const w = html?.match(/data-width="(\d+)"/);
  const h = html?.match(/data-height="(\d+)"/);
  return { w: w ? Number(w[1]) : 1080, h: h ? Number(h[1]) : 1920 };
}

/**
 * The comp's authored duration: data-duration on the composition ROOT tag (the
 * one carrying data-composition-id — child clips hold ="60" sentinels).
 */
export function parseRootDuration(html: string | null, fallback: number): number {
  const tag = html?.match(/<[^>]*data-composition-id="[^"]*"[^>]*>/)?.[0];
  const m = tag?.match(/data-duration="([\d.]+)"/);
  const d = m ? Number(m[1]) : NaN;
  return Number.isFinite(d) && d > 0 ? d : fallback;
}
