import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  palmierCandidateReservationValue,
  parsePalmierSagaCandidateProofV1,
  parsePalmierSagaObservationV1,
  type PalmierSagaCandidateProofV1,
} from "@/lib/producer/contracts/palmier-saga-bridge";
import { parsePalmierCommitSagaV1 } from
  "@/lib/producer/contracts/palmier-commit-saga";
import { parseProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import {
  commitApprovedPalmierCandidateSync,
  type PalmierNativeCommitBoundaryV1,
  type PalmierNativeSagaBridgeV1,
} from "../producer-palmier-native-commit";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
} from "../producer-authority-files";
import { resolveProducerAuthorityHeadSync } from "../producer-revision-head";
import { palmierCandidateQcState } from "../palmier-candidate-qc";

const hash = (value: string): string => value.repeat(64);
const parentId = "palmier-parent";
const candidateId = "palmier-candidate";
const parentTimelineHash = hash("a");
const timelineHash = hash("b");

function proof(): PalmierSagaCandidateProofV1 {
  const stable = {
    schemaVersion: 1 as const,
    projectId: "palmier-project",
    expectedParentId: parentId,
    expectedParentTimelineHash: parentTimelineHash,
    candidateId,
    timelineHash,
    approvalDigest: hash("c"),
    manifestHash: hash("d"),
    inputAuthorityDigest: hash("e"),
    transcriptTimingHash: hash("f"),
    nativePlanHash: hash("1"),
    canvasProfileHash: hash("2"),
  };
  return parsePalmierSagaCandidateProofV1({
    ...stable,
    ok: true,
    status: "saga-candidate-proved",
    candidateHash: canonicalJsonSha256(
      palmierCandidateReservationValue(stable)),
    provedAt: "2026-07-30T12:00:00.000Z",
  });
}

class Bridge implements PalmierNativeSagaBridgeV1 {
  head: "parent" | "candidate" | "foreign" = "parent";
  proofReadable = true;
  activationCalls = 0;
  failPromotion: "none" | "before" | "after" = "none";

  proveCandidate(): PalmierSagaCandidateProofV1 {
    if (!this.proofReadable) throw new Error("candidate proof unavailable");
    return proof();
  }

  observeHead() {
    const exact = this.head === "candidate";
    return parsePalmierSagaObservationV1({
      schemaVersion: 1,
      ok: true,
      status: "saga-head-observed",
      headId: this.head === "parent"
        ? parentId : this.head === "candidate" ? candidateId : "foreign-head",
      candidateHash: exact ? proof().candidateHash : null,
      timelineHash: exact ? timelineHash : null,
      observedAt: "2026-07-30T12:00:01.000Z",
    });
  }

  promoteCandidate(expected: string, candidate: string): void {
    assert.equal(expected, parentId);
    assert.equal(candidate, candidateId);
    this.activationCalls += 1;
    if (this.failPromotion === "before") {
      this.failPromotion = "none";
      throw new Error("promotion failed before effect");
    }
    this.head = "candidate";
    if (this.failPromotion === "after") {
      this.failPromotion = "none";
      throw new Error("process lost after external effect");
    }
  }
}

function fixture(): string {
  return fs.realpathSync(
    fs.mkdtempSync(path.join(os.tmpdir(), "sniper-palmier-commit-")),
  );
}

function sagaFiles(producerDir: string): string[] {
  const root = producerAuthorityPaths(producerDir).sagas;
  return fs.readdirSync(root)
    .filter((name) => name.endsWith(".json"))
    .map((name) => path.join(root, name));
}

function committedPathIsIdempotent(): void {
  const producerDir = fixture();
  try {
    const bridge = new Bridge();
    const first = commitApprovedPalmierCandidateSync(
      producerDir, bridge);
    assert.equal(first.status, "candidate-promoted");
    assert.equal(first.sagaState, "COMMITTED");
    assert.equal(bridge.activationCalls, 1);
    const head = resolveProducerAuthorityHeadSync(producerDir);
    assert.equal(head, first.localRevisionHash);
    const paths = producerAuthorityPaths(producerDir);
    const child = parseProjectRevision(assertObjectHashSync(
      paths.objects.revisions, head));
    assert.equal(child.workflowState, "QC_APPROVED");
    assert.equal(child.timelineMapHash, timelineHash);
    assert.ok(
      child.authoritativeSidecars.palmierNativeDualCommitReservationV1);
    const replay = commitApprovedPalmierCandidateSync(
      producerDir, bridge);
    assert.deepEqual(replay, first);
    assert.equal(bridge.activationCalls, 1);
    assert.equal(sagaFiles(producerDir).length, 1);
  } finally {
    fs.rmSync(producerDir, { recursive: true, force: true });
  }
}

