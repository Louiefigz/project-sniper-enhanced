import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, statSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { guidedFixture } from "@/lib/producer/__tests__/_guided-cut-fixture";
import { runAuthorStage } from "@/app/api/producer/auto-edit/authoring-stage";
import { renderPrivateCutPreview } from "@/app/api/producer/auto-edit/cut-preview";
import { pythonInterpreter, SCRIPTS_DIR } from "@/app/api/_lib/spawn-python";
import { acquireProjectMutationLease } from "../project-mutation-lease";
import { pauseAutoEditForCutApproval } from "../auto-edit-cut-pause-store";
import { markAutoEditWorker } from "../auto-edit-job-store";
import { prepareAutoEditRunContext } from "../auto-edit-pipeline-authority";
import { parseHumanCutSubmission } from "@/lib/producer/contracts/human-cut-acceptance";
import type { GuidedWorkflowV2 } from "@/lib/producer/contracts/guided-workflow-v2";
import { objectValue } from "@/lib/producer/contracts/validation";
import { currentCallerProcessDeadline } from "../caller-process-deadline";
import { runCutPreviewProcess } from "@/app/api/producer/auto-edit/cut-preview-process";

/** TEST ONLY. Real synthetic bytes and preview; admission decode/image facts and writer/critic replies are stubs.
 * Creates no human acceptance or final-delivery fact. The returned submission is test data only.
 * Optional existing workspace supports explicit browser-route tests; the project is always new.
 */
export type SyntheticProgram = "longform-96" | "longform-300" | "longform-body-300";

/** TEST ONLY initial documents, before any pipeline capture, cut request, or approval. */
export function captionedProgramDocuments(project: Record<string, unknown>, plan: Record<string, unknown>) {
  const intent = objectValue(project.intent, "TEST initial project intent"), target = objectValue(plan.target, "TEST initial plan target");
  const wanted = objectValue(intent.lanes, "TEST initial intent lanes"), actual = objectValue(target.lanes, "TEST initial target lanes");
  assert.equal(intent.mode, "longform"); assert.equal(target.mode, "longform");
  assert.equal(intent.scope, "produced"); assert.equal(target.scope, "produced");
  assert.equal(wanted.captions, "off"); assert.deepEqual(actual, wanted);
  return { project: { ...structuredClone(project), intent: { ...structuredClone(intent), lanes: { ...wanted, captions: "auto" } } },
    plan: { ...structuredClone(plan), target: { ...structuredClone(target), lanes: { ...actual, captions: "auto" } } } };
}

function authorInitialCaptionIntent(root: string): void {
  const planPath = path.join(root, "producer/edit_plan.json"), projectPath = path.join(root, "project.json");
  const docs = captionedProgramDocuments(JSON.parse(readFileSync(projectPath, "utf8")), JSON.parse(readFileSync(planPath, "utf8")));
  writeFileSync(projectPath, JSON.stringify(docs.project)); writeFileSync(planPath, JSON.stringify(docs.plan));
}

async function synthesizeProgram(root: string, producer: string, options: { sourceCanvas?: "160x90" | "1920x1080"; program?: SyntheticProgram }) {
  const args = [path.join(producer, "tests/_cut_preview_fixture.py"), root, "--canvas", options.sourceCanvas ?? "160x90"];
  if (options.program) args.push("--program", options.program);
  const started = performance.now();
  const caller = currentCallerProcessDeadline();
  const env = { ...process.env, PYTHONPATH: `${producer}${path.delimiter}${path.join(producer, "tests")}` };
  if (caller) {
    if (options.program) throw new Error("Bounded TEST synthesis supports only the original three-second class");
    // This is only a child-local cap. The runner re-reads the original parent deadline at spawn.
    const handedRemainingMs = Math.min(20_000, currentCallerProcessDeadline()!.timeoutMs);
    await runCutPreviewProcess({ command: pythonInterpreter(), cwd: producer, env, timeoutMs: 20_000,
      args: [path.join(producer, "tests/_bounded_cut_preview_fixture.py"), root, options.sourceCanvas ?? "160x90", String(handedRemainingMs)] });
  } else execFileSync(pythonInterpreter(), args, { env,
    timeout: options.program ? 240_000 : options.sourceCanvas === "1920x1080" ? 30_000 : 20_000 });
  return performance.now() - started;
}

/** TEST ONLY before any source/cut pin: project the hashed silent video with its TEST admission receipt as b-roll. */
function selectInitialPresentationAsset(manifestPath: string): void {
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  assert.deepEqual(manifest.sources.map((row: Record<string, unknown>) => row.id), ["raw-1", "silent"]);
  assert.equal(manifest.broll, undefined);
  const row = manifest.sources[1]; assert.equal(row.transcriptPath, undefined);
  manifest.sources = manifest.sources.slice(0, 1);
  manifest.broll = [{ ...row, id: "presentation-1", kind: "video", sourceSizeBytes: statSync(row.path).size }];
  writeFileSync(manifestPath, JSON.stringify(manifest));
}

