import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileSha256 } from "../auto-edit-hash";
import {
  promoteApprovedCandidateWithRenderGraph,
} from "../current-render-graph-candidate";
import { runCandidateCommand } from
  "../current-render-graph-candidate-command";
import { observeCurrentRenderGraphAuthoritySync } from
  "../current-render-graph-authority";
import { assertApprovedProducerRevisionSync } from
  "../producer-approved-revision-authority";
import {
  corruptChildCache,
  p5FaultFixture,
  selectForeign,
  type P5FaultBoundary,
  type P5FaultFixture,
  type P5FaultKind,
} from "./_p5-render-graph-fault-fixture";

type Outcome = "exact-old" | "exact-new" | "blocked";

const FAULTS: P5FaultKind[] = [
  "cancellation", "disk-sync", "stale-parent", "bad-cache",
];
const BOUNDARY_COVERAGE = {
  "after-intent": true,
  "after-backups": true,
  "after-transfers": true,
  "after-commit": true,
  "after-committed": true,
  "after-rollback-marked": true,
  "after-move-cleanup": true,
  "after-recovery-directory-removed": true,
  "after-intent-removed": true,
} as const satisfies Record<P5FaultBoundary, true>;
const BOUNDARIES = Object.keys(BOUNDARY_COVERAGE) as P5FaultBoundary[];

function activeIdentity(item: P5FaultFixture): {
  graphHash: string;
  receiptHash: string;
  finalHash: string;
} {
  const pointer = JSON.parse(fs.readFileSync(path.join(
    item.producer, ".render-graph-v1", "ACTIVE.json",
  ), "utf8")) as { graphHash: string; receiptHash: string };
  const graph = JSON.parse(fs.readFileSync(path.join(
    item.producer, ".render-graph-v1", "generations",
    pointer.graphHash, "graph.json",
  ), "utf8")) as {
    rootNodeId: string;
    nodes: Array<{ nodeId: string; outputArtifactHash: string | null }>;
  };
  const receipt = JSON.parse(fs.readFileSync(path.join(
    item.producer, ".render-graph-v1", "generations", pointer.graphHash,
    "receipts", `${pointer.receiptHash}.json`,
  ), "utf8")) as {
    artifacts: Array<{ nodeId: string; path: string; sha256: string }>;
  };
  const root = graph.nodes.find((row) => row.nodeId === graph.rootNodeId);
  const artifact = receipt.artifacts.find(
    (row) => row.nodeId === graph.rootNodeId);
  const finalPath = path.join(item.producer, "final.mp4");
  const finalHash = fileSha256(finalPath)!;
  assert.equal(root?.outputArtifactHash, finalHash);
  assert.equal(artifact?.path, finalPath);
  assert.equal(artifact?.sha256, finalHash);
  return { ...pointer, finalHash };
}

function exactGraph(
  item: P5FaultFixture,
  graphHash: string,
  mediaHash: string,
): void {
  observeCurrentRenderGraphAuthoritySync({
    producerDir: item.producer,
    expectedGraphHash: graphHash,
    expectedFinalHash: mediaHash,
  });
}

function assertBlockedGraph(
  item: P5FaultFixture,
  active: ReturnType<typeof activeIdentity>,
  fault: P5FaultKind,
): void {
  if (active.graphHash === item.parent.graphHash) {
    exactGraph(item, item.parent.graphHash, item.parent.mediaHash);
    return;
  }
  if (active.graphHash === item.foreign.graphHash) {
    exactGraph(item, item.foreign.graphHash, item.foreign.mediaHash);
    return;
  }
  assert.equal(active.graphHash, item.childGraphHash);
  assert.equal(active.finalHash, item.candidateHash);
  if (fault === "bad-cache") {
    assert.throws(
      () => exactGraph(item, item.childGraphHash, item.candidateHash),
      /artifact bytes changed/,
    );
    return;
  }
  exactGraph(item, item.childGraphHash, item.candidateHash);
}