function ambiguousExternalEffectRecoversExactly(): void {
  const producerDir = fixture();
  try {
    const bridge = new Bridge();
    bridge.failPromotion = "after";
    assert.throws(
      () => commitApprovedPalmierCandidateSync(producerDir, bridge),
      /process lost after external effect/,
    );
    fs.writeFileSync(path.join(
      producerDir, "palmier.timeline-candidate.json"), JSON.stringify({
      schemaVersion: 1,
      status: "promoted",
      projectId: "palmier-project",
      timelineId: candidateId,
      fingerprint: timelineHash,
    }));
    const recovering = palmierCandidateQcState(producerDir);
    assert.equal(recovering.state, "commit-recovery");
    assert.equal(recovering.canPromote, true);
    const parentHead = resolveProducerAuthorityHeadSync(producerDir);
    const recovered = commitApprovedPalmierCandidateSync(
      producerDir, bridge);
    assert.notEqual(recovered.localRevisionHash, parentHead);
    assert.equal(recovered.sagaState, "COMMITTED");
    assert.equal(bridge.activationCalls, 1);
    assert.equal(palmierCandidateQcState(producerDir).state, "none");
  } finally {
    fs.rmSync(producerDir, { recursive: true, force: true });
  }
}

function foreignStartupHeadPersistsReconciliation(): void {
  const producerDir = fixture();
  try {
    const bridge = new Bridge();
    bridge.failPromotion = "before";
    assert.throws(
      () => commitApprovedPalmierCandidateSync(producerDir, bridge),
      /promotion failed before effect/,
    );
    bridge.head = "foreign";
    assert.throws(
      () => commitApprovedPalmierCandidateSync(producerDir, bridge),
      /RECONCILIATION_REQUIRED/,
    );
    const saga = parsePalmierCommitSagaV1(JSON.parse(
      fs.readFileSync(sagaFiles(producerDir)[0], "utf8"),
    ));
    assert.equal(saga.state, "RECONCILIATION_REQUIRED");
    assert.equal(
      resolveProducerAuthorityHeadSync(producerDir),
      saga.expectedLocalParentHash,
    );
  } finally {
    fs.rmSync(producerDir, { recursive: true, force: true });
  }
}

function failedRestartReproofPersistsReconciliation(): void {
  const producerDir = fixture();
  try {
    const bridge = new Bridge();
    bridge.failPromotion = "before";
    assert.throws(
      () => commitApprovedPalmierCandidateSync(producerDir, bridge),
      /promotion failed before effect/,
    );
    bridge.proofReadable = false;
    assert.throws(
      () => commitApprovedPalmierCandidateSync(producerDir, bridge),
      /RECONCILIATION_REQUIRED/,
    );
    const saga = parsePalmierCommitSagaV1(JSON.parse(
      fs.readFileSync(sagaFiles(producerDir)[0], "utf8"),
    ));
    assert.equal(saga.state, "RECONCILIATION_REQUIRED");
    assert.match(saga.failureReason ?? "", /candidate proof unavailable/);
  } finally {
    fs.rmSync(producerDir, { recursive: true, force: true });
  }
}

function productionReservationBoundariesRecover(): void {
  const boundaries: PalmierNativeCommitBoundaryV1[] = [
    "after-local-child-reserved",
    "after-saga-initialized",
  ];
  for (const boundary of boundaries) {
    const producerDir = fixture();
    try {
      const bridge = new Bridge();
      assert.throws(
        () => commitApprovedPalmierCandidateSync(
          producerDir,
          bridge,
          {
            after: (reached) => {
              if (reached === boundary) throw new Error(`crash:${boundary}`);
            },
          },
        ),
        new RegExp(`crash:${boundary}`),
      );
      assert.equal(bridge.activationCalls, 0);
      const recovered = commitApprovedPalmierCandidateSync(
        producerDir, bridge);
      assert.equal(recovered.sagaState, "COMMITTED");
      assert.equal(bridge.activationCalls, 1);
      assert.equal(
        resolveProducerAuthorityHeadSync(producerDir),
        recovered.localRevisionHash,
      );
    } finally {
      fs.rmSync(producerDir, { recursive: true, force: true });
    }
  }
}

function bridgeContractFailsClosed(): void {
  const candidateProof = proof();
  assert.throws(
    () => parsePalmierSagaCandidateProofV1({
      ...candidateProof,
      unowned: true,
    }),
    /unsupported fields/,
  );
  assert.throws(
    () => parsePalmierSagaCandidateProofV1({
      ...candidateProof,
      timelineHash: hash("9"),
    }),
    /does not match its reservation/,
  );
  assert.throws(
    () => parsePalmierSagaObservationV1({
      ...new Bridge().observeHead(),
      unowned: true,
    }),
    /unsupported fields/,
  );
}

committedPathIsIdempotent();
ambiguousExternalEffectRecoversExactly();
foreignStartupHeadPersistsReconciliation();
failedRestartReproofPersistsReconciliation();
productionReservationBoundariesRecover();
bridgeContractFailsClosed();
console.log("producer-palmier-native-commit tests passed");