export async function createHumanCutFixture(options: { workspace?: string; workflowV2?: GuidedWorkflowV2; sourceCanvas?: "160x90" | "1920x1080";
  program?: SyntheticProgram; captionIntent?: "auto"; graphicsOff?: boolean; presentationAsset?: "admitted-silent-video"; nativeShort?: boolean;
  transcriptVariant?: "numeric-comparison" } = {}) {
  if (options.transcriptVariant !== undefined && options.transcriptVariant !== "numeric-comparison") throw new Error("Unknown TEST transcript variant");
  if (options.transcriptVariant && (options.program || options.nativeShort)) throw new Error("TEST numeric transcript cannot retrofit a program or native Short");
  if (options.program && (options.graphicsOff || options.presentationAsset)) throw new Error("TEST presentation/graphics-off options belong only to a new three-second fixture");
  if (options.captionIntent && options.program !== "longform-body-300") throw new Error("TEST captioned program requires the original five-minute body class");
  const workspace = realpathSync(options.workspace ?? mkdtempSync(path.join(os.tmpdir(), "sniper-human-cut-")));
  const root = path.join(workspace, `test-only-cut-review-${randomUUID().slice(0, 8)}`);
  if (existsSync(root)) throw new Error("Synthetic cut-review fixture cannot reuse an existing project");
  const originalWorkspace = process.env.SNIPER_WORKSPACE_ROOT;
  process.env.SNIPER_WORKSPACE_ROOT = workspace;
  const producer = path.join(SCRIPTS_DIR, "producer");
  // A Python-first program authors media, transcript, cut and intent BEFORE the TS fixture reads them.
  const synthesisMs = options.program ? await synthesizeProgram(root, producer, options) : null;
  if (options.captionIntent) authorInitialCaptionIntent(root);
  const fixture = guidedFixture(root, options.workflowV2, { reuseAuthored: options.program !== undefined, graphicsOff: options.graphicsOff, nativeShort: options.nativeShort, transcriptVariant: options.transcriptVariant });
  writeFileSync(path.join(root, "SYNTHETIC-TEST-ONLY.json"), JSON.stringify({
    schemaVersion: 1, synthetic: true, creativeQualityQualified: false, humanAccepted: false,
    externalAdmission: "TEST-stubbed decode/image facts; real generated bytes, snapshot hashes and source-set joins",
    modelCalls: 0, independentCritics: "TEST-ONLY stubs, not editorial judgment",
    program: options.program ?? "default-3s", synthesisMs, captionIntent: options.captionIntent ?? null,
    transcriptVariant: options.transcriptVariant ?? (options.program ? "program-authored" : "original-statement"),
    purpose: "Cut-review UI transport, authority and process tests only; never delivery evidence",
  }));
  if (!options.program) await synthesizeProgram(root, producer, options);
  if (options.presentationAsset) selectInitialPresentationAsset(fixture.ctx.manifestPath);
  Object.assign(fixture.ctx, prepareAutoEditRunContext({ ctx: fixture.ctx, runId: fixture.run.job.token, resume: false }));
  writeFileSync(fixture.jobPath, JSON.stringify(fixture.run.job));
  // A browser can observe a long fixture before setup completes. Register the real
  // fixture controller so normal orphan recovery cannot misclassify it as ownerless.
  Object.assign(fixture.run.job, markAutoEditWorker(fixture.jobPath, fixture.run.job.token, process.pid));
  const result = await runAuthorStage(fixture.run, fixture.deps);
  if (result.status !== "awaiting_cut_approval") throw new Error("Missing synthetic cut request");
  const { lease } = acquireProjectMutationLease(root, "TEST-ONLY synthetic cut-preview qualification");
  assert.ok(lease);
  try {
    const { receipt } = await renderPrivateCutPreview({ job: fixture.run.job, request: result.request, lease, timeoutMs: options.program ? 240_000 : 30_000 });
    const waiting = pauseAutoEditForCutApproval(fixture.jobPath, fixture.run.job.token, result.request,
      { executionKey: receipt.executionKey, receiptHash: receipt.receiptHash });
    const submission = parseHumanCutSubmission({ schemaVersion: 1, operation: "accept", idempotencyKey: randomUUID(),
      expectedToken: waiting.token, requestHash: result.request.requestHash, executionKey: receipt.executionKey,
      receiptHash: receipt.receiptHash, mediaSha256: receipt.media.sha256,
      attestation: { watched: true, listened: true, acceptsExactCut: true, acknowledgesUnfinished: true } });
    return { ...fixture, root, receipt, submission, cleanup: () => {
      if (originalWorkspace === undefined) delete process.env.SNIPER_WORKSPACE_ROOT;
      else process.env.SNIPER_WORKSPACE_ROOT = originalWorkspace;
      rmSync(options.workspace ? root : workspace, { recursive: true, force: true });
    } };
  } finally { lease.release(); }
}
