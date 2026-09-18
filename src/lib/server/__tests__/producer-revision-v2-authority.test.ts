import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  parseProjectRevision,
  parseProjectRevisionV1,
} from "@/lib/producer/contracts/project-revision";
import {
  assertObjectHashSync,
  authorityKey,
  producerAuthorityPaths,
  publishImmutableAuthorityJsonSync,
  readAuthorityJsonSync,
  writeAuthorityObjectSync,
  writeMutableAuthorityJsonSync,
} from "../producer-authority-files";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { planObjectContentHash } from "../auto-edit-authority";
import {
  approveProducerAuthorityHeadSync,
  initializeProducerAuthoritySync,
  resolveProducerApprovedHeadSync,
  resolveProducerAuthorityHeadSync,
} from "../producer-revision-head";
import { materializeProducerCommitSync } from "../producer-revision-materialize";
import { commitProducerRevisionSync } from "../producer-revision-store";
import {
  bootstrapRevisionFixture,
  cleanRevisionFixture,
  fixtureHash,
  revisionCommitInput,
} from "./_producer-revision-fixture";

function revision(paths: ReturnType<typeof producerAuthorityPaths>, hash: string) {
  return parseProjectRevision(assertObjectHashSync(paths.objects.revisions, hash));
}

function exactPlanIdentity(marker: string): {
  revisionHash: string;
  planObjectHash: string;
} {
  const fixture = bootstrapRevisionFixture();
  try {
    const input = revisionCommitInput(
      fixture.producer, fixture.genesis, "b");
    input.planObject = {
      ...(input.planObject as Record<string, unknown>),
      planVersion: `metadata-${marker}`,
      _privateAuthoringMarker: marker,
    };
    const staged = materializeProducerCommitSync(input);
    const paths = producerAuthorityPaths(fixture.producer);
    const child = revision(paths, staged.record.childRevisionHash);
    if (child.schemaVersion !== 2) {
      throw new Error("new revision write did not emit V2");
    }
    assert.equal(child.planContentHash, input.revision.planContentHash);
    assert.equal(
      staged.record.artifactHashes.plan,
      child.planObjectHash,
    );
    assert.deepEqual(
      assertObjectHashSync(paths.objects.plans, child.planObjectHash),
      input.planObject,
    );
    return {
      revisionHash: staged.record.childRevisionHash,
      planObjectHash: child.planObjectHash,
    };
  } finally {
    cleanRevisionFixture(fixture.root);
  }
}

function verifyHeadSeparation(): void {
  const fixture = bootstrapRevisionFixture();
  try {
    const paths = producerAuthorityPaths(fixture.producer);
    const genesis = revision(paths, fixture.genesis);
    assert.equal(genesis.schemaVersion, 2);
    assert.equal(resolveProducerAuthorityHeadSync(
      fixture.producer), fixture.genesis);
    assert.equal(resolveProducerApprovedHeadSync(
      fixture.producer), null);
    const input = revisionCommitInput(
      fixture.producer, fixture.genesis, "c");
    const committed = commitProducerRevisionSync(input);
    assert.equal(committed.status, "committed");
    assert.equal(resolveProducerAuthorityHeadSync(
      fixture.producer), committed.childRevisionHash);
    assert.equal(resolveProducerApprovedHeadSync(
      fixture.producer), null);
    assert.throws(
      () => approveProducerAuthorityHeadSync(
        fixture.producer, committed.childRevisionHash, null),
      /QC_APPROVED/,
    );
  } finally {
    cleanRevisionFixture(fixture.root);
  }
}

function verifyExplicitApproval(): void {
  const fixture = bootstrapRevisionFixture();
  try {
    const input = revisionCommitInput(
      fixture.producer, fixture.genesis, "d");
    input.revision.workflowState = "QC_APPROVED";
    const committed = commitProducerRevisionSync(input);
    assert.throws(
      () => approveProducerAuthorityHeadSync(
        fixture.producer, fixture.genesis, null),
      /working head changed/,
    );
    assert.equal(
      approveProducerAuthorityHeadSync(
        fixture.producer, committed.childRevisionHash, null),
      committed.childRevisionHash,
    );
    assert.equal(
      approveProducerAuthorityHeadSync(
        fixture.producer, committed.childRevisionHash, null),
      committed.childRevisionHash,
    );
    assert.equal(resolveProducerApprovedHeadSync(
      fixture.producer), committed.childRevisionHash);
  } finally {
    cleanRevisionFixture(fixture.root);
  }
}

function verifyMissingPlanFailsClosed(): void {
  const fixture = bootstrapRevisionFixture();
  try {
    const paths = producerAuthorityPaths(fixture.producer);
    const genesis = revision(paths, fixture.genesis);
    if (genesis.schemaVersion !== 2) {
      throw new Error("fixture genesis is not V2");
    }
    fs.rmSync(path.join(
      paths.objects.plans, `${genesis.planObjectHash}.json`));
    assert.throws(
      () => resolveProducerAuthorityHeadSync(fixture.producer),
      /ENOENT/,
    );
  } finally {
    cleanRevisionFixture(fixture.root);
  }
}

