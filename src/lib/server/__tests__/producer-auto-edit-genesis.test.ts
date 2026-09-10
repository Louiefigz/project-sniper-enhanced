import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { parseProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import { parseProjectionReceiptV1 } from
  "@/lib/producer/contracts/projection-receipt";
import { planObjectContentHash } from "../auto-edit-authority";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
  writeAuthorityObjectSync,
} from "../producer-authority-files";
import {
  ProducerAuthorityReadinessError,
  observeAutoEditGenesisFactsSync,
} from "../producer-auto-edit-genesis-facts";
import { initializeAutoEditProducerAuthoritySync } from
  "../producer-auto-edit-genesis";
import {
  resolveProducerApprovedHeadSync,
  resolveProducerAuthorityHeadSync,
  initializeProducerAuthoritySync,
} from "../producer-revision-head";
import {
  ProducerAuthorityMigrationRequiredError,
} from "../producer-auto-edit-legacy-adoption";
import {
  autoEditGenesisFixture,
} from
  "./_producer-auto-edit-genesis-fixture";

function initializedRevision(): void {
  const item = autoEditGenesisFixture("initialized");
  try {
    const initialized = initializeAutoEditProducerAuthoritySync(item.input);
    assert.equal(initialized.status, "initialized");
    assert.equal(
      resolveProducerAuthorityHeadSync(item.producer),
      initialized.revisionHash,
    );
    assert.equal(resolveProducerApprovedHeadSync(item.producer), null);
    const paths = producerAuthorityPaths(item.producer);
    const parsed = parseProjectRevision(assertObjectHashSync(
      paths.objects.revisions, initialized.revisionHash));
    assert.equal(parsed.schemaVersion, 2);
    if (parsed.schemaVersion !== 2) throw new Error("expected V2 genesis");
    assert.equal(parsed.parentRevisionHash, null);
    assert.equal(parsed.workflowState, "READY_TO_FINALIZE");
    assert.equal(parsed.planContentHash, planObjectContentHash(item.plan));
    assert.equal(parsed.planObjectHash, canonicalJsonSha256(item.plan));
    assert.equal(parsed.sourceSnapshotSetHash, item.sourceSetHash);
    assert.equal(parsed.transcriptTimingHash, item.transcriptHash);
    assert.equal(parsed.timelineMapHash, item.timelineMapHash);
    assert.equal(parsed.pictureLockHash, item.pictureLockHash);
    assert.equal(parsed.renderGraphHash, item.graphHash);
    const projection = parseProjectionReceiptV1(assertObjectHashSync(
      paths.objects.projections, parsed.projectionReceiptHash!));
    assert.equal(projection.projectionHash, item.projectionHash);
    assert.equal(
      parsed.authoritativeSidecars.stagedRenderGraphV1,
      item.graphHash,
    );
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

function idempotentRestart(): void {
  const item = autoEditGenesisFixture("restart");
  try {
    const initialized = initializeAutoEditProducerAuthoritySync(item.input);
    assert.equal(
      initializeAutoEditProducerAuthoritySync(item.input).revisionHash,
      initialized.revisionHash,
    );
    const paths = producerAuthorityPaths(item.producer);
    fs.rmSync(paths.activeHead);
    const restarted = initializeAutoEditProducerAuthoritySync(item.input);
    assert.deepEqual(restarted, {
      status: "reused",
      revisionHash: initialized.revisionHash,
    });
    assert.equal(
      resolveProducerAuthorityHeadSync(item.producer),
      initialized.revisionHash,
    );
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

function staleInputsFailClosed(): void {
  const plan = autoEditGenesisFixture("stale-plan");
  try {
    fs.writeFileSync(
      plan.planPath,
      `${JSON.stringify({ ...plan.plan, changedAfterRender: true })}\n`,
    );
    assert.throws(
      () => initializeAutoEditProducerAuthoritySync(plan.input),
      /rendered plan or manifest checkpoint is stale/,
    );
  } finally {
    fs.rmSync(plan.root, { recursive: true, force: true });
  }
  const candidate = autoEditGenesisFixture("stale-candidate");
  try {
    fs.writeFileSync(candidate.candidatePath, "changed-after-render");
    assert.throws(
      () => initializeAutoEditProducerAuthoritySync(candidate.input),
      /artifact bytes changed|changed while read/,
    );
  } finally {
    fs.rmSync(candidate.root, { recursive: true, force: true });
  }
}

function missingFactsAreNamed(): void {
  const item = autoEditGenesisFixture("missing-lock");
  try {
    fs.rmSync(path.join(item.producer, "picture_locks"), {
      recursive: true,
      force: true,
    });
    assert.throws(
      () => initializeAutoEditProducerAuthoritySync(item.input),
      (error: unknown) => {
        assert.ok(error instanceof ProducerAuthorityReadinessError);
        assert.deepEqual(error.missingFacts, [
          "pictureLockHash",
          "transcriptTimingHash",
          "timelineMapHash",
          "projectionReceiptHash",
        ]);
        return true;
      },
    );
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

function initializeSyntheticShadow(
  item: ReturnType<typeof autoEditGenesisFixture>,
  sourceSnapshotSetHash: string,
): string {
  const facts = observeAutoEditGenesisFactsSync(item.input);
  const paths = producerAuthorityPaths(item.producer);
  const ledger = writeAuthorityObjectSync(paths.objects.requests, {
    schemaVersion: 1,
    kind: "legacy-shadow-empty-request-ledger",
  });
  const graph = writeAuthorityObjectSync(
    paths.objects.graphs, facts.renderGraph);
  return initializeProducerAuthoritySync(item.producer, {
    schemaVersion: 1,
    parentRevisionHash: null,
    planContentHash: facts.planContentHash,
    manifestHash: facts.manifestHash,
    sourceSnapshotSetHash,
    transcriptTimingHash: facts.transcriptTimingHash,
    timelineMapHash: facts.timelineMapHash,
    canvasProfileHash: facts.canvasProfileHash,
    destinationProfileHashes: facts.destinationProfileHashes,
    pictureLockHash: facts.pictureLockHash,
    workflowState: "PICTURE_LOCKED",
    requestLedgerHash: ledger.hash,
    renderGraphHash: graph.hash,
    projectionReceiptHash: null,
    authoritativeSidecars: {
      compatibilityLock: facts.pictureLockHash,
      renderedPlanFile: facts.planFileHash,
    },
  }, facts.planObject).revisionHash;
}

function legacySyntheticShadowIsAdopted(): void {
  const item = autoEditGenesisFixture("legacy-shadow-adoption");
  try {
    const synthetic = canonicalJsonSha256({
      kind: "compatibility-source-binding-v1",
      manifestHash: item.input.expectedManifestHash,
      transcriptDigest: item.transcriptHash,
    });
    const parent = initializeSyntheticShadow(item, synthetic);
    const adopted = initializeAutoEditProducerAuthoritySync(item.input);
    assert.equal(adopted.status, "advanced");
    const paths = producerAuthorityPaths(item.producer);
    const revision = parseProjectRevision(assertObjectHashSync(
      paths.objects.revisions, adopted.revisionHash));
    assert.equal(revision.parentRevisionHash, parent);
    assert.equal(revision.sourceSnapshotSetHash, item.sourceSetHash);
    const evidenceHash =
      revision.authoritativeSidecars.legacyCompatibilityShadowAdoptionV1;
    const evidence = assertObjectHashSync(
      paths.objects.receipts, evidenceHash) as Record<string, unknown>;
    assert.equal(evidence.legacySourceSnapshotSetHash, synthetic);
    assert.equal(
      evidence.admittedSourceSnapshotSetHash,
      item.sourceSetHash,
    );
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

function unknownSyntheticShadowHasMachineBlocker(): void {
  const item = autoEditGenesisFixture("unknown-shadow-source");
  try {
    initializeSyntheticShadow(item, "9".repeat(64));
    assert.throws(
      () => initializeAutoEditProducerAuthoritySync(item.input),
      (error: unknown) => {
        assert.ok(error instanceof ProducerAuthorityMigrationRequiredError);
        assert.equal(
          error.blocker.code,
          "PRODUCER_AUTHORITY_MIGRATION_REQUIRED",
        );
        assert.deepEqual(error.blocker.changedFacts, ["source set"]);
        assert.equal(
          error.blocker.expectedSourceSnapshotSetHash,
          item.sourceSetHash,
        );
        return true;
      },
    );
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

initializedRevision();
idempotentRestart();
staleInputsFailClosed();
missingFactsAreNamed();
legacySyntheticShadowIsAdopted();
unknownSyntheticShadowHasMachineBlocker();
console.log("producer Auto Edit genesis tests passed");
