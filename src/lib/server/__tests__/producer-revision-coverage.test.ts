import assert from "node:assert/strict";
import { parseEditReceiptV1 } from "@/lib/producer/contracts/edit-receipt";
import { parseEditRequestV1 } from "@/lib/producer/contracts/edit-request";
import { parseProjectRevision } from "@/lib/producer/contracts/project-revision";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
} from "../producer-authority-files";
import { resolveProducerAuthorityHeadSync } from "../producer-revision-head";
import { materializeProducerCommitSync } from "../producer-revision-materialize";
import {
  reconcileProducerAuthoritySync,
  recoverProducerCommitSync,
} from "../producer-revision-recovery";
import { commitProducerRevisionSync } from "../producer-revision-store";
import {
  bootstrapRevisionFixture,
  cleanRevisionFixture,
  revisionCommitInput,
} from "./_producer-revision-fixture";

const fixture = bootstrapRevisionFixture();
try {
  const input = revisionCommitInput(
    fixture.producer,
    fixture.genesis,
    "7",
    20,
  );
  const staged = materializeProducerCommitSync(input);
  assert.equal(input.request.clauses.length, 20);
  assert.equal(input.batch.operations.length, 20);
  assert.throws(
    () => recoverProducerCommitSync(
      fixture.producer,
      staged.record.idempotencyKey,
      {
        after: (boundary) => {
          if (boundary === "after-advance") throw new Error("simulated restart");
        },
      },
    ),
    /simulated restart/,
  );

  const recovered = reconcileProducerAuthoritySync(fixture.producer);
  assert.equal(recovered.length, 1);
  assert.equal(recovered[0].status, "committed");
  assert.equal(
    resolveProducerAuthorityHeadSync(fixture.producer),
    staged.record.childRevisionHash,
  );

  const paths = producerAuthorityPaths(fixture.producer);
  const request = parseEditRequestV1(assertObjectHashSync(
    paths.objects.requests,
    staged.record.artifactHashes.requestOutcome,
  ));
  assert.equal(request.clauses.length, 20);
  assert.ok(request.clauses.every((clause) => clause.state === "committed"));
  assert.equal(new Set(request.clauses.map((clause) => clause.clauseId)).size, 20);

  const receipt = parseEditReceiptV1(assertObjectHashSync(
    paths.objects.receipts,
    recovered[0].receiptHash!,
  ));
  assert.equal(receipt.operations.length, 20);
  assert.ok(receipt.operations.every(
    (operation) => operation.executionState === "committed",
  ));
  assert.equal(new Set(receipt.operations.map((row) => row.operationId)).size, 20);

  const revision = parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions,
    staged.record.childRevisionHash,
  ));
  assert.equal(revision.parentRevisionHash, fixture.genesis);
  assert.equal(revision.manifestHash, input.batch.base.manifestHash);
  assert.equal(revision.timelineMapHash, input.batch.base.timelineMapHash);
  assert.equal(revision.pictureLockHash, input.batch.base.pictureLockHash);
  assert.deepEqual(
    revision.destinationProfileHashes,
    input.batch.base.destinationProfileHashes,
  );

  const replay = commitProducerRevisionSync(input);
  assert.equal(replay.status, "replayed");
  assert.equal(replay.receiptHash, recovered[0].receiptHash);
} finally {
  cleanRevisionFixture(fixture.root);
}

console.log("producer-revision-coverage tests passed");
