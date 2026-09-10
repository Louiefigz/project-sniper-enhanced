import assert from "node:assert/strict";
import {
  existsSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import {
  AUTO_EDIT_PROMOTION_RECONCILIATION_FILE,
  readApproval,
} from "../../server/auto-edit-quality-artifacts";
import {
  promoteApprovedCandidateWithRenderGraph,
} from "../../server/current-render-graph-candidate";
import { fileSha256 } from "../../server/auto-edit-job-store";
import {
  REVISION_HASH,
  action,
  assertRolledBack,
  authorityRuntime,
  fixture,
} from "./_auto-edit-graph-promotion-fixture";

function beforeActivationFailureRollsBack(): void {
  const item = fixture("before-activation");
  let rollbackCalls = 0;
  const runtime = authorityRuntime({
    command: (args) => {
      if (action(args) === "activate"
          || action(args) === "candidate-active") {
        throw new Error("graph activation failed");
      }
      if (action(args) === "rollback") rollbackCalls += 1;
      return { ok: true };
    },
  });
  try {
    assert.throws(
      () => promoteApprovedCandidateWithRenderGraph(
        item.candidate, item.producer, item.record, runtime),
      /graph activation failed/,
    );
    assertRolledBack(item);
    assert.equal(rollbackCalls, 1);
    assert.equal(existsSync(path.join(
      item.producer, AUTO_EDIT_PROMOTION_RECONCILIATION_FILE)), false);
  } finally {
    rmSync(item.root, { recursive: true, force: true });
  }
}

function ambiguousActivationCompletesExactCandidate(): void {
  const item = fixture("ambiguous-active");
  let active = false;
  const runtime = authorityRuntime({
    command: (args) => {
      if (action(args) === "activate") {
        active = true;
        throw new Error("transport ended after ACTIVE write");
      }
      if (action(args) === "candidate-active" && !active) {
        throw new Error("candidate is not ACTIVE");
      }
      return { ok: true };
    },
  });
  try {
    promoteApprovedCandidateWithRenderGraph(
      item.candidate, item.producer, item.record, runtime);
    assert.equal(active, true);
    assert.equal(
      fileSha256(path.join(item.producer, "final.mp4")),
      item.candidateHash,
    );
    assert.ok(readApproval(item.producer));
    assert.equal(existsSync(item.candidate), false);
    assert.equal(existsSync(path.join(
      item.producer, ".sniper-qc", "promotion-recovery")), false);
  } finally {
    rmSync(item.root, { recursive: true, force: true });
  }
}

function approvalFailureRestoresMediaAndGraph(): void {
  const item = fixture("approval-failure");
  let active = false;
  const runtime = authorityRuntime({
    command: (args) => {
      if (action(args) === "activate") active = true;
      if (action(args) === "rollback") active = false;
      return { ok: true };
    },
    approvalWriter: () => {
      throw new Error("approval publication failed");
    },
  });
  try {
    assert.throws(
      () => promoteApprovedCandidateWithRenderGraph(
        item.candidate, item.producer, item.record, runtime),
      /approval publication failed/,
    );
    assert.equal(active, false);
    assertRolledBack(item);
  } finally {
    rmSync(item.root, { recursive: true, force: true });
  }
}

function ambiguousRollbackLeavesBlockingMarker(): void {
  const item = fixture("rollback-ambiguous");
  const runtime = authorityRuntime({
    command: (args) => {
      if (["activate", "candidate-active", "rollback"].includes(action(args))) {
        throw new Error(`ambiguous ${action(args)}`);
      }
      return { ok: true };
    },
  });
  try {
    assert.throws(
      () => promoteApprovedCandidateWithRenderGraph(
        item.candidate, item.producer, item.record, runtime),
      /requires reconciliation/,
    );
    assertRolledBack(item);
    const marker = path.join(
      item.producer, AUTO_EDIT_PROMOTION_RECONCILIATION_FILE);
    assert.ok(existsSync(marker));
    assert.throws(
      () => promoteApprovedCandidateWithRenderGraph(
        item.candidate, item.producer, item.record, runtime),
      /blocked by unresolved reconciliation/,
    );
  } finally {
    rmSync(item.root, { recursive: true, force: true });
  }
}

function qcFailureRestoresMutableAuthority(): void {
  const item = fixture("qc-authority-failure");
  const approvedHead = path.join(item.producer, ".test-approved-head");
  writeFileSync(approvedHead, "old-approved-head");
  let active = false;
  const runtime = authorityRuntime({
    command: (args) => {
      if (action(args) === "activate") active = true;
      if (action(args) === "rollback") active = false;
      return { ok: true };
    },
    qcPreparation: (producerDir) => ({
      producerDir,
      parentRevisionHash: REVISION_HASH,
      expectedApprovedHead: null,
      mutablePaths: [approvedHead],
    }),
    qcCommit: () => {
      writeFileSync(approvedHead, "new-approved-head");
      throw new Error("QC revision publication failed");
    },
  });
  try {
    assert.throws(
      () => promoteApprovedCandidateWithRenderGraph(
        item.candidate, item.producer, item.record, runtime),
      /QC revision publication failed/,
    );
    assert.equal(active, false);
    assert.equal(readFileSync(approvedHead, "utf8"), "old-approved-head");
    assertRolledBack(item);
  } finally {
    rmSync(item.root, { recursive: true, force: true });
  }
}

beforeActivationFailureRollsBack();
ambiguousActivationCompletesExactCandidate();
approvalFailureRestoresMediaAndGraph();
ambiguousRollbackLeavesBlockingMarker();
qcFailureRestoresMutableAuthority();
console.log("auto-edit graph promotion failure test passed");
