import assert from "node:assert/strict";
import {
  appendFileSync,
  mkdtempSync,
  readFileSync,
  rmSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import type { TimelineIdentity } from
  "../../../app/api/producer/live-build/authority";
import {
  appendLiveBuildHead,
  appendLiveBuildOperationEvent,
  closeLiveBuildJournal,
  emptyLiveBuildJournal,
  liveBuildJournalCounts,
  type LiveBuildJournalLedger,
} from "../../../app/api/producer/live-build/journal";
import { isLiveBuildMutationTool } from
  "../../../app/api/producer/live-build/process";
import {
  LiveBuildReconciliationError,
  reconcileLiveBuildResume,
} from "../../../app/api/producer/live-build/reconciliation";
import {
  liveBuildJournalPath,
  prepareLiveBuildState,
  readLiveBuildState,
  type LiveBuildState,
} from "../../../app/api/producer/live-build/state";

const INITIAL = "a".repeat(64);
const CHANGED = "b".repeat(64);

function fixture(dir: string): {
  state: LiveBuildState;
  ledger: LiveBuildJournalLedger;
  observed: TimelineIdentity;
} {
  const state = prepareLiveBuildState({
    dir,
    planHash: "c".repeat(64),
    doctrineHash: "d".repeat(64),
    projectId: "project",
    projectPath: "/tmp/project.palmier",
    parentTimelineId: "parent",
    parentFingerprint: "e".repeat(64),
    candidateTimelineId: "candidate",
    candidateFingerprint: INITIAL,
  }, false);
  const ledger = emptyLiveBuildJournal();
  appendLiveBuildHead(dir, ledger, INITIAL);
  return {
    state,
    ledger,
    observed: {
      projectId: "project",
      timelineId: "candidate",
      fingerprint: INITIAL,
    },
  };
}

function applying(
  dir: string,
  ledger: LiveBuildJournalLedger,
  operationId: string,
  input: Record<string, unknown> = { words: ["um"] },
): void {
  appendLiveBuildOperationEvent(dir, ledger, {
    event: "palmier_op",
    operationId,
    tool: "remove_words",
    input,
    status: "applying",
    elapsedMs: 1,
  });
}

function result(
  dir: string,
  ledger: LiveBuildJournalLedger,
  operationId: string,
  status: "applied" | "failed",
): void {
  appendLiveBuildOperationEvent(dir, ledger, {
    event: "palmier_op_result",
    operationId,
    status,
    elapsedMs: 2,
  });
}

function temporary(run: (dir: string) => void): void {
  const dir = mkdtempSync(path.join(os.tmpdir(), "sniper-live-reconcile-"));
  try { run(dir); } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

temporary((dir) => {
  const { state, observed } = fixture(dir);
  const reconciled = reconcileLiveBuildResume(dir, state, observed);
  assert.equal(reconciled.restartSession, false);
  assert.deepEqual(liveBuildJournalCounts(reconciled.ledger), {
    operationsSeen: 0,
    operationsCompleted: 0,
  });
});

temporary((dir) => {
  const { state, ledger, observed } = fixture(dir);
  applying(dir, ledger, "pending");
  const reconciled = reconcileLiveBuildResume(dir, state, observed);
  assert.equal(reconciled.restartSession, true);
  assert.equal(
    reconciled.ledger.operations.get("pending")?.status, "not-applied");
  assert.deepEqual(
    reconciled.state.resumeAuthority?.resolvedNotAppliedIds, ["pending"]);
});

temporary((dir) => {
  const { state, ledger, observed } = fixture(dir);
  applying(dir, ledger, "ambiguous");
  assert.throws(
    () => reconcileLiveBuildResume(
      dir, state, { ...observed, fingerprint: CHANGED }),
    LiveBuildReconciliationError,
  );
  const paused = readLiveBuildState(dir);
  assert.equal(paused?.status, "reconciliation_required");
  assert.equal(
    paused?.reconciliation?.reason,
    "applying-operation-has-ambiguous-visible-effect",
  );
  assert.deepEqual(paused?.reconciliation?.resolutionActions, [
    "external-adopt-visible-head",
    "external-adopt-visible-head-and-fork-candidate",
  ]);
  assert.equal(paused?.reconciliation?.resolutionOwner, "external-operator");
  assert.equal(paused?.reconciliation?.automaticResumeAllowed, false);
});

for (const prior of ["applying", "failed", "applied"] as const) {
  temporary((dir) => {
    const { ledger } = fixture(dir);
    applying(dir, ledger, `prior-${prior}`);
    if (prior !== "applying") result(dir, ledger, `prior-${prior}`, prior);
    const before = readFileSync(liveBuildJournalPath(dir), "utf8");
    assert.throws(
      () => applying(dir, ledger, `retry-${prior}`),
      /fail-closed replay fence/,
    );
    assert.equal(readFileSync(liveBuildJournalPath(dir), "utf8"), before);
  });
}

temporary((dir) => {
  const { state, ledger, observed } = fixture(dir);
  applying(dir, ledger, "not-applied");
  const reconciled = reconcileLiveBuildResume(dir, state, observed);
  assert.doesNotThrow(
    () => applying(dir, reconciled.ledger, "safe-retry"));
});

temporary((dir) => {
  const { ledger } = fixture(dir);
  applying(dir, ledger, "applied");
  result(dir, ledger, "applied", "applied");
  const before = liveBuildJournalCounts(ledger);
  assert.doesNotThrow(
    () => result(dir, ledger, "applied", "applied"));
  assert.deepEqual(liveBuildJournalCounts(ledger), before);
  assert.throws(
    () => result(dir, ledger, "applied", "failed"),
    /conflicting or late results/,
  );
  assert.doesNotThrow(
    () => applying(dir, ledger, "other-window", { words: ["actually"] }));
});

temporary((dir) => {
  const { state, ledger, observed } = fixture(dir);
  applying(dir, ledger, "no-delta");
  result(dir, ledger, "no-delta", "applied");
  const before = readFileSync(liveBuildJournalPath(dir), "utf8");
  assert.throws(
    () => appendLiveBuildHead(dir, ledger, INITIAL),
    /produced no candidate delta/,
  );
  assert.equal(readFileSync(liveBuildJournalPath(dir), "utf8"), before);
  assert.throws(
    () => reconcileLiveBuildResume(dir, state, observed),
    LiveBuildReconciliationError,
  );
  assert.equal(
    readLiveBuildState(dir)?.reconciliation?.reason,
    "applied-operation-produced-no-candidate-delta",
  );
});

temporary((dir) => {
  const { ledger } = fixture(dir);
  const before = readFileSync(liveBuildJournalPath(dir), "utf8");
  assert.throws(
    () => applying(
      dir, ledger, "oversized", { entries: ["x".repeat(20_000)] }),
    /durable journal limit/,
  );
  assert.equal(readFileSync(liveBuildJournalPath(dir), "utf8"), before);
  assert.equal(ledger.operations.has("oversized"), false);
});

for (const fragment of [
  "{\"at\":\"now\",\"event\":\"palmier_op\"",
  "{not-json}\n",
]) {
  temporary((dir) => {
    const { state, observed } = fixture(dir);
    appendFileSync(liveBuildJournalPath(dir), fragment);
    assert.throws(
      () => reconcileLiveBuildResume(dir, state, observed),
      LiveBuildReconciliationError,
    );
    assert.match(
      readLiveBuildState(dir)?.reconciliation?.reason ?? "",
      /^journal-unreadable:/u,
    );
  });
}

temporary((dir) => {
  const { state, ledger, observed } = fixture(dir);
  applying(dir, ledger, "verified");
  result(dir, ledger, "verified", "applied");
  appendLiveBuildHead(dir, ledger, CHANGED);
  const reconciled = reconcileLiveBuildResume(
    dir, state, { ...observed, fingerprint: CHANGED });
  assert.equal(reconciled.restartSession, false);
  assert.deepEqual(
    reconciled.state.resumeAuthority?.verifiedOperations.map(
      (row) => row.operationId),
    ["verified"],
  );
  assert.deepEqual(liveBuildJournalCounts(reconciled.ledger), {
    operationsSeen: 1,
    operationsCompleted: 1,
  });
});

temporary((dir) => {
  const { state, observed } = fixture(dir);
  assert.throws(
    () => reconcileLiveBuildResume(
      dir, state, { ...observed, fingerprint: CHANGED }),
    LiveBuildReconciliationError,
  );
  assert.equal(
    readLiveBuildState(dir)?.reconciliation?.reason,
    "manual-or-foreign-candidate-drift",
  );
});

temporary((dir) => {
  const { ledger } = fixture(dir);
  for (const [index, tool] of ["get_projects", "detect_beats"].entries()) {
    const operationId = `read-${index}`;
    appendLiveBuildOperationEvent(dir, ledger, {
      event: "palmier_op", operationId, tool, input: {},
      status: "applying", elapsedMs: 1,
    });
    result(dir, ledger, operationId, "applied");
    assert.equal(isLiveBuildMutationTool(tool), false);
  }
  appendLiveBuildHead(dir, ledger, INITIAL);
  assert.deepEqual(liveBuildJournalCounts(ledger), {
    operationsSeen: 0,
    operationsCompleted: 0,
  });
  assert.throws(
    () => closeLiveBuildJournal(dir, INITIAL),
    /no applied mutation/,
  );
});

console.log(
  "palmier-live-build-reconciliation.test.ts: all assertions passed");
