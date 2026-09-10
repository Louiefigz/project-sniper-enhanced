/** Explicit expensive TEST integration only. No user project input, live brains, or delivery approval. */
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, realpathSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { createOpeningReadyFixture } from "./_guided-opening-media-fixture";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { openingMediaAuthority, assertFullProgramMediaMetadata } from "../guided-opening-media-input";
import { assertBodyGraphWorkload } from "@/lib/producer/contracts/guided-body-media-v1";
import { bodyLiveRuntimeControls, newBodyLiveLog,
  retainBodyLive, timedBodyLive, type BodyLiveLog } from "./_guided-body-live-support";
import { BODY_LIVE_TEST_SCOPE as SCOPE, launchLiveOpening, approveLiveSynthetic, generateLiveBody } from "./_guided-body-live-flow";
const HELP = { usage: "node --import tsx src/lib/server/__tests__/_guided-body-live-fixture.ts --help|--check-controls|--run|--run-captioned",
  scope: SCOPE, genuineHumanAcceptance: false, profile: "longform-body-300 / actual 1920x1080 / real deterministic gates",
  models: "existing TEST compiler/critic responses only; no paid API or live model calls",
  estimatedMinutes: "Unqualified: last opening/admission-only attempt took 12 minutes 29 seconds; this run measures the full private candidate",
  requires: "Explicit runtime controls and coordinated source stability through body render, cleanup and readback",
  stop: "A failed/unknown launch retains its claim; this driver never retries, cancels the detached controller, or infers cleanup",
  result: "Actual private body candidate and QC, never public final, genuine creator acceptance or delivery approval" };

export function parseBodyLiveMode(argv: string[]): "help" | "check-controls" | "run" | "run-captioned" {
  if (argv.length === 0 || (argv.length === 1 && argv[0] === "--help")) return "help";
  if (argv.length === 1 && argv[0] === "--check-controls") return "check-controls";
  if (argv.length === 1 && argv[0] === "--run") return "run";
  if (argv.length === 1 && argv[0] === "--run-captioned") return "run-captioned";
  throw new Error("Only --help, --check-controls, --run or --run-captioned is accepted; existing projects are forbidden");
}

/** The created project and marker are mandatory before any synthetic attestation is submitted. */
export function assertBodyLiveSynthetic(log: BodyLiveLog, dir: string): void {
  assert.equal(realpathSync(dir), dir);
  assert.equal(path.dirname(path.dirname(dir)), log.workspace);
  assert.match(path.basename(path.dirname(dir)), /^test-only-cut-review-[a-f0-9]{8}$/);
  assert.equal(path.basename(dir), "producer");
  const marker = readCutPreviewObject(path.join(path.dirname(dir), "SYNTHETIC-TEST-ONLY.json")).value;
  assert.equal(marker.synthetic, true); assert.equal(marker.program, "longform-body-300");
  assert.equal(marker.modelCalls, 0); assert.equal(marker.humanAccepted, false); assert.equal(marker.creativeQualityQualified, false);
}

function protectedState(dir: string) {
  const job = observeHumanCutJob(dir).job;
  for (const name of ["final.mp4", ".sniper-qc-approved.json"]) assert.equal(existsSync(path.join(dir, name)), false, `${name} must remain absent`);
  return { planSha256: readCutPreviewObject(job.ctx.planPath).sha256, manifestSha256: readCutPreviewObject(job.ctx.manifestPath).sha256,
    pictureLockedRevisionHash: job.guidedHandoffV2?.pictureLockedRevisionHash };
}


/** Expensive opt-in; never accepts a caller-selected existing producer directory. */
export async function runBodyLiveFixture(captioned = false) {
  const controls = bodyLiveRuntimeControls();
  const workspace = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-body-live-"))), log = newBodyLiveLog(workspace);
  const previousWorkspace = process.env.SNIPER_WORKSPACE_ROOT;
  process.env.SNIPER_WORKSPACE_ROOT = workspace;
  retainBodyLive(log, "test-scope.json", { ...HELP, workspace, controls, captioned, startedAt: new Date().toISOString() });
  process.stderr.write(`TEST-only retained workspace: ${workspace}\n`);
  try {
    const { fixture, proposal } = await timedBodyLive(log, "fresh-source-preview-proposal-readiness", () => createOpeningReadyFixture({
      workspace, program: "longform-body-300", sourceCanvas: "1920x1080", realGates: true,
      ...(captioned ? { captionPreset: "producer-config-line-v1" as const } : {}) }));
    const dir = fixture.ctx.dir; assertBodyLiveSynthetic(log, dir);
    retainBodyLive(log, "project.json", { dir, root: fixture.root, scope: SCOPE, genuineHumanAcceptance: false });
    const media = openingMediaAuthority(proposal);
    assertFullProgramMediaMetadata({ plan: proposal.result.candidate!, bindings: media.bindings });
    assertBodyGraphWorkload(media.authority.target, media.bindings.graphics.length);
    retainBodyLive(log, "all-body-metadata-preflight.json", {
      scope: "TEST-all-row-profile-workload-before-opening-not-template-media-or-approval-proof",
      candidatePlanHash: media.authority.candidatePlanHash, graphicCount: media.bindings.graphics.length,
      bodyGenerated: false, deliveryApproved: false });
    const scope = { log, dir, assertSynthetic: () => assertBodyLiveSynthetic(log, dir) };
    const protectedBefore = protectedState(dir), selected = await launchLiveOpening(log, dir);
    const approved = await approveLiveSynthetic(scope, selected), body = await generateLiveBody(scope, approved, captioned);
    assert.deepEqual(protectedState(dir), protectedBefore);
    const result = { state: "TEST-chain-passed-private-body-candidate", scope: SCOPE, workspace, dir,
      genuineHumanAcceptance: false, creativeQualityQualified: false, bodyGenerated: true,
      bodyApproved: false, deliveryApproved: false, captioned, elapsedMs: performance.now() - log.began, body };
    retainBodyLive(log, "result.json", result); return result;
  } catch (error) {
    retainBodyLive(log, "failed.json", { scope: SCOPE, workspace, genuineHumanAcceptance: false, error: String(error).slice(0, 8000),
      elapsedMs: performance.now() - log.began, artifactsPreserved: true, ownership: "read actual retained controller/claim evidence; never inferred idle", automaticRetry: false });
    throw error;
  } finally {
    if (previousWorkspace === undefined) delete process.env.SNIPER_WORKSPACE_ROOT;
    else process.env.SNIPER_WORKSPACE_ROOT = previousWorkspace;
  }
}

export async function bodyLiveMain(argv: string[]) {
  const mode = parseBodyLiveMode(argv);
  if (mode === "help") return HELP;
  if (mode === "check-controls") return bodyLiveRuntimeControls();
  return runBodyLiveFixture(mode === "run-captioned");
}

if (require.main === module) bodyLiveMain(process.argv.slice(2)).then((result) => {
  process.stdout.write(JSON.stringify(result) + "\n");
}).catch((error) => { process.stderr.write(JSON.stringify({ ok: false, error: String(error) }) + "\n"); process.exitCode = 1; });
