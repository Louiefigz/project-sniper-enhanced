import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {
  recoverCandidatePromotionSync,
  runRecoverablePromotionSync,
} from "../candidate-promotion-transaction";
import {
  crash,
  marker,
  withFixture,
} from "./helpers/candidate-promotion-adversarial-fixture";

function staleIdentityBlocks(): void {
  withFixture("stale", (item) => {
    crash(item, "after-backups");
    const stale = { ...item.topology, transactionId: "b".repeat(64) };
    assert.throws(
      () => recoverCandidatePromotionSync(stale),
      /stale or foreign/,
    );
    assert.equal(fs.readFileSync(
      path.join(item.producer, "final.mp4"), "utf8"), "old-media");
    assert.equal(marker(item).phase, "backed-up");
  });
}

function tornIntentBlocksWithoutOverwrite(): void {
  withFixture("torn-intent", (item) => {
    fs.writeFileSync(item.topology.reconciliationPath, "{torn");
    assert.throws(
      () => recoverCandidatePromotionSync(item.topology),
      /torn or malformed/,
    );
    assert.equal(fs.readFileSync(
      item.topology.reconciliationPath, "utf8"), "{torn");
    assert.equal(fs.readFileSync(
      path.join(item.producer, "final.mp4"), "utf8"), "old-media");
  });
}

function foreignDestinationBlocksWithoutOverwrite(): void {
  withFixture("foreign-live", (item) => {
    crash(item, "after-transfers");
    fs.writeFileSync(path.join(item.producer, "final.mp4"), "foreign-media");
    assert.throws(
      () => recoverCandidatePromotionSync(item.topology),
      /requires reconciliation/,
    );
    assert.equal(fs.readFileSync(
      path.join(item.producer, "final.mp4"), "utf8"), "foreign-media");
    assert.equal(marker(item).phase, "reconciliation-required");
  });
}

function tornBackupBlocksWithoutLiveMutation(): void {
  withFixture("torn-backup", (item) => {
    crash(item, "after-backups");
    fs.writeFileSync(path.join(
      item.topology.recoveryRoot,
      `promotion-${item.topology.transactionId}`,
      "prior-0",
    ), "torn");
    assert.throws(
      () => recoverCandidatePromotionSync(item.topology),
      /requires reconciliation/,
    );
    assert.equal(fs.readFileSync(
      path.join(item.producer, "final.mp4"), "utf8"), "old-media");
    assert.equal(marker(item).phase, "reconciliation-required");
  });
}

function maliciousSourceSymlinkBlocks(): void {
  withFixture("source-symlink", (item) => {
    crash(item, "after-backups");
    const source = path.join(item.producer, "candidate-audit.json");
    fs.rmSync(source);
    fs.symlinkSync(path.join(item.producer, "final.mp4"), source);
    assert.throws(
      () => recoverCandidatePromotionSync(item.topology),
      /symlink traversal/,
    );
    assert.equal(fs.readFileSync(
      path.join(item.producer, "final.mp4"), "utf8"), "old-media");
    assert.equal(marker(item).phase, "backed-up");
  });
}

function foreignCommittedStateBlocks(): void {
  withFixture("foreign-committed", (item) => {
    crash(item, "after-committed");
    fs.writeFileSync(path.join(item.producer, "edit_plan.json"), "foreign-plan");
    assert.throws(
      () => recoverCandidatePromotionSync(item.topology),
      /requires reconciliation/,
    );
    assert.equal(fs.readFileSync(
      path.join(item.producer, "edit_plan.json"), "utf8"), "foreign-plan");
    assert.equal(marker(item).phase, "reconciliation-required");
  });
}

