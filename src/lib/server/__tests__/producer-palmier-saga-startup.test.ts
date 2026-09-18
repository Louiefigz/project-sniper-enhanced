import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { PalmierCommitSagaV1 } from
  "@/lib/producer/contracts/palmier-commit-saga";
import {
  initializeProducerPalmierSagaSync,
  recoverPalmierSagaSync,
  type PalmierObservedHeadV1,
  type PalmierSagaAdapterV1,
} from "../producer-palmier-saga";

const hash = (value: string): string => value.repeat(64);
const parentHash = hash("a");
const childHash = hash("b");
const candidateHash = hash("c");
const timelineHash = hash("d");
const parentId = "palmier-parent";
const candidateId = "palmier-candidate";

function initial(): PalmierCommitSagaV1 {
  return {
    schemaVersion: 1,
    sagaId: "10000000-0000-4000-8000-000000000001",
    idempotencyKey: "20000000-0000-4000-8000-000000000001",
    state: "PREPARING",
    expectedLocalParentHash: parentHash,
    reservedLocalChildHash: childHash,
    expectedPalmierParentId: parentId,
    reservedPalmierCandidateId: candidateId,
    reservedPalmierCandidateHash: candidateHash,
    reservedPalmierTimelineHash: timelineHash,
    activationReadback: null,
    updatedAt: "2026-07-29T12:00:00.000Z",
  };
}

type PalmierState = "parent" | "child" | "foreign" | "partial";
type LocalState = "parent" | "child" | "foreign" | "unreadable";

function palmierObservation(state: PalmierState): PalmierObservedHeadV1 {
  const common = { observedAt: "2026-07-29T12:00:01.000Z" };
  if (state === "parent") {
    return { ...common, headId: parentId, candidateHash: null, timelineHash: null };
  }
  if (state === "child") {
    return { ...common, headId: candidateId, candidateHash, timelineHash };
  }
  if (state === "partial") {
    return { ...common, headId: candidateId, candidateHash, timelineHash: null };
  }
  return {
    ...common,
    headId: "palmier-foreign",
    candidateHash: null,
    timelineHash: null,
  };
}

class MatrixAdapter implements PalmierSagaAdapterV1 {
  proofValid = true;
  proofCalls = 0;
  activationCalls = 0;
  localCalls = 0;

  constructor(
    public palmier: PalmierObservedHeadV1,
    public local: string | null,
  ) {}

  proveCandidates(): boolean {
    this.proofCalls += 1;
    return this.proofValid;
  }

  observePalmier(): PalmierObservedHeadV1 {
    return { ...this.palmier };
  }

  activatePalmier(expected: string, candidate: string): void {
    assert.equal(expected, parentId);
    assert.equal(candidate, candidateId);
    this.activationCalls += 1;
    this.palmier = palmierObservation("child");
  }

  observeLocal(): string {
    if (this.local === null) throw new Error("local head is partial");
    return this.local;
  }

  commitLocal(expected: string, child: string): void {
    assert.equal(this.local, expected);
    this.localCalls += 1;
    this.local = child;
  }
}

function fixture(): { root: string; file: string } {
  const root = fs.realpathSync(
    fs.mkdtempSync(path.join(os.tmpdir(), "sniper-palmier-startup-")),
  );
  return {
    root,
    file: initializeProducerPalmierSagaSync(root, initial()).filePath,
  };
}

const palmierStates: PalmierState[] = [
  "parent", "child", "foreign", "partial",
];
const localStates: LocalState[] = [
  "parent", "child", "foreign", "unreadable",
];
for (const palmierState of palmierStates) {
  for (const localState of localStates) {
    const item = fixture();
    try {
      const local = localState === "parent"
        ? parentHash : localState === "child"
          ? childHash : localState === "foreign" ? hash("f") : null;
      const adapter = new MatrixAdapter(
        palmierObservation(palmierState),
        local,
      );
      const result = recoverPalmierSagaSync(item.file, adapter);
      const exactInput = ["parent", "child"].includes(palmierState)
        && ["parent", "child"].includes(localState);
      assert.equal(result.state, exactInput
        ? "COMMITTED" : "RECONCILIATION_REQUIRED",
      `${palmierState}/${localState}`);
      if (result.state === "COMMITTED") {
        assert.equal(adapter.palmier.headId, candidateId);
        assert.equal(adapter.local, childHash);
      }
      assert.ok(adapter.activationCalls <= 1);
      assert.ok(adapter.localCalls <= 1);
    } finally {
      fs.rmSync(item.root, { recursive: true, force: true });
    }
  }
}

{
  const item = fixture();
  try {
    const adapter = new MatrixAdapter(
      palmierObservation("parent"),
      parentHash,
    );
    assert.throws(() => recoverPalmierSagaSync(item.file, adapter, {
      after: (boundary) => {
        if (boundary === "after-candidates-proved") {
          throw new Error("crash after candidate proof");
        }
      },
    }), /crash after candidate proof/);
    adapter.proofValid = false;
    const result = recoverPalmierSagaSync(item.file, adapter);
    assert.equal(result.state, "RECONCILIATION_REQUIRED");
    assert.match(result.failureReason ?? "", /re-proof failed/);
    assert.equal(adapter.activationCalls, 0);
    assert.equal(adapter.localCalls, 0);
    assert.equal(adapter.proofCalls, 2);
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

console.log("producer-palmier-saga-startup tests passed");
