import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import {
  parseProjectRevision,
  type ProjectRevisionV2,
} from "@/lib/producer/contracts/project-revision";
import type { ApprovalRecord } from "../auto-edit-approval";
import { approvalPath } from "../auto-edit-quality-artifacts";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
  writeAuthorityObjectSync,
} from "../producer-authority-files";
import {
  commitProducerQcPromotionSync,
  prepareProducerQcPromotionSync,
} from "../producer-qc-promotion";
import { qcPromotionIntentPath } from
  "../producer-qc-promotion-intent";
import {
  resolveProducerApprovedHeadSync,
  resolveProducerAuthorityHeadSync,
} from "../producer-revision-head";
import { commitProducerRevisionSync } from "../producer-revision-store";
import {
  bootstrapRevisionFixture,
  cleanRevisionFixture,
  revisionCommitInput,
} from "./_producer-revision-fixture";

const hash = (value: string): string => createHash("sha256")
  .update(value).digest("hex");

function revision(producer: string, revisionHash: string): ProjectRevisionV2 {
  const paths = producerAuthorityPaths(producer);
  const value = parseProjectRevision(
    assertObjectHashSync(paths.objects.revisions, revisionHash));
  if (value.schemaVersion !== 2) throw new Error("expected V2 revision");
  return value;
}

function artifact(name: string) {
  return { path: path.join("/private/tmp", name), hash: hash(name) };
}

function approval(
  parent: ProjectRevisionV2,
  finalHash: string,
  name: string,
): ApprovalRecord {
  const authorityDigest = hash(`${name}-authority`);
  const candidateHash = finalHash;
  const assembledProofHash = hash(`${name}-assembly`);
  const audit = {
    candidateHash,
    assembledProofHash,
    machine: artifact(`${name}-audit.json`),
    report: artifact(`${name}-audit.md`),
    frames: [artifact(`${name}-frame.png`)],
    digest: hash(`${name}-audit-digest`),
  };
  return {
    schemaVersion: 2,
    qualityPolicyVersion: 1,
    authorityDigest,
    planHash: parent.planContentHash,
    manifestHash: parent.manifestHash,
    finalHash,
    candidateHash,
    assembledProofHash,
    qcRound: 1,
    approvedAt: "2026-07-29T12:00:00.000Z",
    planningRoundsRequired: 1,
    planningReviews: [{
      round: 1,
      authorityDigest,
      planHash: parent.planContentHash,
      packet: artifact(`${name}-packet.json`),
      gates: artifact(`${name}-gates.json`),
      review: artifact(`${name}-planning-review.json`),
    }],
    renderedReviews: [
      { ...artifact(`${name}-composition.json`), lens: "composition" },
      { ...artifact(`${name}-editorial.json`), lens: "editorial" },
    ],
    audit,
    qualitySummary: artifact(`${name}-summary.json`),
  };
}

function graph(
  producer: string,
  parent: ProjectRevisionV2,
  finalHash: string,
  name: string,
) {
  const paths = producerAuthorityPaths(producer);
  const storedGraph = writeAuthorityObjectSync(paths.objects.graphs, {
    schemaVersion: 1,
    graphId: `qc-${name}`,
    toolchainHash: hash(`${name}-toolchain`),
    rootNodeId: "node-final",
    nodes: [{
      nodeId: "node-final",
      kind: "final-export",
      dependencies: [],
      inputDigests: { "final.plan": parent.planContentHash },
      outputArtifactHash: finalHash,
      frameRange: null,
    }],
  });
  const receipt = {
    schemaVersion: 1,
    kind: "qc-test-receipt",
    graphHash: storedGraph.hash,
  };
  const receiptHash = canonicalJsonSha256(receipt);
  const pointer = {
    schemaVersion: 1,
    graphHash: storedGraph.hash,
    receiptHash,
  };
  const activePointerHash = canonicalJsonSha256(pointer);
  const graphRoot = path.join(
    producer, ".render-graph-v1", "generations", storedGraph.hash);
  fs.mkdirSync(path.join(graphRoot, "receipts"), { recursive: true });
  fs.writeFileSync(
    path.join(graphRoot, "receipts", `${receiptHash}.json`),
    `${JSON.stringify(receipt)}\n`,
  );
  fs.writeFileSync(
    path.join(producer, ".render-graph-v1", "ACTIVE.json"),
    `${JSON.stringify(pointer)}\n`,
  );
  return {
    graphHash: storedGraph.hash,
    receiptHash,
    activePointerHash,
    finalMediaHash: finalHash,
  };
}

function publishApproval(producer: string, value: ApprovalRecord): void {
  fs.writeFileSync(
    approvalPath(producer),
    `${JSON.stringify(value, null, 2)}\n`,
  );
}

