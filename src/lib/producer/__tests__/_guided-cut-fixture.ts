import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { runCutReviewLoop } from "@/app/api/producer/auto-edit/cut-review-loop";
import { verifyApprovedCut } from "@/app/api/producer/auto-edit/cut-approval";
import { mintCompatibilityPictureLock } from "@/app/api/producer/auto-edit/compatibility-picture-lock";
import { DEFAULT_PIPELINE_DEPENDENCIES } from "@/app/api/producer/auto-edit/pipeline-dependencies";
import type { PipelineRuntime } from "@/app/api/producer/auto-edit/pipeline-types";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import {
  appendAutoEditJobEvent, autoEditJobPath, startAutoEditJob,
} from "@/lib/server/auto-edit-job-store";
import { diskCheckpointWriter, diskInvalidationWriter } from "@/app/api/producer/auto-edit/pipeline-writers";
import { parseGuidedWorkflowV2, type GuidedWorkflowV2 } from "@/lib/producer/contracts/guided-workflow-v2";

/** TEST ONLY: a Python-first program (tests/_cut_preview_fixture.py --program …) already authored
 * project.json, source/raw.transcript.json, source/asset_manifest.json and producer/edit_plan.json.
 * Reuse them verbatim instead of overwriting with the 3-second default. */
function authoredMediaFixture(root: string): AutoEditCtx {
  const dir = path.join(root, "producer"), source = path.join(root, "source");
  const project = JSON.parse(readFileSync(path.join(root, "project.json"), "utf8")) as { intent: AutoEditCtx["intent"] & { scope: AutoEditCtx["scope"] } };
  const planPath = path.join(dir, "edit_plan.json"), manifestPath = path.join(source, "asset_manifest.json");
  for (const file of [planPath, manifestPath, path.join(source, "raw.transcript.json")]) {
    if (!existsSync(file)) throw new Error(`Authored TEST program is missing ${file}`);
  }
  if (!project.intent?.mode || !project.intent.scope) throw new Error("Authored TEST program lacks a stored operator intent");
  return { dir, planPath, manifestPath, transcriptsDir: source, scope: project.intent.scope,
    intent: project.intent, workflowPolicy: "cut-first", deliveryPolicy: "mp4-only" };
}

function mediaFixture(root: string, reuseAuthored = false, graphicsOff = false): AutoEditCtx {
  if (reuseAuthored && graphicsOff) throw new Error("TEST explicit graphics-off may not retrofit an authored program");
  if (reuseAuthored) return authoredMediaFixture(root);
  const dir = path.join(root, "producer"), source = path.join(root, "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  const lanes = graphicsOff ? { graphics: "off" as const } : {};
  const intent = { mode: "longform" as const, scope: "produced" as const, lanes, music: false };
  writeFileSync(path.join(root, "project.json"), JSON.stringify({ origin: "upload", intent }));
  const transcript = path.join(source, "raw.transcript.json");
  writeFileSync(transcript, JSON.stringify({ transcript: [{
    start: 0, end: 3, text: "We can make this much clearer today.", words: [
      { word: "We", start: 0, end: 0.3 }, { word: "can", start: 0.3, end: 0.6 },
      { word: "make", start: 0.6, end: 1 }, { word: "this", start: 1, end: 1.3 },
      { word: "much", start: 1.3, end: 1.7 }, { word: "clearer", start: 1.7, end: 2.3 },
      { word: "today.", start: 2.3, end: 3 },
    ],
  }] }));
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(manifestPath, JSON.stringify({ sources: [{ id: "raw-1", duration: 3,
    transcriptPath: path.basename(transcript) }] }));
  const planPath = path.join(dir, "edit_plan.json");
  writeFileSync(planPath, JSON.stringify({ planVersion: 1,
    target: { mode: "longform", scope: "produced", width: 1920, height: 1080, fps: 30, ...(graphicsOff ? { lanes } : {}) },
    cutTrack: [{ sourceId: "raw-1", start: 0, end: 3, speed: 1, rationale: "Keep the complete opening thought." }],
    cutDecisions: { schemaVersion: 1, removals: [] },
  }));
  return { dir, planPath, manifestPath, transcriptsDir: source, scope: "produced",
    intent, workflowPolicy: "cut-first", deliveryPolicy: "mp4-only" };
}

/** Actual cut gates/review artifacts/projection; model calls and preview rendering are synthetic. */
export function guidedFixture(root: string, workflowV2?: GuidedWorkflowV2, options: { reuseAuthored?: boolean; graphicsOff?: boolean } = {}) {
  const ctx = mediaFixture(root, options.reuseAuthored ?? false, options.graphicsOff ?? false);
  if (workflowV2) ctx.workflowV2 = parseGuidedWorkflowV2(workflowV2);
  const job = startAutoEditJob({ ctx, token: "guided-job", snapshots: 0 });
  const jobPath = autoEditJobPath(ctx.dir);
  const events: Record<string, unknown>[] = [];
  const calls = { cutWriters: 0, visualWriters: 0, critics: 0, verifications: 0, locks: 0, planning: 0, renders: 0 };
  const run: PipelineRuntime = { job, io: {
    send: (event) => { events.push(event); appendAutoEditJobEvent(jobPath, job.token, event); },
    sendRaw: (line) => events.push({ line }),
    advance: diskCheckpointWriter(jobPath, job.token), invalidate: diskInvalidationWriter(jobPath, job.token),
  } };
  const deps = { ...DEFAULT_PIPELINE_DEPENDENCIES,
    prepareCutPreview: async () => ({ executionKey: "1".repeat(64), receiptHash: "2".repeat(64) }),
    author: async (_ctx: AutoEditCtx, _send: unknown, stage: "cut" | "visual") => {
      if (stage === "cut") calls.cutWriters += 1;
      else calls.visualWriters += 1;
      return { code: 0, timedOut: false, errTail: "", ms: 1, provider: "codex" as const, authored: null };
    },
    reviewCut: (runtime: Parameters<typeof runCutReviewLoop>[0]) => runCutReviewLoop(runtime, {
      review: async () => {
        calls.critics += 1;
        return { provider: "codex" as const, ms: 1, review: { schemaVersion: 1 as const,
          stage: "cut" as const, verdict: "pass" as const, summary: "The cut is coherent.", materialIssues: [], findings: [] } };
      },
    }),
    verifyCut: async (...args: Parameters<typeof verifyApprovedCut>) => {
      calls.verifications += 1;
      return verifyApprovedCut(...args);
    },
    lockCut: async (...args: Parameters<typeof mintCompatibilityPictureLock>) => {
      calls.locks += 1;
      return mintCompatibilityPictureLock(...args);
    },
    planning: async () => { calls.planning += 1; throw new Error("guided cut may not enter planning"); },
    assemble: async () => { calls.renders += 1; throw new Error("guided cut may not render final media"); },
    checkpoint: async () => ({ status: "deferred" as const, reason: "test does not contact Palmier" }),
    palmierPrimary: async () => false,
    reconciliationReady: () => {},
  };
  return { ctx, run, jobPath, events, calls, deps };
}