function classify(
  item: P5FaultFixture,
  fault: P5FaultKind,
  boundary: P5FaultBoundary,
): Outcome {
  const label = `${fault}/${boundary}`;
  const active = activeIdentity(item);
  if (fs.existsSync(item.reconciliationPath)) {
    const marker = JSON.parse(fs.readFileSync(
      item.reconciliationPath, "utf8",
    )) as { schemaVersion?: number; phase?: string; status?: string };
    assert.equal(marker.schemaVersion, 1, label);
    assert.equal(
      marker.phase === "reconciliation-required"
        || marker.status === "reconciliation-required",
      true,
      label,
    );
    assertBlockedGraph(item, active, fault);
    return "blocked";
  }
  if (active.graphHash === item.parent.graphHash) {
    assert.equal(fs.existsSync(item.terminalPath), false, label);
    exactGraph(item, item.parent.graphHash, item.parent.mediaHash);
    return "exact-old";
  }
  if (active.graphHash === item.childGraphHash && fault !== "bad-cache") {
    assert.equal(active.finalHash, item.candidateHash, label);
    const terminalDirectory = path.dirname(item.terminalPath);
    const terminalNames = fs.existsSync(terminalDirectory)
      ? fs.readdirSync(terminalDirectory) : [];
    assert.equal(
      fs.existsSync(item.terminalPath),
      true,
      `${label}: expected ${item.terminalPath}; found ${terminalNames}`,
    );
    exactGraph(item, item.childGraphHash, item.candidateHash);
    assertApprovedProducerRevisionSync({
      producerDir: item.producer,
      planPath: item.planPath,
      manifestPath: item.manifestPath,
      expectedFinalHash: item.candidateHash,
    });
    return "exact-new";
  }
  assert.fail(`${label}: unblocked state is neither exact old nor exact new`);
}

function inject(item: P5FaultFixture, fault: P5FaultKind): never {
  if (fault === "stale-parent") selectForeign(item);
  if (fault === "bad-cache") corruptChildCache(item);
  if (fault === "cancellation") {
    throw new DOMException("injected local cancellation", "AbortError");
  }
  throw new Error(`injected local ${fault} fault`);
}

function runCase(
  fault: P5FaultKind,
  boundary: P5FaultBoundary,
): Outcome {
  const item = p5FaultFixture(`${fault}-${boundary}`);
  let injected = false;
  const command = (args: string[]) => {
    if (boundary === "after-rollback-marked"
        && ["activate", "candidate-active"].includes(args[0] ?? "")) {
      throw new Error("injected activation failure to enter rollback");
    }
    return runCandidateCommand(args);
  };
  try {
    assert.throws(() => promoteApprovedCandidateWithRenderGraph(
      item.candidate, item.producer, item.record, {
        command,
        afterPromotionBoundary: (observed) => {
          if (!injected && observed === boundary) {
            injected = true;
            inject(item, fault);
          }
        },
      },
    ));
    assert.equal(injected, true);
    return classify(item, fault, boundary);
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

function expectedOutcome(
  fault: P5FaultKind,
  boundary: P5FaultBoundary,
): Outcome {
  if (fault === "stale-parent") return "blocked";
  if (fault === "bad-cache") {
    return [
      "after-intent", "after-backups", "after-transfers",
    ].includes(boundary) ? "exact-old" : "blocked";
  }
  if (["after-intent", "after-backups", "after-transfers"]
    .includes(boundary)) return "exact-old";
  return ["after-commit", "after-committed"].includes(boundary)
    ? "exact-new" : "blocked";
}

const observed = new Map<Outcome, number>([
  ["exact-old", 0], ["exact-new", 0], ["blocked", 0],
]);
for (const fault of FAULTS) {
  for (const boundary of BOUNDARIES) {
    const outcome = runCase(fault, boundary);
    assert.equal(
      outcome,
      expectedOutcome(fault, boundary),
      `${fault}/${boundary}`,
    );
    observed.set(outcome, observed.get(outcome)! + 1);
  }
}

assert.deepEqual(Object.fromEntries(observed), {
  "exact-old": 9,
  "exact-new": 4,
  blocked: 23,
});
assert.equal([...observed.values()].reduce((sum, value) => sum + value), 36);
console.log("P5 local render-graph fault cohort passed: 36/36");
