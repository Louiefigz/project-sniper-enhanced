import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  assertSurgicalReviewCurrent,
  beginSurgicalReview,
  finalizeSurgicalEdit,
  rollbackSurgicalEdit,
} from "../../../app/api/producer/ai-edit/finalize";
import {
  assertNoPromotionReconciliation,
  SURGICAL_RECONCILIATION_CANDIDATE_FILE,
  SURGICAL_RECONCILIATION_FILE,
} from "../../../app/api/producer/ai-edit/promotion-recovery";
import type { ProducerReview } from "../../../app/api/producer/auto-edit/review-contract";
import { surgicalAuthorityFailure } from
  "../../../app/api/producer/ai-edit/prepare";
import { guardProjectMutation } from
  "../../../app/api/_lib/project-mutation";

const review: ProducerReview = {
  schemaVersion: 1,
  stage: "plan",
  verdict: "pass",
  summary: "The isolated candidate is ready.",
  materialIssues: [],
  findings: [],
};

interface Fixture {
  dir: string;
  authorityPath: string;
  candidatePath: string;
  manifestPath: string;
  parentText: string;
}

function sha256(value: string | Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}

function fixture(): Fixture {
  const dir = mkdtempSync(path.join(os.tmpdir(), "sniper-ask-edit-cas-"));
  const authorityPath = path.join(dir, "edit_plan.json");
  const candidatePath = path.join(dir, "isolated-candidate.json");
  const manifestPath = path.join(dir, "asset_manifest.json");
  const parentText = `${JSON.stringify({
    planVersion: 4,
    target: { mode: "longform" },
    cutTrack: [{ sourceId: "source-1", start: 0, end: 10 }],
    graphicsTrack: [],
  }, null, 2)}\n`;
  writeFileSync(authorityPath, parentText);
  writeFileSync(manifestPath, JSON.stringify({ sources: [] }));
  return { dir, authorityPath, candidatePath, manifestPath, parentText };
}

function stageCandidate(item: Fixture, title: string): void {
  writeFileSync(item.candidatePath, JSON.stringify({
    planVersion: 4,
    target: { mode: "longform" },
    cutTrack: [{ sourceId: "source-1", start: 0, end: 10 }],
    graphicsTrack: [{
      outStart: 2,
      outEnd: 5,
      kind: "line-swap",
      anchor: "own-screen",
      reason: "Clarify the thesis",
      spec: { lineA: title, lineB: "The TEST result", underlineWord: "result" },
    }],
  }));
  beginSurgicalReview(item.dir, { lanes: ["graphics"] });
}

function input(item: Fixture) {
  return {
    provider: "codex" as const,
    dir: item.dir,
    planPath: item.candidatePath,
    authorityPlanPath: item.authorityPath,
    manifestPath: item.manifestPath,
    transcriptsDir: item.dir,
    request: "Add a title card",
    scope: { lanes: ["graphics" as const] },
    originalPlanText: item.parentText,
    parentPlanHash: sha256(item.parentText),
  };
}