function approvalAdvancesExactPlanAndReplays(): void {
  const fixture = bootstrapRevisionFixture();
  try {
    const parent = revision(fixture.producer, fixture.genesis);
    const finalHash = hash("approved-final");
    const record = approval(parent, finalHash, "basic");
    const currentGraph = graph(
      fixture.producer, parent, finalHash, "basic");
    const preparation = prepareProducerQcPromotionSync(fixture.producer, {
      graphHash: currentGraph.graphHash,
      approval: record,
    });
    publishApproval(fixture.producer, record);
    const input = {
      preparation,
      graph: currentGraph,
      approval: record,
    };
    const committed = commitProducerQcPromotionSync(input);
    assert.equal(committed.status, "committed");
    const child = revision(fixture.producer, committed.childRevisionHash);
    assert.equal(child.parentRevisionHash, fixture.genesis);
    assert.equal(child.workflowState, "QC_APPROVED");
    assert.equal(child.planContentHash, parent.planContentHash);
    assert.equal(child.planObjectHash, parent.planObjectHash);
    assert.equal(child.renderGraphHash, input.graph.graphHash);
    assert.equal(
      child.authoritativeSidecars.currentRenderGraphV1,
      input.graph.graphHash,
    );
    assert.equal(
      child.authoritativeSidecars.currentRenderGraphReceiptV1,
      input.graph.receiptHash,
    );
    assert.equal(
      child.authoritativeSidecars.approvedFinalMedia,
      finalHash,
    );
    assert.equal(
      child.authoritativeSidecars.currentRenderGraphActivePointerV1,
      input.graph.activePointerHash,
    );
    assert.equal(
      child.authoritativeSidecars.qcApprovalV2,
      canonicalJsonSha256(record),
    );
    assert.equal(
      resolveProducerAuthorityHeadSync(fixture.producer),
      committed.childRevisionHash,
    );
    assert.equal(
      resolveProducerApprovedHeadSync(fixture.producer),
      committed.childRevisionHash,
    );
    const replay = commitProducerQcPromotionSync(input);
    assert.equal(replay.status, "replayed");
    assert.equal(replay.childRevisionHash, committed.childRevisionHash);
  } finally {
    cleanRevisionFixture(fixture.root);
  }
}

function draftAheadOfApprovedPromotesItsOwnChild(): void {
  const fixture = bootstrapRevisionFixture();
  try {
    const genesis = revision(fixture.producer, fixture.genesis);
    const firstRecord = approval(
      genesis, hash("first-final"), "first-approved");
    const firstGraph = graph(
      fixture.producer,
      genesis,
      firstRecord.finalHash,
      "first-approved",
    );
    const firstPreparation = prepareProducerQcPromotionSync(
      fixture.producer,
      { graphHash: firstGraph.graphHash, approval: firstRecord },
    );
    publishApproval(fixture.producer, firstRecord);
    const first = commitProducerQcPromotionSync({
      preparation: firstPreparation,
      graph: firstGraph,
      approval: firstRecord,
    });
    fs.rmSync(qcPromotionIntentPath(fixture.producer));
    const draftInput = revisionCommitInput(
      fixture.producer, first.childRevisionHash, "f");
    const draft = commitProducerRevisionSync(draftInput);
    assert.equal(
      resolveProducerApprovedHeadSync(fixture.producer),
      first.childRevisionHash,
    );
    const draftRevision = revision(
      fixture.producer, draft.childRevisionHash);
    const secondRecord = approval(
      draftRevision, hash("second-final"), "second-approved");
    const secondGraph = graph(
      fixture.producer,
      draftRevision,
      secondRecord.finalHash,
      "second-approved",
    );
    const secondPreparation = prepareProducerQcPromotionSync(
      fixture.producer,
      { graphHash: secondGraph.graphHash, approval: secondRecord },
    );
    assert.equal(
      secondPreparation.expectedApprovedHead,
      first.childRevisionHash,
    );
    publishApproval(fixture.producer, secondRecord);
    const second = commitProducerQcPromotionSync({
      preparation: secondPreparation,
      graph: secondGraph,
      approval: secondRecord,
    });
    const approved = revision(fixture.producer, second.childRevisionHash);
    assert.equal(approved.parentRevisionHash, draft.childRevisionHash);
    assert.equal(approved.planObjectHash, draftRevision.planObjectHash);
    assert.equal(
      resolveProducerApprovedHeadSync(fixture.producer),
      second.childRevisionHash,
    );
  } finally {
    cleanRevisionFixture(fixture.root);
  }
}

approvalAdvancesExactPlanAndReplays();
draftAheadOfApprovedPromotesItsOwnChild();
console.log("producer QC promotion tests passed");
