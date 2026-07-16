/**
 * CLIPPER skill — keep-ranges → Final Cut Pro FCPXML (standalone CLI).
 *
 * Reuses the SAME generator the /clipper GUI uses (src/lib/clipper/xml.ts), so a
 * skill-driven export is byte-identical to the app's. The brain decides the keep
 * ranges; this only turns them into a timeline.
 *
 *   node --import tsx scripts/clipper/clipper_fcpxml.ts <video> <keep_ranges.json> <out.fcpxml>
 *
 * keep_ranges.json: [{ "start": number, "end": number, "text": string }, ...]
 *   — the exact shape scripts/producer/edit/render_cut.py consumes, so ONE file
 *   feeds both the rendered MP4 and this FCPXML.
 *
 * Single-cam / camera-audio only (audioChannels=1). Dual-cam and lav routing are
 * GUI features; this convenience export keeps to the common single-file case.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { generateFCPXML } from "@/lib/clipper/xml";
import { probeVideoMetadata } from "@/lib/server/clipper-media-probe";
import type { Source } from "@/lib/clipper/types";

interface KeepRange {
  start: number;
  end: number;
  text?: string;
}

async function main(): Promise<void> {
  const [video, rangesPath, outPath] = process.argv.slice(2);
  if (!video || !rangesPath || !outPath) {
    process.stderr.write(
      "Usage: node --import tsx scripts/clipper/clipper_fcpxml.ts <video> <keep_ranges.json> <out.fcpxml>\n",
    );
    process.exit(1);
  }

  const meta = await probeVideoMetadata(video);
  const parsed = JSON.parse(readFileSync(rangesPath, "utf8")) as KeepRange[];
  if (!Array.isArray(parsed) || parsed.length === 0) {
    throw new Error("keep_ranges.json must be a non-empty array of {start,end,text}");
  }
  const segments = parsed.map((r) => ({ start: r.start, end: r.end, text: r.text ?? "" }));

  const source: Source = {
    angles: [{ id: "A", filePath: resolve(video), audioSource: true }],
    duration: meta.duration,
    fps: meta.frameRate.numerator / meta.frameRate.denominator,
    frameRate: meta.frameRate,
    width: meta.width,
    height: meta.height,
    audioChannels: 1,
    audioMode: "camera",
  };

  writeFileSync(outPath, generateFCPXML(segments, source));
  process.stdout.write(`${outPath}\n`);
}

main().catch((err) => {
  process.stderr.write(`${err instanceof Error ? err.message : String(err)}\n`);
  process.exit(1);
});
