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
  originalPath?: string;
  sourceSha256?: string;
  admissionReceiptPath?: string;
  admissionReceiptSha256?: string;
}

/** Hash-bound receipt for the immutable media snapshots admitted by ingest.py. */
export interface SourceSetAdmissionBinding {
  schemaVersion: 1;
  receiptPath: string;
  receiptSha256: string;
  sourceSetDigest: string;
  entryCount: number;
}

const SHA256_PATTERN = /^[0-9a-f]{64}$/;

/** New `/producer/ingest` runs cannot publish a stripped admission binding. */
export function requireSourceSetAdmission(
  manifest: AssetManifest,
): SourceSetAdmissionBinding {
  const value = manifest.sourceSetAdmission;
  if (!value || value.schemaVersion !== 1) {
    throw new Error("ingest manifest has no source-set admission binding");
  }
  const expectedPath = `.sniper-source-sets/${value.receiptSha256}.json`;
  if (
    !SHA256_PATTERN.test(value.receiptSha256)
    || !SHA256_PATTERN.test(value.sourceSetDigest)
    || value.receiptPath !== expectedPath
    || !Number.isSafeInteger(value.entryCount)
    || value.entryCount < 0
  ) {
    throw new Error("ingest manifest source-set admission binding is malformed");
  }
  return value;
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
  /** Required on new Producer ingests; absent only on legacy/test manifests. */
  sourceSetAdmission?: SourceSetAdmissionBinding;
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
