// PRODUCER (Part 3) live-app shapes — the thin UI over the Python pipeline.
//
// Phase 4 EXPERIMENTAL scaffold: the AI brain is NOT here. Plans are supplied by
// the operator (pasted JSON) — the `producer` skill remains the brain. These
// types only describe what the ingest / lint / render Python CLIs emit and what
// the UI carries between steps. See docs/producer/PRODUCER_PLAN.md §3.3 + §2.

/** Where the operator is in the /producer flow. */
export type ProducerStep = "select" | "manifest" | "render" | "edit";

/** One raw source in an asset_manifest.json (ingest.py `_source_entry`). */
export interface ManifestSource {
  id: string;
  path: string;
  duration: number;
  fps: number;
  vfr: boolean;
  resolution: [number, number];
  rotation: number;
  audio: { present: boolean; channels: number; sampleRate: number };
  contentHash: string;
  transcriptPath: string | null;
  role: string;
}

/**
 * B-roll / music catalog entries carry variable fields depending on kind; the
 * scaffold only summarizes them, so they stay loosely typed with a stable id.
 */
export interface ManifestAsset {
  id: string;
  path?: string;
  duration?: number;
  [key: string]: unknown;
}

/** The whole ingest output (docs/producer/PRODUCER_PLAN.md §2.1). */
export interface AssetManifest {
  generatedAt: string;
  input: string;
  sources: ManifestSource[];
  broll: ManifestAsset[];
  music: ManifestAsset[];
}

/** Availability only: manifest entries are never proof that a track is selected. */
export interface ManifestMusicSummary {
  project: number;
  bundled: number;
  available: number;
}

/** Separate operator/project tracks from repo-bundled fallback beds. */
export function summarizeManifestMusic(
  music: ManifestAsset[] | undefined,
): ManifestMusicSummary {
  const assets = music ?? [];
  const bundled = assets.filter((asset) => asset.source === "builtin").length;
  return {
    project: assets.length - bundled,
    bundled,
    available: assets.length,
  };
}

/** plan_lint.py verdict — exit 0 = renderable (warnings ok), exit 1 = rejected. */
export interface LintVerdict {
  ok: boolean;
  errors: string[];
  warnings: string[];
}

/** A parsed SSE status line from any Python stage (loosely typed — shapes vary). */
export type StreamEvent = Record<string, unknown>;

/** One rendered line in a stream log panel. */
export type LogKind = "info" | "event" | "stderr" | "error";
export interface LogLine {
  t: string;
  kind: LogKind;
  text: string;
}
