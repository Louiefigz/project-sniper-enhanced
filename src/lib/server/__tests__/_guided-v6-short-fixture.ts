/** Actual NEW bootstrap/source/preview; only launch transport and critics are TEST stubs. */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdtempSync, realpathSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import type { TestContext } from "node:test";
import { pythonInterpreter, SCRIPTS_DIR } from "@/app/api/_lib/spawn-python";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { runCutPreviewProcess } from "@/app/api/producer/auto-edit/cut-preview-process";
import { renderPrivateCutPreview } from "@/app/api/producer/auto-edit/cut-preview";
import { runAutoEditPipeline, type PipelineRuntime } from "@/app/api/producer/auto-edit/pipeline";
import { runCutReviewLoop } from "@/app/api/producer/auto-edit/cut-review-loop";
import { diskCheckpointWriter, diskInvalidationWriter } from "@/app/api/producer/auto-edit/pipeline-writers";
import { settleWorkerExecution, withWorkerMutationLease } from "@/app/api/producer/auto-edit/worker-outcome";
import { bootstrapGuidedProject, bootstrapServices } from "../guided-project-bootstrap";
import { readGuidedProjectBootstrapStatus } from "../guided-project-bootstrap-status";
import { parseBootstrapRequest } from "../guided-project-bootstrap-contract";
import { autoEditJobPath, readAutoEditJob, markAutoEditWorker, appendAutoEditJobEvent } from "../auto-edit-job-store";
import { runBootstrapWorker } from "../guided-project-bootstrap-worker";

const SOURCE_SCRIPT = path.join(SCRIPTS_DIR, "producer/tests/_guided_v6_short_source.py");

/** No reuse parameter: every actual run gets new source bytes, admission and project UUID. */
async function sourceFixture(t: TestContext, remainingMs: () => number) {
  remainingMs();
  const workspace = realpathSync(mkdtempSync(path.join(tmpdir(), "sniper-v6-short-")));
  const previous = process.env.SNIPER_WORKSPACE_ROOT;
  process.env.SNIPER_WORKSPACE_ROOT = workspace;
  t.after(() => { if (previous === undefined) delete process.env.SNIPER_WORKSPACE_ROOT; else process.env.SNIPER_WORKSPACE_ROOT = previous; });
  writeFileSync(path.join(workspace, "TEST-ONLY.json"), JSON.stringify({ synthetic: true, genuineHumanAcceptance: false,
    actualAsr: false, providerCalls: 0, launchTransport: "in-process TEST controller, not detached qualification" }), { flag: "wx", mode: 0o600 });
  process.stderr.write(`V6 SHORT TEST retained workspace: ${workspace}\n`);
  const sourceRoot = path.join(workspace, "TEST-source");
  const source = await runCutPreviewProcess({ command: pythonInterpreter(), args: [SOURCE_SCRIPT, sourceRoot],
    cwd: path.dirname(SOURCE_SCRIPT), timeoutMs: Math.min(600_000, remainingMs()), signal: t.signal, trackForShutdown: true,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONPATH: `${path.dirname(path.dirname(SOURCE_SCRIPT))}${path.delimiter}${path.dirname(SOURCE_SCRIPT)}` } });
  remainingMs();
  writeFileSync(path.join(workspace, "TEST-source-process.json"), JSON.stringify(source), { flag: "wx", mode: 0o600 });
  const documents = readCutPreviewObject(path.join(sourceRoot, "TEST-initial-documents.json")).value;
  const plan = readCutPreviewObject(path.join(sourceRoot, "TEST-previsual-plan.json"));
  const manifest = readCutPreviewObject(path.join(sourceRoot, "source/asset_manifest.json"));
  const request = parseBootstrapRequest({ schemaVersion: 1, operation: "bootstrap-existing-cut", idempotencyKey: randomUUID(),
    intent: documents.intent, candidate: { path: path.join(sourceRoot, "TEST-previsual-plan.json"), sha256: plan.sha256 },
    manifest: { path: path.join(sourceRoot, "source/asset_manifest.json"), sha256: manifest.sha256 } });
  return { workspace, sourceRoot, request, original: plan };
}

/** Run the production worker scope/outcome/lease. No quiescence, source, or gate is mocked. */
async function runTestWorker(jobPath: string, remainingMs: () => number) {
  remainingMs();
  const job = readAutoEditJob(jobPath);
  assert.ok(job); assert.equal(job.workerPid, process.pid);
  let critics = 0;
  await withWorkerMutationLease(job, (lease) => runBootstrapWorker(job, lease, () => {
    const send = (event: Record<string, unknown>) => appendAutoEditJobEvent(jobPath, job.token, event);
    const run: PipelineRuntime = { job, io: { send, sendRaw: (line) => send({ event: "TEST-log", line }),
      advance: diskCheckpointWriter(jobPath, job.token), invalidate: diskInvalidationWriter(jobPath, job.token) } };
    return settleWorkerExecution({ jobPath, token: job.token, send, stopHeartbeat: () => {}, run: () => runAutoEditPipeline(run, {
      author: async () => { throw new Error("TEST bootstrap must never invoke a writer"); },
      revise: async () => { throw new Error("TEST bootstrap must never revise its candidate"); },
      reviewCut: (current) => runCutReviewLoop(current, { review: async () => {
        critics++;
        return { provider: "codex", ms: 1, review: { schemaVersion: 1, stage: "cut", verdict: "pass",
          summary: `TEST ONLY independent cut critic${critics}; not creative judgment.`, materialIssues: [], findings: [] } };
      } }),
      prepareCutPreview: async (current, request) => {
        const { receipt } = await renderPrivateCutPreview({ job: current, request, lease, timeoutMs: Math.min(180_000, remainingMs()) });
        remainingMs();
        return { executionKey: receipt.executionKey, receiptHash: receipt.receiptHash };
      },
    }) });
  }));
  assert.equal(critics, 2);
  return critics;
}

export async function createV6ShortBootstrapFixture(t: TestContext, remainingMs: () => number) {
  const source = await sourceFixture(t, remainingMs);
  let launches = 0;
  t.mock.method(bootstrapServices, "launch", async (jobPath: string) => {
    assert.equal(++launches, 1, "new-only replay must not launch again");
    const job = readAutoEditJob(jobPath); assert.ok(job);
    // Capture this actual controller's PID/start identity, not an invented worker.
    markAutoEditWorker(jobPath, job.token, process.pid);
    return process.pid;
  });
  remainingMs();
  const result = await bootstrapGuidedProject(source.request), dir = result.producerDir;
  assert.equal(result.replayed, false);
  const jobPath = autoEditJobPath(dir), critics = await runTestWorker(jobPath, remainingMs);
  remainingMs();
  const status = readGuidedProjectBootstrapStatus(dir);
  assert.equal(status.state, "awaiting_cut_approval"); assert.ok(status.preview);
  assert.equal(status.cleanupUnknown, false); assert.equal(status.cutAccepted, false);
  assert.equal((await bootstrapGuidedProject(source.request)).replayed, true);
  assert.equal(readCutPreviewObject(source.request.candidate.path).sha256, source.original.sha256);
  const saved = readCutPreviewObject(path.join(dir, "edit_plan.json"));
  assert.deepEqual(saved.value, { ...source.original.value, planVersion: Number(source.original.value.planVersion) + 1 });
  return { ...source, dir, root: path.dirname(dir), jobPath, status, critics, saved };
}
