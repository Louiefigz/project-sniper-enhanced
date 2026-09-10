import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseLegacyRegressionGateRegistryV1 } from
  "../contracts/p0-legacy-regression-gates";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../..");
const registryPath = path.join(
  root,
  "docs/producer/command-driven-editing/contracts/legacy-regression-gates-v1.json",
);
const value = JSON.parse(fs.readFileSync(registryPath, "utf8")) as unknown;
const registry = parseLegacyRegressionGateRegistryV1(value);

assert.equal(registry.completeness, "complete");
assert.deepEqual(registry.gates.map((gate) => gate.gateId), [
  "exact-delivery-geometry",
  "footage-readability",
  "measured-comp-capability",
  "channel-normalization-order",
  "frame-sample-duration-authority",
  "exact-rational-fps",
  "caption-end-to-end-authority",
  "cut-prompt-vocabulary",
  "graphics-over-broll-layering",
  "dual-cut-approval-binding",
  "refit-old-output-order",
  "observed-state-recovery",
  "headless-non-authorizing-boundary",
]);

function assertPathExists(relativePath: string, label: string): void {
  assert.equal(
    fs.existsSync(path.join(root, relativePath)),
    true,
    `${label} does not exist: ${relativePath}`,
  );
}

for (const gate of registry.gates) {
  for (const source of gate.sourceDocuments) {
    assertPathExists(source, `${gate.gateId} source`);
  }
  for (const code of gate.enforcingCode) {
    assertPathExists(code, `${gate.gateId} enforcing code`);
  }
  for (const fixture of gate.fixtures) {
    assertPathExists(fixture.path, `${gate.gateId} fixture`);
  }
  for (const evidence of gate.evidenceArtifacts) {
    assertPathExists(evidence, `${gate.gateId} evidence`);
  }
}

const blocked = registry.gates.filter((gate) => gate.implementationStatus === "blocked");
assert.deepEqual(blocked.map((gate) => gate.gateId), []);
assert.ok(blocked.every((gate) => gate.knownGap !== "none"));
assert.ok(registry.gates
  .filter((gate) => gate.implementationStatus === "enforced")
  .every((gate) => gate.receiptBindings.length > 0));

const missingOwner = structuredClone(value) as {
  gates: Array<Record<string, unknown>>;
};
missingOwner.gates[0].ownerPhases = [];
assert.throws(
  () => parseLegacyRegressionGateRegistryV1(missingOwner),
  /at least one owner/,
);

const falseEnforcement = structuredClone(value) as {
  gates: Array<Record<string, unknown>>;
};
falseEnforcement.gates[0].receiptBindings = [];
assert.throws(
  () => parseLegacyRegressionGateRegistryV1(falseEnforcement),
  /requires a receipt binding/,
);

const hiddenGap = structuredClone(value) as {
  gates: Array<Record<string, unknown>>;
};
hiddenGap.gates[8].implementationStatus = "blocked";
hiddenGap.gates[8].knownGap = "none";
assert.throws(
  () => parseLegacyRegressionGateRegistryV1(hiddenGap),
  /requires an exact known gap/,
);

console.log("p0 legacy regression gate registry tests passed");
