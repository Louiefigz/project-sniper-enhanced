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
  type PalmierSagaBoundaryV1,
} from "../producer-palmier-saga";

const hash = (value: string): string => value.repeat(64);
const initial = (): PalmierCommitSagaV1 => ({
  schemaVersion: 1,
  sagaId: "10000000-0000-4000-8000-000000000001",
  idempotencyKey: "20000000-0000-4000-8000-000000000001",
  state: "PREPARING",
  expectedLocalParentHash: hash("a"),
  reservedLocalChildHash: hash("b"),
  expectedPalmierParentId: "palmier-parent",
  reservedPalmierCandidateId: "palmier-candidate",
  reservedPalmierCandidateHash: hash("c"),
  reservedPalmierTimelineHash: hash("d"),
  activationReadback: null,
  updatedAt: "2026-07-29T12:00:00.000Z",
});

class Adapter implements PalmierSagaAdapterV1 {
  palmier: PalmierObservedHeadV1 = {
    headId: "palmier-parent",
    candidateHash: null,
    timelineHash: null,
    observedAt: "2026-07-29T12:00:01.000Z",
  };
  local = hash("a");
  candidatesValid = true;
  activationCalls = 0;
  localCalls = 0;
  palmierReadable = true;
  localReadable = true;
  candidateProofReadable = true;
  driftPalmierOnLocalCommit = false;

  proveCandidates(): boolean {
    if (!this.candidateProofReadable) {
      throw new Error("candidate store offline");
    }
    return this.candidatesValid;
  }

  observePalmier(): PalmierObservedHeadV1 {
    if (!this.palmierReadable) throw new Error("Palmier offline");
    return { ...this.palmier };
  }

  activatePalmier(expected: string, candidate: string): void {
    assert.equal(expected, "palmier-parent");
    assert.equal(candidate, "palmier-candidate");
    this.activationCalls += 1;
    this.palmier = {
      headId: candidate,
      candidateHash: hash("c"),
      timelineHash: hash("d"),
      observedAt: "2026-07-29T12:00:02.000Z",
    };
  }

  observeLocal(): string {
    if (!this.localReadable) throw new Error("local head unreadable");
    return this.local;
  }

  commitLocal(expected: string, child: string): void {
    assert.equal(this.local, expected);
    this.localCalls += 1;
    this.local = child;
    if (this.driftPalmierOnLocalCommit) {
      this.palmier = {
        ...this.palmier,
        headId: "foreign-after-local-effect",
        candidateHash: null,
        timelineHash: null,
      };
    }
  }
}

function unreadableStartupStateReconciles(): void {
  for (const lane of ["candidate", "palmier", "local"] as const) {
    const item = fixture();
    try {
      const adapter = new Adapter();
      if (lane === "candidate") adapter.candidateProofReadable = false;
      if (lane === "palmier") adapter.palmierReadable = false;
      if (lane === "local") {
        adapter.palmier = {
          headId: "palmier-candidate",
          candidateHash: hash("c"),
          timelineHash: hash("d"),
          observedAt: "2026-07-29T12:00:02.000Z",
        };
        adapter.localReadable = false;
      }
      const result = recoverPalmierSagaSync(item.file, adapter);
      assert.equal(result.state, "RECONCILIATION_REQUIRED");
      assert.match(result.failureReason ?? "", /unreadable|offline/);
    } finally {
      fs.rmSync(item.root, { recursive: true, force: true });
    }
  }
}

function fixture(): { root: string; file: string } {
  const root = fs.realpathSync(
    fs.mkdtempSync(path.join(os.tmpdir(), "sniper-palmier-saga-")),
  );
  const file = initializeProducerPalmierSagaSync(root, initial()).filePath;
  return { root, file };
}

const boundaries: PalmierSagaBoundaryV1[] = [
  "after-candidates-proved",
  "after-palmier-activating",
  "after-palmier-effect",
  "after-palmier-active",
  "after-local-committing",
  "after-local-effect",
  "after-committed",
];
for (const boundary of boundaries) {
  const item = fixture();
  try {
    const adapter = new Adapter();
    assert.throws(
      () => recoverPalmierSagaSync(item.file, adapter, {
        after: (current) => {
          if (current === boundary) throw new Error(`fault at ${boundary}`);
        },
      }),
      new RegExp(`fault at ${boundary}`),
    );
    const recovered = recoverPalmierSagaSync(item.file, adapter);
    assert.equal(recovered.state, "COMMITTED");
    assert.equal(adapter.palmier.headId, "palmier-candidate");
    assert.equal(adapter.local, hash("b"));
    assert.ok(adapter.activationCalls <= 1);
    assert.ok(adapter.localCalls <= 1);
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

{
  const item = fixture();
  try {
    const adapter = new Adapter();
    adapter.palmier = {
      ...adapter.palmier,
      headId: "foreign-head",
    };
    const result = recoverPalmierSagaSync(item.file, adapter);
    assert.equal(result.state, "RECONCILIATION_REQUIRED");
    assert.match(result.failureReason ?? "", /foreign/);
    assert.equal(adapter.activationCalls, 0);
    assert.equal(adapter.localCalls, 0);
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

{
  const item = fixture();
  try {
    const adapter = new Adapter();
    adapter.palmier = {
      headId: "palmier-candidate",
      candidateHash: hash("e"),
      timelineHash: hash("d"),
      observedAt: "2026-07-29T12:00:02.000Z",
    };
    assert.equal(
      recoverPalmierSagaSync(item.file, adapter).state,
      "RECONCILIATION_REQUIRED",
    );
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

{
  const item = fixture();
  try {
    const adapter = new Adapter();
    adapter.local = hash("f");
    const result = recoverPalmierSagaSync(item.file, adapter);
    assert.equal(result.state, "RECONCILIATION_REQUIRED");
    assert.match(result.failureReason ?? "", /local head/);
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

{
  const item = fixture();
  try {
    const adapter = new Adapter();
    adapter.candidatesValid = false;
    assert.equal(recoverPalmierSagaSync(item.file, adapter).state, "ABORTED");
    assert.equal(adapter.activationCalls, 0);
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

{
  const item = fixture();
  try {
    const adapter = new Adapter();
    adapter.driftPalmierOnLocalCommit = true;
    const result = recoverPalmierSagaSync(item.file, adapter);
    assert.equal(result.state, "RECONCILIATION_REQUIRED");
    assert.match(result.failureReason ?? "", /during local commit/);
    assert.equal(adapter.local, hash("b"));
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

unreadableStartupStateReconciles();
console.log("producer-palmier-saga tests passed");
