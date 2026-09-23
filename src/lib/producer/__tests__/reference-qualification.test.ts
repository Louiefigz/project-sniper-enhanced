import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  referenceExecutionClass,
  VERIFIED_MIMIC_BLOCKERS,
  VERIFIED_MIMIC_RELEASED,
} from "../reference-qualification";

assert.equal(referenceExecutionClass("mimic"), "reference-inspired");
assert.throws(() => referenceExecutionClass("extend"), /retired/);
assert.equal(referenceExecutionClass("new-style"), "provisional-style-candidate");
assert.equal(VERIFIED_MIMIC_RELEASED, false);
assert.deepEqual(VERIFIED_MIMIC_BLOCKERS, [
  "three materially different approved packs with explicit waiver coverage",
  "retained reviewer-disagreement adjudication evidence",
  "proved-scene closure for every realized mechanic",
  "itemized unsupported-mechanic disclosure before execution",
  "rights evidence for every reference-derived identity asset",
  "unseen-footage frozen-tolerance and three-reviewer no-regression evidence",
  "separate onboarding and approved-pack editing-time receipts",
]);

const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../..",
);
const codexAdapter = fs.readFileSync(
  path.join(root, ".agents/skills/reference-editor/SKILL.md"),
  "utf8",
);
assert.match(codexAdapter, /reference-inspired/i);
assert.match(codexAdapter, /P6 remains 0\/7/i);
assert.doesNotMatch(
  codexAdapter,
  /compile a verified style pack|through Producer and editable Palmier/i,
);

console.log("reference-qualification tests passed");
