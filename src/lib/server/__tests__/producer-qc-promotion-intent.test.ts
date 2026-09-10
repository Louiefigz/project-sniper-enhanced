import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { approvalPath } from "../auto-edit-quality-artifacts";
import {
  assertApprovedProducerRevisionSync,
  approvedProducerRevisionReady,
} from "../producer-approved-revision-authority";
import {
  commitProducerQcPromotionSync,
} from "../producer-qc-promotion";
import {
  ProducerQcPromotionReconciliationError,
  qcPromotionIntentPath,
  recoverProducerQcPromotionIntentSync,
} from "../producer-qc-promotion-intent";
import { QC_PROMOTION_RECONCILIATION_FILE } from
  "../ask-editor-reconciliation";
import {
  cleanQcPromotionIntentFixture,
  preparedQcPromotionIntentFixture,
  publishQcPromotionLiveState,
} from "./_producer-qc-promotion-intent-fixture";

function preparedOldStateRecovers(): void {
  const item = preparedQcPromotionIntentFixture("intent-old");
  try {
    assert.ok(fs.existsSync(qcPromotionIntentPath(item.genesis.producer)));
    assert.equal(
      recoverProducerQcPromotionIntentSync(item.genesis.producer),
      "recovered-old",
    );
    assert.equal(
      fs.existsSync(qcPromotionIntentPath(item.genesis.producer)),
      false,
    );
  } finally {
    cleanQcPromotionIntentFixture(item);
  }
}

function exactChildFaultRecoversAndResumes(): void {
  const item = preparedQcPromotionIntentFixture("intent-exact-child");
  try {
    const graph = publishQcPromotionLiveState(item);
    assert.throws(
      () => commitProducerQcPromotionSync({
        preparation: item.preparation,
        graph,
        approval: item.approval,
      }, {
        after: (boundary) => {
          if (boundary === "after-advance") {
            throw new Error("fault after exact child advance");
          }
        },
      }),
      /fault after exact child advance/,
    );
    assert.equal(
      recoverProducerQcPromotionIntentSync(item.genesis.producer),
      "recovered-exact-child",
    );
    assertApprovedProducerRevisionSync({
      producerDir: item.genesis.producer,
      planPath: item.genesis.planPath,
      manifestPath: item.genesis.manifestPath,
      expectedFinalHash: item.approval.finalHash,
    });
    assert.equal(approvedProducerRevisionReady(
      item.genesis.producer,
      item.genesis.planPath,
      item.genesis.manifestPath,
      item.approval.finalHash,
    ), true);
    fs.writeFileSync(
      item.genesis.planPath,
      `${JSON.stringify({ ...item.genesis.plan, foreign: true })}\n`,
    );
    assert.equal(approvedProducerRevisionReady(
      item.genesis.producer,
      item.genesis.planPath,
      item.genesis.manifestPath,
      item.approval.finalHash,
    ), false);
  } finally {
    cleanQcPromotionIntentFixture(item);
  }
}

function mixedLiveStateRequiresReconciliation(): void {
  const item = preparedQcPromotionIntentFixture("intent-mixed");
  try {
    fs.writeFileSync(
      approvalPath(item.genesis.producer),
      `${JSON.stringify(item.approval)}\n`,
    );
    assert.throws(
      () => recoverProducerQcPromotionIntentSync(item.genesis.producer),
      ProducerQcPromotionReconciliationError,
    );
    assert.ok(fs.existsSync(qcPromotionIntentPath(item.genesis.producer)));
    const marker = path.join(
      item.genesis.producer, QC_PROMOTION_RECONCILIATION_FILE);
    const value = JSON.parse(fs.readFileSync(marker, "utf8")) as
      Record<string, unknown>;
    assert.equal(value.status, "reconciliation-required");
    assert.equal(value.intentId, item.preparation.intentId);
  } finally {
    cleanQcPromotionIntentFixture(item);
  }
}

function materializedChildWithoutCasRequiresReconciliation(): void {
  const item = preparedQcPromotionIntentFixture("intent-materialized");
  try {
    const graph = publishQcPromotionLiveState(item);
    assert.throws(
      () => commitProducerQcPromotionSync({
        preparation: item.preparation,
        graph,
        approval: item.approval,
      }, {
        after: (boundary) => {
          if (boundary === "after-child-materialized") {
            throw new Error("fault before head CAS");
          }
        },
      }),
      /fault before head CAS/,
    );
    assert.throws(
      () => recoverProducerQcPromotionIntentSync(item.genesis.producer),
      ProducerQcPromotionReconciliationError,
    );
  } finally {
    cleanQcPromotionIntentFixture(item);
  }
}

function approvedHeadWithoutAdvanceRequiresReconciliation(): void {
  const item = preparedQcPromotionIntentFixture("intent-staged-approved");
  try {
    const graph = publishQcPromotionLiveState(item);
    assert.throws(
      () => commitProducerQcPromotionSync({
        preparation: item.preparation,
        graph,
        approval: item.approval,
      }, {
        after: (boundary) => {
          if (boundary === "after-approved-head") {
            throw new Error("fault after approved head");
          }
        },
      }),
      /fault after approved head/,
    );
    assert.throws(
      () => recoverProducerQcPromotionIntentSync(item.genesis.producer),
      ProducerQcPromotionReconciliationError,
    );
  } finally {
    cleanQcPromotionIntentFixture(item);
  }
}

preparedOldStateRecovers();
exactChildFaultRecoversAndResumes();
mixedLiveStateRequiresReconciliation();
materializedChildWithoutCasRequiresReconciliation();
approvedHeadWithoutAdvanceRequiresReconciliation();
console.log("producer QC promotion durable-intent tests passed");
