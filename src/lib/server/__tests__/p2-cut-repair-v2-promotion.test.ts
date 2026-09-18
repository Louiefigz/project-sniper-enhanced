import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { parseProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import { fixtureSha } from
  "@/lib/producer/__tests__/_cut-restore-speech-fixture";
import { fileSha256 } from "../auto-edit-hash";
import {
  promoteCutRepairReviewSync,
  recoverCutRepairPromotionSync,
} from "../cut-repair-promotion-store";
import {
  assertObjectHashSync,
  authorityKey,
  readAuthorityJsonSync,
  writeAuthorityObjectSync,
} from "../producer-authority-files";
import { publishProducerAdvanceSync } from "../producer-revision-head";
import {
  cleanRevisionFixture,
} from "./_producer-revision-fixture";
import {
  assertActivation,
  assertReplay,
  assertSelectedArtifacts,
  promotionInput,
} from "./_p2-cut-repair-v2-promotion-assertions";
import { renderedPromotionReviewSetup } from
  "./_p2-cut-repair-v2-lifecycle-fixture";
import { observeCurrentRenderGraphAuthoritySync } from
  "../current-render-graph-authority";
import { activateCutRepairPromotionMediaSync } from
  "../cut-repair-media-activation";
import { parseCutRepairTransitionRecord } from
  "../cut-repair-transition-model";

const ACTIVATION_CRASH_WORKER = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "helpers",
  "cut-repair-activation-crash-worker.ts",
);

function run(): void {
  const value = renderedPromotionReviewSetup();
  try {
    const input = promotionInput(value);
    const promoted = promoteCutRepairReviewSync({
      producerDir: value.fixture.producer,
      action: input.action,
      proof: input.proof.proof,
    });
    assert.equal(promoted.status, "committed");
    assertSelectedArtifacts(value, input, promoted.childRevisionHash);
    assertActivation(value, input);
    assertReplay(value, input);
  } finally {
    cleanRevisionFixture(value.fixture.root);
  }
}

function crashAfterActivationRecovers(): void {
  const value = renderedPromotionReviewSetup();
  try {
    const input = promotionInput(value);
    assert.throws(() => promoteCutRepairReviewSync({
      producerDir: value.fixture.producer,
      action: input.action,
      proof: input.proof.proof,
    }, {
      after: (boundary) => {
        if (boundary === "after-advance") {
          throw new Error("crash:after-activation");
        }
      },
    }), /crash:after-activation/);
    assert.equal(
      fileSha256(path.join(value.fixture.producer, "final.mp4")),
      input.proof.hashes.renderedMedia,
    );
    const recovered = recoverCutRepairPromotionSync(
      value.fixture.producer, input.action.idempotencyKey);
    assert.ok(["committed", "replayed"].includes(recovered.status));
    assert.doesNotThrow(() => observeCurrentRenderGraphAuthoritySync({
      producerDir: value.fixture.producer,
      expectedGraphHash: value.graph.hash,
      expectedFinalHash: input.proof.hashes.renderedMedia,
    }));
  } finally {
    cleanRevisionFixture(value.fixture.root);
  }
}

function staleDescendantCannotReactivateMedia(): void {
  const value = renderedPromotionReviewSetup();
  try {
    const input = promotionInput(value);
    const promoted = promoteCutRepairReviewSync({
      producerDir: value.fixture.producer,
      action: input.action,
      proof: input.proof.proof,
    });
    const revision = parseProjectRevision(assertObjectHashSync(
      value.paths.objects.revisions, promoted.childRevisionHash));
    const descendant = writeAuthorityObjectSync(
      value.paths.objects.revisions,
      { ...revision, parentRevisionHash: promoted.childRevisionHash },
    );
    publishProducerAdvanceSync(value.paths, {
      schemaVersion: 1,
      expectedParentRevisionHash: promoted.childRevisionHash,
      childRevisionHash: descendant.hash,
      idempotencyKey: "76000000-0000-4000-8000-000000000001",
      requestDigest: fixtureSha("a"),
    });
    assert.throws(
      () => recoverCutRepairPromotionSync(
        value.fixture.producer, input.action.idempotencyKey),
      /cannot reactivate stale descendant media/,
    );
  } finally {
    cleanRevisionFixture(value.fixture.root);
  }
}

function activationCrashReopensReceipt(
  boundary: "after-commit" | "after-committed" | "after-intent-removed",
): void {
  const value = renderedPromotionReviewSetup();
  try {
    const input = promotionInput(value);
    promoteCutRepairReviewSync({
      producerDir: value.fixture.producer,
      action: input.action,
      proof: input.proof.proof,
    });
    fs.rmSync(path.join(
      value.paths.sagas,
      "cut-repair-media-activation",
      "promotion-commits",
    ), { recursive: true, force: true });
    const recordPath = path.join(
      value.paths.sagas,
      "cut-repair-promotion",
      "records",
      `${authorityKey(input.action.idempotencyKey)}.json`,
    );
    fs.writeFileSync(
      path.join(value.fixture.root, "cut-repair-record.json"),
      `${JSON.stringify(readAuthorityJsonSync(recordPath))}\n`,
    );
    const crashed = spawnSync(process.execPath, [
      "--import", "tsx", ACTIVATION_CRASH_WORKER,
      value.fixture.root, value.fixture.producer, boundary,
    ], { encoding: "utf8" });
    assert.equal(crashed.status, 72, crashed.stderr || crashed.stdout);
    assert.doesNotThrow(() => recoverCutRepairPromotionSync(
      value.fixture.producer, input.action.idempotencyKey));
    assertActivation(value, input);
  } finally {
    cleanRevisionFixture(value.fixture.root);
  }
}

function thrownAfterCommitKeepsExactChild(): void {
  const value = renderedPromotionReviewSetup();
  try {
    const input = promotionInput(value);
    promoteCutRepairReviewSync({
      producerDir: value.fixture.producer,
      action: input.action,
      proof: input.proof.proof,
    });
    const recordPath = path.join(
      value.paths.sagas,
      "cut-repair-promotion",
      "records",
      `${authorityKey(input.action.idempotencyKey)}.json`,
    );
    const record = parseCutRepairTransitionRecord(
      readAuthorityJsonSync(recordPath));
    fs.rmSync(path.join(
      value.paths.sagas,
      "cut-repair-media-activation",
      "promotion-commits",
    ), { recursive: true, force: true });
    assert.throws(() => activateCutRepairPromotionMediaSync(
      value.fixture.producer,
      record,
      (boundary) => {
        if (boundary === "after-commit") {
          throw new Error("injected fault after exact activation receipt");
        }
      },
    ), /injected fault after exact activation receipt/);
    assertSelectedArtifacts(
      value, input, record.childRevisionHash);
    assertActivation(value, input);
  } finally {
    cleanRevisionFixture(value.fixture.root);
  }
}

run();
crashAfterActivationRecovers();
staleDescendantCannotReactivateMedia();
activationCrashReopensReceipt("after-commit");
activationCrashReopensReceipt("after-committed");
activationCrashReopensReceipt("after-intent-removed");
thrownAfterCommitKeepsExactChild();
console.log("p2-cut-repair-v2-promotion tests passed");
