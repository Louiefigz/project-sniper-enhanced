import { createHash, randomUUID } from "node:crypto";
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileSha256 } from "@/lib/server/auto-edit-job-store";
import { atomicWriteJsonSync } from "@/lib/server/atomic-file";
import { LANES, resolveLanes } from "@/lib/producer/intent-presets";
import type { AutoEditCtx } from "../auto-edit/stream";
import type { LiveBuildPreflight } from "./preflight";
import { liveBuildJournalPath } from "./state";

export interface TimelineIdentity {
  projectId: string;
  timelineId: string;
  fingerprint: string;
}

export interface PalmierLiveBuildQcAuthority {
  schemaVersion: 1;
  kind: "palmier-live-build-qc-authority";
  requestHash: string;
  captureId: string;
  liveInput: {
    path: string;
    hash: string;
    planHash: string;
    journalHash: string;
    lanes: string[];
    parent: TimelineIdentity;
    operationCount: number;
    sessionId: string;
  };
  ctx: AutoEditCtx;
}

interface CaptureInput {
  preflight: LiveBuildPreflight;
  parent: TimelineIdentity;
  sessionId: string;
  operationCount: number;
}

function sha(value: string | Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}

function activeLanes(ctx: AutoEditCtx): string[] {
  const resolved = resolveLanes(ctx.scope, ctx.intent?.lanes);
  const lanes = LANES.filter((lane) => resolved[lane] === "auto");
  return ["cuts", "reframe", ...lanes,
    ...(ctx.intent?.audioEnhance ? ["audio"] : []),
    ...(ctx.intent?.music ? ["music"] : [])];
}

function exactHash(filePath: string, expected: string, label: string): string {
  const current = fileSha256(filePath);
  if (!current || current !== expected) {
    throw new Error(`${label} changed before Palmier QC authority was captured.`);
  }
  return current;
}

/** Freeze the approved plan, operation journal, and pinned Producer context. */
export function captureLiveBuildQcAuthority(input: CaptureInput): {
  authority: PalmierLiveBuildQcAuthority;
  authorityPath: string;
} {
  const { preflight } = input;
  exactHash(preflight.planPath, preflight.planHash, "Approved plan");
  const journalPath = liveBuildJournalPath(preflight.dir);
  const journalHash = fileSha256(journalPath);
  if (!journalHash || input.operationCount < 1) {
    throw new Error("Live build produced no hash-bound Palmier mutation journal.");
  }
  const lanes = activeLanes(preflight.ctx);
  const request = `Execute approved Producer plan ${preflight.planHash} exactly in the governed Palmier candidate.`;
  const requestHash = sha(request);
  const captureId = `live-${preflight.planHash.slice(0, 16)}-${randomUUID()}`;
  const runDir = path.join(preflight.dir, ".sniper-learning", "runs", captureId);
  mkdirSync(runDir, { recursive: true, mode: 0o700 });
  const liveInputPath = path.join(runDir, "live-build-input.json");
  const artifact = {
    schemaVersion: 1,
    kind: "palmier-live-build-input",
    captureId,
    request: { text: request, hash: requestHash },
    controller: { lanes },
    parent: input.parent,
    plan: { path: preflight.planPath, hash: preflight.planHash },
    journal: { path: journalPath, hash: journalHash,
      operationCount: input.operationCount },
    planningReviews: preflight.planningReviews,
    sessionId: input.sessionId,
  };
  atomicWriteJsonSync(liveInputPath, artifact);
  const liveInputHash = sha(readFileSync(liveInputPath));
  const authority: PalmierLiveBuildQcAuthority = {
    schemaVersion: 1,
    kind: "palmier-live-build-qc-authority",
    requestHash,
    captureId,
    liveInput: {
      path: liveInputPath, hash: liveInputHash,
      planHash: preflight.planHash, journalHash, lanes,
      parent: input.parent, operationCount: input.operationCount,
      sessionId: input.sessionId,
    },
    ctx: preflight.ctx,
  };
  const authorityPath = path.join(runDir, "live-build-authority.json");
  atomicWriteJsonSync(authorityPath, authority);
  return { authority, authorityPath };
}