function unownedRecoveryDirectoryRules(): void {
  withFixture("unowned", (item) => {
    const directory = path.join(
      item.topology.recoveryRoot,
      `promotion-${item.topology.transactionId}`,
    );
    fs.mkdirSync(directory, { recursive: true });
    runRecoverablePromotionSync({
      ...item.topology,
      commit: () => fs.writeFileSync(
        path.join(item.producer, "edit_plan.json"), "new-plan"),
    });
    assert.equal(fs.readFileSync(
      path.join(item.producer, "final.mp4"), "utf8"), "new-media");
  });
  withFixture("unowned-foreign", (item) => {
    const directory = path.join(
      item.topology.recoveryRoot,
      `promotion-${item.topology.transactionId}`,
    );
    fs.mkdirSync(directory, { recursive: true });
    fs.writeFileSync(path.join(directory, "foreign"), "do-not-delete");
    assert.throws(
      () => runRecoverablePromotionSync({
        ...item.topology,
        commit: () => undefined,
      }),
      /foreign unowned recovery state/,
    );
    assert.equal(fs.readFileSync(
      path.join(directory, "foreign"), "utf8"), "do-not-delete");
  });
}

function symlinkedAncestorCannotEscapeScope(): void {
  withFixture("ancestor-symlink", (item) => {
    const outside = path.join(item.root, "outside");
    fs.mkdirSync(outside);
    fs.writeFileSync(path.join(outside, "final.mp4"), "outside-media");
    const link = path.join(item.producer, "escaped");
    fs.symlinkSync(outside, link);
    const escaped = {
      ...item.topology,
      moves: [{
        source: path.join(item.producer, "candidate.mp4"),
        destination: path.join(link, "final.mp4"),
      }],
    };
    assert.throws(
      () => runRecoverablePromotionSync({
        ...escaped,
        commit: () => undefined,
      }),
      /symlink traversal/,
    );
    assert.equal(fs.readFileSync(
      path.join(outside, "final.mp4"), "utf8"), "outside-media");
    assert.equal(fs.existsSync(item.topology.reconciliationPath), false);
  });
}

function foreignTemporaryIsNeverDeleted(): void {
  withFixture("foreign-temporary", (item) => {
    const temporary = path.join(
      item.producer,
      `.promotion-promotion-${item.topology.transactionId}-0.tmp`,
    );
    fs.writeFileSync(temporary, "foreign-temporary");
    assert.throws(
      () => runRecoverablePromotionSync({
        ...item.topology,
        commit: () => undefined,
      }),
      /temporary path is foreign/,
    );
    assert.equal(fs.readFileSync(
      temporary, "utf8"), "foreign-temporary");
    assert.equal(fs.readFileSync(
      path.join(item.producer, "final.mp4"), "utf8"), "old-media");
    assert.equal(fs.existsSync(item.topology.reconciliationPath), false);
  });
}

function missingSourcePoliciesAreExplicit(): void {
  withFixture("missing-required", (item) => {
    fs.rmSync(path.join(item.producer, "candidate-audit.json"));
    assert.throws(
      () => runRecoverablePromotionSync({
        ...item.topology,
        commit: () => undefined,
      }),
      /required source is missing/,
    );
    assert.equal(fs.readFileSync(
      path.join(item.producer, "audit.json"), "utf8"), "old-audit");
    assert.equal(fs.existsSync(item.topology.reconciliationPath), false);
  });
  withFixture("missing-optional", (item) => {
    fs.rmSync(path.join(item.producer, "candidate-audit.json"));
    runRecoverablePromotionSync({
      ...item.topology,
      copies: item.topology.copies.map((row) => ({
        ...row, missingSource: "delete-destination" as const,
      })),
      commit: () => fs.writeFileSync(
        path.join(item.producer, "edit_plan.json"), "new-plan"),
    });
    assert.equal(
      fs.existsSync(path.join(item.producer, "audit.json")), false);
  });
}

staleIdentityBlocks();
tornIntentBlocksWithoutOverwrite();
foreignDestinationBlocksWithoutOverwrite();
tornBackupBlocksWithoutLiveMutation();
maliciousSourceSymlinkBlocks();
foreignCommittedStateBlocks();
unownedRecoveryDirectoryRules();
symlinkedAncestorCannotEscapeScope();
foreignTemporaryIsNeverDeleted();
missingSourcePoliciesAreExplicit();
console.log("candidate promotion adversarial recovery tests passed");
