import assert from "node:assert/strict";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { planContentHash } from "../../server/auto-edit-authority";
import { fileSha256 } from "../../server/auto-edit-job-store";
import {
  approvalPath,
  candidateFinalPath,
  prepareQcRound,
  previewStalePath,
} from "../../server/auto-edit-quality-artifacts";
import type { RenderGraphPromotionRuntime } from
  "../../server/current-render-graph-candidate";
import { writeApprovalFixture } from "./auto-edit-approval-fixture";

interface PromotionFixture {
  root: string;
  producer: string;
  candidate: string;
  candidateHash: string;
  record: ReturnType<typeof writeApprovalFixture>;
}

const OLD_MEDIA = "prior-live-media";
const OLD_PROOF = "prior-live-proof";
const OLD_APPROVAL = "prior-live-approval";
const OLD_DIAGNOSTIC = "prior-live-diagnostic";
const GRAPH_HASH = "a".repeat(64);
const RECEIPT_HASH = "b".repeat(64);
const POINTER_HASH = "c".repeat(64);
export const REVISION_HASH = "d".repeat(64);

export function fixture(name: string): PromotionFixture {
  const root = mkdtempSync(path.join(
    os.tmpdir(), `sniper-graph-promotion-${name}-`));
  const producer = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(source, { recursive: true });
  prepareQcRound(producer, name, 1);
  writeFileSync(
    path.join(producer, "edit_plan.json"),
    '{"planVersion":1,"cutTrack":[]}',
  );
  writeFileSync(path.join(source, "manifest.json"), '{"sources":[]}');
  const candidate = candidateFinalPath(producer, name, 1);
  writeFileSync(candidate, "candidate-media");
  const candidateHash = fileSha256(candidate)!;
  writeFileSync(`${candidate}.assembled.json`, JSON.stringify({
    planHash: planContentHash(path.join(producer, "edit_plan.json")),
    authorityHash: candidateHash,
  }));
  const record = writeApprovalFixture({
    ctx: {
      dir: producer,
      scope: "light",
      planPath: path.join(producer, "edit_plan.json"),
      manifestPath: path.join(source, "manifest.json"),
      transcriptsDir: source,
    },
    token: name,
    candidate,
    qcRound: 1,
  });
  writeFileSync(path.join(producer, "final.mp4"), OLD_MEDIA);
  writeFileSync(path.join(producer, "final.mp4.assembled.json"), OLD_PROOF);
  writeFileSync(path.join(producer, "audit_report.json"), OLD_DIAGNOSTIC);
  writeFileSync(approvalPath(producer), OLD_APPROVAL);
  writeFileSync(previewStalePath(producer), "prior-stale-marker");
  return { root, producer, candidate, candidateHash, record };
}

export function action(args: string[]): string {
  return args[0] ?? "";
}

export function authorityRuntime(
  input: RenderGraphPromotionRuntime,
): RenderGraphPromotionRuntime {
  const command = input.command ?? (() => ({ ok: true }));
  return {
    ...input,
    command: (args) => ({
      ...command(args),
      ...(action(args) === "verify" ? { graphHash: GRAPH_HASH } : {}),
    }),
    stagedObserver: input.stagedObserver ?? ((expectation) => ({
      graphHash: GRAPH_HASH,
      receiptHash: RECEIPT_HASH,
      candidatePointerHash: POINTER_HASH,
      candidateMediaHash: expectation.expectedCandidateHash,
      previousGraphHash: null,
      previousReceiptHash: null,
    })),
    activeObserver: input.activeObserver ?? ((expectation) => ({
      graphHash: expectation.expectedGraphHash,
      receiptHash: RECEIPT_HASH,
      activePointerHash: POINTER_HASH,
      finalMediaHash: expectation.expectedFinalHash,
    })),
    qcPreparation: input.qcPreparation ?? ((producerDir) => ({
      producerDir,
      parentRevisionHash: REVISION_HASH,
      expectedApprovedHead: null,
      mutablePaths: [],
    })),
    qcCommit: input.qcCommit ?? (() => ({
      status: "committed",
      childRevisionHash: REVISION_HASH,
    })),
  };
}

export function assertRolledBack(item: PromotionFixture): void {
  assert.equal(readFileSync(item.candidate, "utf8"), "candidate-media");
  assert.equal(fileSha256(item.candidate), item.candidateHash);
  assert.ok(existsSync(`${item.candidate}.assembled.json`));
  assert.equal(
    readFileSync(path.join(item.producer, "final.mp4"), "utf8"),
    OLD_MEDIA,
  );
  assert.equal(
    readFileSync(path.join(
      item.producer, "final.mp4.assembled.json"), "utf8"),
    OLD_PROOF,
  );
  assert.equal(
    readFileSync(path.join(item.producer, "audit_report.json"), "utf8"),
    OLD_DIAGNOSTIC,
  );
  assert.equal(readFileSync(approvalPath(item.producer), "utf8"), OLD_APPROVAL);
  assert.equal(
    readFileSync(previewStalePath(item.producer), "utf8"),
    "prior-stale-marker",
  );
}
