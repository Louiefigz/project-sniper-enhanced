"use client";

import { safeRect, type BoxSize, type CanvasDims } from "@/lib/producer/placement-geometry";

interface Props {
  canvas: CanvasDims; // the comp's authored canvas (1080x1920 shorts)
  box: BoxSize; // the <video> layout box, display px
}

// SAFE-ZONE overlay shown WHILE DRAGGING a graphic on a shorts canvas: the
// producer_config.SAFE_BOX margins (top 250 / bottom 520 / left 60 / right 150
// on 1080x1920 — TikTok/Reels/Shorts UI chrome) dimmed, plus a dashed guide
// rect around the platform-safe area. Purely visual — the soft-snap and the
// unsafe-release warning live in lib/producer/placement-geometry.
export default function SafeZoneGuides({ canvas, box }: Props) {
  const r = safeRect(canvas);
  const sx = box.width / canvas.w;
  const sy = box.height / canvas.h;
  const left = r.left * sx;
  const top = r.top * sy;
  const right = r.right * sx;
  const bottom = r.bottom * sy;
  const dim = "pointer-events-none absolute bg-neutral-950/50";
  return (
    <>
      <div className={dim} style={{ left: 0, top: 0, width: box.width, height: top }} />
      <div className={dim} style={{ left: 0, top: bottom, width: box.width, height: box.height - bottom }} />
      <div className={dim} style={{ left: 0, top, width: left, height: bottom - top }} />
      <div className={dim} style={{ left: right, top, width: box.width - right, height: bottom - top }} />
      <div
        className="pointer-events-none absolute rounded-sm border border-dashed border-sky-300/70"
        style={{ left, top, width: right - left, height: bottom - top }}
        title="platform-safe area (SAFE_BOX)"
      />
    </>
  );
}
