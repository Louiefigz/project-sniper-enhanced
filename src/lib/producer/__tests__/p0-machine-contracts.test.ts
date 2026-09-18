import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  parseCurrentSystemInventoryV1,
  parseFpsSupportMatrixV1,
  parseProductCapabilityMatrixV1,
} from "../contracts/p0-machine-contracts";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../..");
const contractDir = path.join(
  root,
  "docs",
  "producer",
  "command-driven-editing",
  "contracts",
);

function load(name: string): unknown {
  return JSON.parse(fs.readFileSync(path.join(contractDir, name), "utf8")) as unknown;
}

const inventoryValue = load("current-system-inventory-v1.json");
const inventory = parseCurrentSystemInventoryV1(inventoryValue);
assert.equal(inventory.completeness, "complete");
assert.equal(inventory.phaseExit, "passed");
assert.equal(inventory.inventoryGaps.length, 0);
assert.equal(inventory.baseline.status, "measured");
assert.deepEqual(inventory.baseline.evidencePaths, [
  "docs/producer/command-driven-editing/contracts/p0-current-short-baseline-v1.json",
  "docs/producer/command-driven-editing/contracts/p0-current-lf14-baseline-v1.json",
]);
assert.deepEqual(inventory.callSiteAudit.roots, [
  "scripts/producer",
  "src/app/api",
  "src/lib/producer",
  "src/lib/server",
]);
assert.ok(inventory.artifacts.some((row) => row.artifactId === "revision-store-v1"));
for (const artifactId of [
  "compatibility-picture-lock",
  "minimum-render-graph-shadow",
  "palmier-commit-saga-shadow",
  "external-media-snapshot-shadow",
  "caption-track-alpha-shards-v1",
  "scene-package-cli-v1",
  "current-render-graph-v1",
  "template-usage-approval",
  "project-mutation-lease",
  "promotion-reconciliation",
  "assembled-media-authority",
  "auto-edit-qc-rounds",
  "caption-render-authority-v1",
  "palmier-timeline-authority",
  "palmier-desktop-authority",
  "palmier-live-build-state",
  "palmier-sync-transaction",
  "scene-authoring-stage-receipt",
  "reference-admission-transaction",
  "auto-edit-job-journal",
  "auto-edit-launch-lease",
  "auto-edit-diagnostic-log",
  "cut-repair-staging-cache",
  "producer-learning-root",
  "producer-learning-run-snapshots",
  "producer-learning-template-usage",
  "producer-learning-observations",
  "producer-learning-geometry-ledger",
  "producer-learning-qc-history",
  "auto-edit-quality-policy",
  "reference-media-admission",
  "producer-run-state",
  "legacy-governed-production-state-family",
  "legacy-editor-delivery-output-family",
  "bounded-command-execution-adapters",
  "palmier-current-preflight-boundary",
  "native-desktop-interaction-adapters",
  "frameio-review-report",
  "cut-repair-qc-tool-manifest",
  "scene-unit-private-review",
  "palmier-editable-parity",
]) {
  assert.ok(inventory.artifacts.some((row) => row.artifactId === artifactId));
}
assert.equal(
  inventory.artifacts.find(
    (row) => row.artifactId === "compatibility-projection",
  )?.pathPattern,
  "<project>/producer/compatibility_projections/<hash>.json",
);
assert.equal(
  inventory.artifacts.find(
    (row) => row.artifactId === "edit-plan",
  )?.callSiteDispositions["src/app/api/producer/save-plan/route.ts"],
  "writer",
);
assert.equal(
  inventory.authorityDiscovery.artifactBindings[".render-graph-v1"],
  "current-render-graph-v1",
);
assert.deepEqual(inventory.authorityDiscovery.backlog, {});
assert.equal(
  inventory.authorityDiscovery.pathBoundaryEvidence,
  "docs/producer/command-driven-editing/contracts/"
    + "p0-authority-path-boundary-evidence-v1.json",
);
assert.equal(
  inventory.authorityDiscovery.persistenceDispositionEvidence,
  "docs/producer/command-driven-editing/contracts/"
    + "p0-persistence-call-dispositions-v1.json",
);