function verifyLegacyRequestDigestReplays(): void {
  const fixture = bootstrapRevisionFixture();
  try {
    const input = revisionCommitInput(
      fixture.producer, fixture.genesis, "e");
    const committed = commitProducerRevisionSync(input);
    const paths = producerAuthorityPaths(fixture.producer);
    const name = `${authorityKey(input.request.idempotencyKey)}.json`;
    const recordPath = path.join(paths.idempotency, name);
    const intentPath = path.join(paths.intents, name);
    const record = readAuthorityJsonSync(recordPath) as Record<string, unknown>;
    const intent = readAuthorityJsonSync(intentPath) as Record<string, unknown>;
    const legacyDigest = canonicalJsonSha256({
      request: input.request,
      batch: input.batch,
      revision: input.revision,
      graph: input.renderGraph,
      projection: input.projectionReceipt,
      invalidation: input.invalidationReceipt,
      invariantProofHash: input.invariantProofHash,
    });
    writeMutableAuthorityJsonSync(recordPath, {
      ...record, requestDigest: legacyDigest,
    });
    writeMutableAuthorityJsonSync(intentPath, {
      ...intent, requestDigest: legacyDigest,
    });
    const replay = commitProducerRevisionSync(input);
    assert.equal(replay.status, "replayed");
    assert.equal(replay.childRevisionHash, committed.childRevisionHash);
  } finally {
    cleanRevisionFixture(fixture.root);
  }
}

function verifyLegacyReadCompatibility(): void {
  const root = fs.realpathSync(
    fs.mkdtempSync(path.join(os.tmpdir(), "sniper-revision-v1-read-")));
  const producer = path.join(root, "producer");
  fs.mkdirSync(producer);
  try {
    const paths = producerAuthorityPaths(producer);
    const legacy = parseProjectRevisionV1({
      schemaVersion: 1,
      parentRevisionHash: null,
      planContentHash: fixtureHash("a"),
      manifestHash: fixtureHash("b"),
      sourceSnapshotSetHash: fixtureHash("c"),
      transcriptTimingHash: fixtureHash("d"),
      timelineMapHash: fixtureHash("e"),
      canvasProfileHash: fixtureHash("f"),
      destinationProfileHashes: [],
      pictureLockHash: null,
      workflowState: "INGESTED",
      requestLedgerHash: fixtureHash("1"),
      renderGraphHash: fixtureHash("2"),
      projectionReceiptHash: null,
      authoritativeSidecars: {},
    });
    const stored = writeAuthorityObjectSync(paths.objects.revisions, legacy);
    publishImmutableAuthorityJsonSync(
      path.join(paths.advances, "GENESIS.json"),
      { schemaVersion: 1, revisionHash: stored.hash },
    );
    assert.equal(resolveProducerAuthorityHeadSync(producer), stored.hash);
    assert.equal(resolveProducerApprovedHeadSync(producer), null);
    assert.equal(revision(paths, stored.hash).schemaVersion, 1);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

function verifyExplicitApprovedGenesisImport(): void {
  const root = fs.realpathSync(
    fs.mkdtempSync(path.join(os.tmpdir(), "sniper-approved-genesis-")));
  const producer = path.join(root, "producer");
  fs.mkdirSync(producer);
  const plan = {
    schemaVersion: 1,
    planVersion: "approved-import",
    graphicsTrack: [],
  };
  try {
    const initialized = initializeProducerAuthoritySync(producer, {
      schemaVersion: 1,
      parentRevisionHash: null,
      planContentHash: planObjectContentHash(plan),
      manifestHash: fixtureHash("a"),
      sourceSnapshotSetHash: fixtureHash("b"),
      transcriptTimingHash: fixtureHash("c"),
      timelineMapHash: fixtureHash("d"),
      canvasProfileHash: fixtureHash("e"),
      destinationProfileHashes: [],
      pictureLockHash: null,
      workflowState: "QC_APPROVED",
      requestLedgerHash: fixtureHash("1"),
      renderGraphHash: fixtureHash("2"),
      projectionReceiptHash: null,
      authoritativeSidecars: {},
    }, plan, { approvedGenesis: "qc-approved-import" });
    assert.equal(
      resolveProducerApprovedHeadSync(producer),
      initialized.revisionHash,
    );
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

const left = exactPlanIdentity("left");
const right = exactPlanIdentity("right");
assert.notEqual(left.planObjectHash, right.planObjectHash);
assert.notEqual(left.revisionHash, right.revisionHash);
verifyHeadSeparation();
verifyExplicitApproval();
verifyMissingPlanFailsClosed();
verifyLegacyRequestDigestReplays();
verifyLegacyReadCompatibility();
verifyExplicitApprovedGenesisImport();
console.log("producer-revision-v2-authority tests passed");
