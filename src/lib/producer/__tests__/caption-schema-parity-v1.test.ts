import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { reconcileCaptionAuthority } from
  "@/app/api/producer/ai-edit/caption-operations-v1";
import type { EditPlan } from "@/lib/producer/edit-plan";

const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)), "../../../..",
);
const wordId = "w-1111111111111111";
const track = (sceneId: string): NonNullable<EditPlan["captionsTrack"]> => ({
  schemaVersion: 1,
  source: "kept-transcript",
  defaultPolicy: "off",
  groups: [{
    groupId: "cg-1111111111111111",
    anchor: { kind: "word-range", wordIds: [wordId] },
    styleId: "karaoke",
    mode: "karaoke-word",
    placement: "bottom-center",
    suppressUnderSceneIds: [sceneId],
  }],
});
const ledger = (token: string): NonNullable<
EditPlan["captionCorrectionLedger"]> => ({
  schemaVersion: 1,
  kind: "caption-correction-ledger",
  corrections: [{
    correctionId: "cc-1111111111111111",
    sourceWordIds: [wordId],
    displayTokens: [token],
    timingPolicy: "proportional-codepoints",
  }],
});
const validTrack = track("s".repeat(128));
const invalidTrack = track("s".repeat(129));
const validLedger = ledger("x".repeat(256));
const invalidLedgers = [ledger("x".repeat(257)), ledger("   ")];

assert.doesNotThrow(() => reconcileCaptionAuthority({
  captionsTrack: validTrack,
  captionCorrectionLedger: validLedger,
}));
assert.throws(() => reconcileCaptionAuthority({
  captionsTrack: invalidTrack,
  captionCorrectionLedger: validLedger,
}), /non-empty string array/u);
for (const invalid of invalidLedgers) {
  assert.throws(() => reconcileCaptionAuthority({
    captionsTrack: validTrack,
    captionCorrectionLedger: invalid,
  }), /displayTokens/u);
}

const cases = [
  { schema: "caption-track-v1.schema.json", document: validTrack },
  { schema: "caption-track-v1.schema.json", document: invalidTrack },
  { schema: "caption-correction-ledger-v1.schema.json", document: validLedger },
  ...invalidLedgers.map((document) => ({
    schema: "caption-correction-ledger-v1.schema.json", document,
  })),
];
const python = spawnSync(
  path.join(root, ".venv", "bin", "python3"),
  [path.join(root, "scripts/producer/contracts/schema_validator.py"), "--batch"],
  { cwd: root, input: JSON.stringify(cases), encoding: "utf8" },
);
assert.equal(python.status, 0, python.stderr);
const results = JSON.parse(python.stdout) as Array<{ valid: boolean }>;
assert.deepEqual(results.map((row) => row.valid), [
  true, false, true, false, false,
]);

console.log("caption-schema-parity-v1 tests passed");