async function failedCandidatePreservesParent(): Promise<void> {
  const item = fixture();
  try {
    stageCandidate(item, "Rejected candidate");
    await assert.rejects(
      finalizeSurgicalEdit(input(item), {
        governance: async () => {
          throw new Error("candidate gate failed");
        },
        critic: async () => review,
      }),
      /candidate gate failed/,
    );
    assert.equal(readFileSync(item.authorityPath, "utf8"), item.parentText);
    assert.equal(existsSync(item.candidatePath), false);
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function externalChangeDefeatsPromotion(): Promise<void> {
  const item = fixture();
  const externalText = `${JSON.stringify({
    planVersion: 5,
    target: { mode: "longform" },
    cutTrack: [{ sourceId: "source-1", start: 0, end: 9 }],
    graphicsTrack: [],
    manualEdit: true,
  }, null, 2)}\n`;
  try {
    stageCandidate(item, "Stale candidate");
    await assert.rejects(
      finalizeSurgicalEdit(input(item), {
        governance: async () => ({ warnings: [] }),
        critic: async () => {
          writeFileSync(item.authorityPath, externalText);
          return review;
        },
      }),
      /changed during Ask Editor candidate work/,
    );
    assert.equal(readFileSync(item.authorityPath, "utf8"), externalText);
    assert.equal(existsSync(item.candidatePath), false);
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function exactParentPromotes(): Promise<void> {
  const item = fixture();
  try {
    stageCandidate(item, "Promoted candidate");
    await finalizeSurgicalEdit(input(item), {
      governance: async () => ({ warnings: [] }),
      critic: async () => review,
    });
    assert.match(readFileSync(item.authorityPath, "utf8"), /Promoted candidate/);
    assert.equal(existsSync(item.candidatePath), false);
    assert.doesNotThrow(() => assertSurgicalReviewCurrent(item.authorityPath));
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function postPromotionFailureRestoresParent(): Promise<void> {
  const item = fixture();
  const finalizer = input(item);
  try {
    stageCandidate(item, "Temporary promoted candidate");
    await assert.rejects(
      finalizeSurgicalEdit(finalizer, {
        governance: async () => ({ warnings: [] }),
        critic: async () => review,
        afterPromotion: (authorityPath) => {
          assert.match(readFileSync(authorityPath, "utf8"), /Temporary promoted candidate/);
          throw new Error("injected failure immediately after promotion");
        },
      }),
      /injected failure immediately after promotion/,
    );
    assert.equal(readFileSync(item.authorityPath, "utf8"), item.parentText);
    assert.equal(existsSync(item.candidatePath), false);
    assert.equal(existsSync(path.join(item.dir, SURGICAL_RECONCILIATION_FILE)), false);
    const externalAfterRecovery = `${item.parentText.trimEnd()}\n \n`;
    writeFileSync(item.authorityPath, externalAfterRecovery);
    rollbackSurgicalEdit(finalizer);
    assert.equal(readFileSync(item.authorityPath, "utf8"), externalAfterRecovery,
      "the outer stream rollback cannot repeat a settled post-promotion restore");
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

async function changedAuthorityRefusesPostPromotionRestore(): Promise<void> {
  const item = fixture();
  const externalText = `${JSON.stringify({
    planVersion: 9,
    target: { mode: "longform" },
    cutTrack: [{ sourceId: "source-1", start: 1, end: 8 }],
    graphicsTrack: [],
    externalChangeAfterPromotion: true,
  }, null, 2)}\n`;
  const finalizer = input(item);
  try {
    stageCandidate(item, "Promoted before conflict");
    await assert.rejects(
      finalizeSurgicalEdit(finalizer, {
        governance: async () => ({ warnings: [] }),
        critic: async () => review,
        afterPromotion: (authorityPath) => {
          writeFileSync(authorityPath, externalText);
          throw new Error("injected post-promotion failure");
        },
      }),
      /manual reconciliation required, and no authority bytes were overwritten/,
    );
    assert.equal(readFileSync(item.authorityPath, "utf8"), externalText);
    assert.equal(existsSync(item.candidatePath), true, "candidate evidence is preserved");
    const evidencePath = path.join(item.dir, SURGICAL_RECONCILIATION_FILE);
    const evidence = JSON.parse(readFileSync(evidencePath, "utf8")) as {
      promotedChildHash: string;
      observedAuthorityHash: string;
      triggeringFailure: string;
      retainedCandidatePath: string;
    };
    assert.equal(evidence.observedAuthorityHash, sha256(externalText));
    assert.notEqual(evidence.promotedChildHash, evidence.observedAuthorityHash);
    assert.match(evidence.triggeringFailure, /injected post-promotion failure/);
    const retainedPath = path.join(
      item.dir, SURGICAL_RECONCILIATION_CANDIDATE_FILE,
    );
    assert.equal(evidence.retainedCandidatePath, retainedPath);
    assert.equal(sha256(readFileSync(retainedPath)), evidence.promotedChildHash);
    assert.throws(
      () => assertNoPromotionReconciliation(item.dir),
      /unresolved post-promotion conflict/,
    );
    const blocked = await surgicalAuthorityFailure(item.dir);
    assert.equal(blocked?.status, 409);
    const globalBlock = guardProjectMutation({
      projectRoot: item.dir,
      producerDir: item.dir,
      operation: "saving timeline changes",
    });
    assert.equal(globalBlock.response?.status, 409);
    rollbackSurgicalEdit(finalizer);
    assert.equal(readFileSync(item.authorityPath, "utf8"), externalText);
    assert.equal(existsSync(item.candidatePath), true,
      "the outer stream rollback must preserve reconciliation evidence");
    assert.throws(() => assertSurgicalReviewCurrent(item.authorityPath), /awaiting/);
  } finally {
    rmSync(item.dir, { recursive: true, force: true });
  }
}

failedCandidatePreservesParent()
  .then(externalChangeDefeatsPromotion)
  .then(exactParentPromotes)
  .then(postPromotionFailureRestoresParent)
  .then(changedAuthorityRefusesPostPromotionRestore)
  .then(() => console.log("ask-edit-authority-cas.test.ts: all assertions passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
