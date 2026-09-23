import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseCurrentSystemInventoryV1 } from "../contracts/p0-machine-contracts";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../..");
const contracts = path.join(root, "docs/producer/command-driven-editing/contracts");
const load = (name: string): unknown => JSON.parse(
  fs.readFileSync(path.join(contracts, name), "utf8"),
) as unknown;
const value = load("current-system-inventory-2026-09-22.json");
const current = parseCurrentSystemInventoryV1(value);
const historical = parseCurrentSystemInventoryV1(load("current-system-inventory-v1.json"));

assert.equal(current.asOf, "2026-09-22");
assert.equal(current.phaseExit, "blocked");
assert.equal(current.baseline.status, "required-unmeasured");
assert.deepEqual(current.baseline.evidencePaths, []);
assert.deepEqual(current.callSiteAudit, historical.callSiteAudit);
assert.equal(
  current.authorityDiscovery.pathBoundaryEvidence,
  "docs/producer/command-driven-editing/contracts/"
    + "p0-authority-path-boundary-evidence-2026-09-22.json",
);
assert.equal(
  current.authorityDiscovery.persistenceDispositionEvidence,
  "docs/producer/command-driven-editing/contracts/"
    + "p0-persistence-call-dispositions-2026-09-22.json",
);
assert.throws(
  () => parseCurrentSystemInventoryV1({ ...current, phaseExit: "passed" }),
  /cannot pass/,
);
assert.throws(
  () => parseCurrentSystemInventoryV1({
    ...current,
    completeness: "complete",
    inventoryGaps: ["unresolved source ownership"],
  }),
  /completeness and inventory gaps disagree/,
);
assert.throws(
  () => parseCurrentSystemInventoryV1({
    ...current,
    baseline: { ...current.baseline, status: "measured" },
  }),
  /must name every required fixture trace/,
);

console.log("current-system-inventory-revision tests passed");
