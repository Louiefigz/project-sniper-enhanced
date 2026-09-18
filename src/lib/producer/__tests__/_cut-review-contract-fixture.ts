/** Small transcript-only fixture: no media, provider process, or creator approval. */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import type { CutApprovalReceipt } from "@/app/api/producer/auto-edit/cut-approval";
import { autoEditAuthoritySnapshot, stableAuthorityHash } from "@/lib/server/auto-edit-authority-snapshot";
import { captureAutoEditDoctrine } from "@/lib/server/auto-edit-doctrine";

export function cutReviewFixture(root: string): AutoEditCtx {
  const dir = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  writeFileSync(path.join(source, "raw.transcript.json"), JSON.stringify({
    transcript: [{
      start: 0, end: 3, text: "This is the complete opening thought.",
      words: [
        { word: "This", start: 0, end: 0.4 }, { word: "is", start: 0.4, end: 0.6 },
        { word: "the", start: 0.6, end: 0.8 }, { word: "complete", start: 0.8, end: 1.4 },
        { word: "opening", start: 1.4, end: 2 }, { word: "thought.", start: 2, end: 2.6 },
      ],
    }],
  }));
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(manifestPath, JSON.stringify({
    sources: [{ id: "raw", transcriptPath: "raw.transcript.json" }],
  }));
  const planPath = path.join(dir, "edit_plan.json");
  writeFileSync(planPath, JSON.stringify({
    planVersion: 1, target: { mode: "longform" },
    cutTrack: [{ sourceId: "raw", start: 0, end: 2.6, speed: 1, rationale: "Complete thought." }],
    cutDecisions: { schemaVersion: 1, removals: [] },
  }));
  const base: AutoEditCtx = {
    dir, planPath, manifestPath, transcriptsDir: source, scope: "produced",
    intent: { mode: "longform", lanes: {} },
  };
  return { ...base, doctrine: captureAutoEditDoctrine(base, "cut-contract", process.cwd()) };
}

/** Metadata-only deterministic receipt; not an executed gate or acoustic proof. */
export function cutReviewGate(ctx: AutoEditCtx): CutApprovalReceipt {
  const authority = autoEditAuthoritySnapshot(ctx);
  const plan = JSON.parse(readFileSync(ctx.planPath, "utf8"));
  return {
    schemaVersion: 1, stage: "previsual",
    planHash: authority.planHash!, manifestHash: authority.manifestHash!,
    transcriptDigest: authority.transcriptDigest,
    cutTrackDigest: stableAuthorityHash(plan.cutTrack),
    cutDecisionsDigest: stableAuthorityHash(plan.cutDecisions),
    cuts: 1, seams: [], removals: [],
  };
}