const capabilityValue = load("product-capability-matrix-v1.json");
const capabilities = parseProductCapabilityMatrixV1(capabilityValue);
assert.equal(capabilities.phaseExit, "blocked");
assert.equal(
  capabilities.capabilities.find(
    (row) => row.capabilityId === "project-scoped-custom-motion",
  )?.status,
  "released",
);
assert.equal(
  capabilities.capabilities.find(
    (row) => row.capabilityId === "non-ripple-word-repair",
  )?.status,
  "unqualified",
);
const wordRepair = capabilities.capabilities.find(
  (row) => row.capabilityId === "non-ripple-word-repair",
);
assert.ok(
  wordRepair?.blockingGates.some((gate) => gate.includes("creator-speech qualification")),
);
assert.ok(
  wordRepair?.blockingGates.some((gate) => gate.includes("general layered picture repair")),
);
assert.ok(
  wordRepair?.blockingGates.every(
    (gate) => !gate.includes("actual controller producer")
      && !gate.includes("configure and retain a genuinely independent forced-aligner")
      && !gate.includes("full ingest-to-repair normalized-VFR"),
  ),
  "the capability matrix must not relist bounded P2 exits as unfinished product gates",
);
assert.equal(
  capabilities.capabilities.find(
    (row) => row.capabilityId === "range-karaoke-captions",
  )?.status,
  "released",
);
assert.equal(
  capabilities.capabilities.find(
    (row) => row.capabilityId === "scene-unit-private-review",
  )?.status,
  "compatibility",
);
assert.equal(
  capabilities.capabilities.find(
    (row) => row.capabilityId === "reference-inspired-editing",
  )?.status,
  "released",
);
assert.equal(
  capabilities.capabilities.find(
    (row) => row.capabilityId === "verified-reference-mimic",
  )?.status,
  "unqualified",
);
for (const capabilityId of [
  "ask-editor-project-custom-motion",
  "continuous-subject-reframe",
  "animated-pip",
]) {
  assert.equal(
    capabilities.capabilities.find(
      (row) => row.capabilityId === capabilityId,
    )?.status,
    "unsupported",
  );
}
assert.equal(
  capabilities.capabilities.find(
    (row) => row.capabilityId === "set-graphic-text-v1",
  )?.status,
  "compatibility",
);
for (const capabilityId of [
  "first-class-revision-authority",
  "minimum-render-graph-v1",
  "external-media-sandbox-admission",
]) {
  assert.equal(
    capabilities.capabilities.find(
      (row) => row.capabilityId === capabilityId,
    )?.status,
    "compatibility",
  );
}

const fpsValue = load("fps-support-matrix-v1.json");
const fps = parseFpsSupportMatrixV1(fpsValue);
assert.deepEqual(
  fps.rows.filter((row) => row.status === "measured-released")
    .map((row) => `${row.surface}:${row.numerator}/${row.denominator}`),
  [
    "graphics-comp-catalog:24000/1001",
    "graphics-comp-catalog:24/1",
    "graphics-comp-catalog:25/1",
    "graphics-comp-catalog:30000/1001",
    "graphics-comp-catalog:30/1",
    "graphics-comp-catalog:50/1",
    "graphics-comp-catalog:60000/1001",
    "graphics-comp-catalog:60/1",
  ],
);
assert.equal(fps.phaseExit, "blocked");

assert.throws(
  () => parseCurrentSystemInventoryV1({
    ...(inventoryValue as Record<string, unknown>),
    completeness: "partial",
    inventoryGaps: ["retained test gap"],
    phaseExit: "passed",
  }),
  /cannot pass/,
);

const inventoryMutation = structuredClone(
  inventoryValue,
) as { artifacts: Array<Record<string, unknown>> };
inventoryMutation.artifacts[0].callSiteDispositions = {
  "src/app/api/_lib/workspace.ts": "unreviewed",
};
assert.throws(
  () => parseCurrentSystemInventoryV1(inventoryMutation),
  /must be one of/,
);

const incompleteBaseline = structuredClone(
  inventoryValue,
) as { baseline: { evidencePaths: string[] } };
incompleteBaseline.baseline.evidencePaths.pop();
assert.throws(
  () => parseCurrentSystemInventoryV1(incompleteBaseline),
  /must name every required fixture trace/,
);

const bypassedDiscovery = structuredClone(
  inventoryValue,
) as {
  authorityDiscovery: {
    artifactBindings: Record<string, string>;
    backlog: Record<string, string>;
  };
};
bypassedDiscovery.authorityDiscovery.artifactBindings[
  ".sniper-auto-edit-job.json"
] = "edit-plan";
assert.throws(
  () => parseCurrentSystemInventoryV1(bypassedDiscovery),
  /bypasses artifact tokens/,
);

const capabilityMutation = structuredClone(
  capabilityValue,
) as { capabilities: Array<Record<string, unknown>> };
capabilityMutation.capabilities[1].status = "released";
capabilityMutation.capabilities[1].codeEvidence = [];
assert.throws(
  () => parseProductCapabilityMatrixV1(capabilityMutation),
  /lacks released evidence/,
);

const fpsMutation = structuredClone(
  fpsValue,
) as { rows: Array<Record<string, unknown>> };
fpsMutation.rows[0].numerator = "60";
fpsMutation.rows[0].denominator = "2";
assert.throws(
  () => parseFpsSupportMatrixV1(fpsMutation),
  /positive and reduced/,
);

console.log("p0-machine-contracts tests passed");
