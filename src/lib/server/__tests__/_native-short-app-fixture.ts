/** Tiny stored-journal/manifest fixture; deep proposal reconstruction alone is stubbed. */
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { guidedFixture } from "@/lib/producer/__tests__/_guided-cut-fixture";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { autoEditRequestKey, canonicalJsonSha256, fileSha256 } from "../auto-edit-hash";
import { parseAutoEditJobRecord } from "../auto-edit-job-persistence";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { clearProducerRun } from "../producer-run-registry";
import type { readGuidedTreatmentProposal } from "../guided-proposal-store";

const HASH = "a".repeat(64);

function writeInventory(directory: string) {
  mkdirSync(directory, { recursive: true });
  const source = path.join(directory, "source.mp4"), picture = path.join(directory, "provided.png");
  writeFileSync(source, "TEST tiny source bytes; no media decode");
  writeFileSync(picture, "TEST supplied image bytes");
  writeFileSync(path.join(directory, "transcript.json"), '{"words":[]}');
  const receipt = "TEST retained admission shape; no sandbox job runs here";
  const temporary = path.join(directory, "receipt.json"); writeFileSync(temporary, receipt);
  const receiptHash = fileSha256(temporary)!, receiptPath = `.sniper-source-sets/${receiptHash}.json`;
  mkdirSync(path.dirname(path.join(directory, receiptPath))); writeFileSync(path.join(directory, receiptPath), receipt);
  const manifest = { sources: [{ id: "raw-1", path: source, sourceSha256: fileSha256(source), duration: 3,
    resolution: [1920, 1080], fps: 30, transcriptPath: "transcript.json" }],
    broll: [{ id: "supplied", path: "provided.png", sourceSha256: fileSha256(picture) }], music: [],
    sourceSetAdmission: { schemaVersion: 1, receiptPath, receiptSha256: receiptHash, sourceSetDigest: HASH, entryCount: 2 } };
  const manifestPath = path.join(directory, "asset_manifest.json"); writeFileSync(manifestPath, JSON.stringify(manifest));
  return { manifestPath, source, picture };
}

export function nativeShortAppFixture(externalManifest = false) {
  const workspace = realpathSync(mkdtempSync(path.join(os.tmpdir(), "native-short-app-"))), root = path.join(workspace, "project");
  mkdirSync(root);
  const f = guidedFixture(root, { schemaVersion: 2, mode: "guided", afterCut: "treatment-then-intro",
    approvalPolicy: "explicit-human" }, { nativeShort: true });
  const inventory = writeInventory(externalManifest ? path.join(workspace, "bootstrap-admitted") : path.join(root, "source"));
  const job = structuredClone(f.run.job), now = new Date().toISOString();
  job.ctx.manifestPath = inventory.manifestPath; job.ctx.transcriptsDir = path.dirname(inventory.manifestPath);
  const intent = job.ctx.intent; if (!intent) throw new Error("TEST guided fixture needs stored intent");
  intent.shortDirection = { selection: "auto", supportingVideo: "source-first",
    mediaPolicy: { placement: "auto", sources: "provided-only" } };
  job.requestKey = autoEditRequestKey(job.ctx);
  const request = { schemaVersion: 1 as const, requestKey: job.requestKey, planHash: HASH, authorityDigest: HASH,
    cutAuthorityDigest: HASH, cutApprovalReceiptHash: HASH, cutReviewApprovalReceiptHash: HASH,
    pictureLockHash: HASH, timelineMapHash: HASH, projectionReceiptHash: HASH, createdAt: now };
  Object.assign(job, { status: "treatment_admitted", checkpoint: "cut_reviewed", workerPid: undefined, workerIdentity: undefined,
    cutApprovalWaitStartedAt: now, cutApprovalRequest: { ...request, requestHash: canonicalJsonSha256(request) },
    cutPreview: { executionKey: HASH, receiptHash: HASH }, guidedHandoffV2: { schemaVersion: 2,
      cutDecisionHash: HASH, cutActivationHash: HASH, pictureLockedRevisionHash: HASH,
      treatmentAdmissionHash: HASH, treatmentProposalHash: HASH } });
  parseAutoEditJobRecord(job); writeFileSync(f.jobPath, JSON.stringify(job));
  // A different ordinary project intent must not replace the guided job's narrower source policy.
  const ordinary = structuredClone(intent); ordinary.shortDirection!.mediaPolicy!.sources = "public-web";
  writeFileSync(path.join(root, "project.json"), JSON.stringify({ origin: "raw", history: [], intent: ordinary }));
  const priorWorkspace = process.env.SNIPER_WORKSPACE_ROOT; process.env.SNIPER_WORKSPACE_ROOT = workspace;
  return { ...f, ...inventory, workspace, root, job, dir: f.ctx.dir,
    requests: path.join(f.ctx.dir, "native-shorts/requests"),
    cleanup: () => { clearProducerRun(f.ctx.dir); rmSync(workspace, { recursive: true, force: true });
      if (priorWorkspace === undefined) delete process.env.SNIPER_WORKSPACE_ROOT; else process.env.SNIPER_WORKSPACE_ROOT = priorWorkspace; } };
}

/** The service still performs actual packet writing, inventory hashing and manifest authority checks. */
export function nativeProposalObservation(f: ReturnType<typeof nativeShortAppFixture>): ReturnType<typeof readGuidedTreatmentProposal> {
  const observed = observeHumanCutJob(f.dir);
  const proposal = { ...observed, manifest: readCutPreviewObject(observed.job.ctx.manifestPath), proposalHash: HASH,
    evidence: { kind: "TEST-only-stubbed-proposal-evidence", version: 1 },
    result: { proposal: { schemaVersion: 9 }, blockers: [], candidate: { executionRoute: "native-short-v1" } } };
  return proposal as unknown as ReturnType<typeof readGuidedTreatmentProposal>;
}

export function readNativeAppPacket(directory: string) {
  return JSON.parse(readFileSync(path.join(directory, "SHORT-REQUEST.json"), "utf8"));
}
