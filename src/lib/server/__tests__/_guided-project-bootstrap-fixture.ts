/** TEST metadata only. Never verifies a media source, runs critics, or starts a worker. */
import path from "node:path";
import { randomUUID } from "node:crypto";
import { mkdtempSync, realpathSync, rmSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import type { TestContext } from "node:test";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseCutApprovalRequest } from "@/lib/producer/contracts/cut-approval-request";
import { bootstrapGuidedProject, bootstrapServices } from "../guided-project-bootstrap";
import { autoEditJobPath, parseAutoEditJobRecord } from "../auto-edit-job-persistence";
import { parseBootstrapRequest } from "../guided-project-bootstrap-contract";

export const HASH = "a".repeat(64);

export function bootstrapFixture(t: TestContext) {
  const root = realpathSync(mkdtempSync(path.join(tmpdir(), "TEST-bootstrap-")));
  const prior = process.env.SNIPER_WORKSPACE_ROOT; process.env.SNIPER_WORKSPACE_ROOT = root;
  t.after(() => {
    if (prior === undefined) delete process.env.SNIPER_WORKSPACE_ROOT; else process.env.SNIPER_WORKSPACE_ROOT = prior;
    rmSync(root, { recursive: true, force: true });
  });
  const intent = { mode: "longform", scope: "produced", lanes: {} };
  const plan = { planVersion: 7, target: { ...intent, treatment: "produced", fps: 30, width: 1920, height: 1080 },
    cutTrack: [{ sourceId: "TEST-source", start: 0, end: 12, speed: 1 }], cutDecisions: { schemaVersion: 1, removals: [] } };
  const candidate = path.join(root, "TEST-original-plan.json"), manifest = path.join(root, "TEST-manifest.json");
  writeFileSync(candidate, JSON.stringify(plan));
  writeFileSync(manifest, JSON.stringify({ sources: [{ id: "TEST-source" }], sourceSetAdmission: { schemaVersion: 1 } }));
  const request = parseBootstrapRequest({ schemaVersion: 1, operation: "bootstrap-existing-cut", idempotencyKey: randomUUID(), intent,
    candidate: { path: candidate, sha256: observeCutPreviewFile(candidate, 131072).sha256 },
    manifest: { path: manifest, sha256: observeCutPreviewFile(manifest, 131072).sha256 } });
  let launches = 0;
  t.mock.method(bootstrapServices, "pin", ({ ctx }: Parameters<typeof bootstrapServices.pin>[0]) => ctx);
  t.mock.method(bootstrapServices, "launch", async () => { launches++; return 12345; });
  const start = async () => {
    const result = await bootstrapGuidedProject(request), dir = result.producerDir;
    const jobPath = autoEditJobPath(dir), job = parseAutoEditJobRecord(JSON.parse(readFileSync(jobPath, "utf8")));
    return { result, dir, jobPath, job };
  };
  return { root, request, candidate, manifest, plan, start, launches: () => launches };
}

export function bootstrapCutRequest(job: Awaited<ReturnType<ReturnType<typeof bootstrapFixture>["start"]>>["job"]) {
  const core = { schemaVersion: 1, requestKey: job.requestKey, planHash: job.ctx.existingCutCandidate!.savedPlanSha256,
    authorityDigest: HASH, cutAuthorityDigest: HASH, cutApprovalReceiptHash: HASH, cutReviewApprovalReceiptHash: HASH,
    pictureLockHash: HASH, timelineMapHash: HASH, projectionReceiptHash: HASH, createdAt: new Date().toISOString() };
  return parseCutApprovalRequest({ ...core, requestHash: canonicalJsonSha256(core) });
}
