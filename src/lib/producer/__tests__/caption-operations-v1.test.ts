import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import {
  correctCaptionWords,
  reconcileCaptionAuthority,
  setCaptionRange,
} from "@/app/api/producer/ai-edit/caption-operations-v1";
import { captionCorrectionLedgerHash } from
  "@/app/api/producer/ai-edit/caption-ledger-hash-v1";
import type {
  CaptionCorrectionLedgerV1,
  EditPlan,
} from "@/lib/producer/edit-plan";

const words = [
  "w-1111111111111111",
  "w-2222222222222222",
  "w-3333333333333333",
];

function pythonResult(script: string, input: unknown): string {
  const result = spawnSync(
    path.join(process.cwd(), ".venv", "bin", "python3"),
    ["-c", script],
    {
      encoding: "utf8",
      input: JSON.stringify(input),
      env: {
        ...process.env,
        PYTHONPATH: path.join(process.cwd(), "scripts", "producer"),
      },
    },
  );
  assert.equal(result.status, 0, result.stderr);
  return result.stdout.trim();
}

function pythonLedgerHash(ledger: CaptionCorrectionLedgerV1): string {
  const script = [
    "import json, sys",
    "from captions.caption_fingerprints import correction_ledger_hash",
    "print(correction_ledger_hash(json.load(sys.stdin)))",
  ].join("; ");
  return pythonResult(script, ledger);
}

function pythonAcceptsReason(reason: string): boolean {
  const script = `
import json, sys
from captions.caption_contract import validate_correction_ledger
reason = json.load(sys.stdin)
ledger = {"schemaVersion": 1, "kind": "caption-correction-ledger",
          "corrections": [{"correctionId": "cc-1111111111111111",
            "sourceWordIds": ["w-1111111111111111"],
            "displayTokens": ["word"],
            "timingPolicy": "proportional-codepoints", "reason": reason}]}
try:
    validate_correction_ledger(ledger)
except ValueError:
    print("reject")
else:
    print("accept")
`;
  return pythonResult(script, reason) === "accept";
}

const initial: EditPlan = {
  captions: { burn: true },
  captionsTrack: {
    schemaVersion: 1,
    source: "kept-transcript",
    defaultPolicy: "line",
    groups: [],
  },
};
assert.equal(
  captionCorrectionLedgerHash({
    schemaVersion: 1, kind: "caption-correction-ledger", corrections: [],
  }),
  "199e7df4efe8532ed9a45b5fe955712a38020fd1a13292b0fa8e6db40dbcade1",
);
assert.equal(
  captionCorrectionLedgerHash({
    schemaVersion: 1,
    kind: "caption-correction-ledger",
    corrections: [{
      correctionId: "cc-1111111111111111",
      sourceWordIds: [words[2]],
      displayTokens: ["Sniper 🚀"],
      timingPolicy: "proportional-codepoints",
      reason: "proper name",
    }],
  }),
  "f0007c2efbcf35f90f7550575c302ffee3e87a5e090acca4ffa847c2c7995f92",
);
const delLedger: CaptionCorrectionLedgerV1 = {
  schemaVersion: 1,
  kind: "caption-correction-ledger",
  corrections: [{
    correctionId: "cc-1111111111111111",
    sourceWordIds: [words[2]],
    displayTokens: ["A\u007fB"],
    timingPolicy: "proportional-codepoints",
    reason: "valid DEL \u007f marker",
  }],
};
assert.equal(
  captionCorrectionLedgerHash(delLedger),
  pythonLedgerHash(delLedger),
);

const karaoke = setCaptionRange(initial, {
  kind: "set-caption-range",
  wordIds: words.slice(1),
  styleId: "karaoke",
  mode: "karaoke-word",
  placement: "bottom-center",
});
assert.equal(karaoke.captionsTrack?.groups.length, 1);
assert.match(karaoke.captionsTrack!.groups[0].groupId, /^cg-[0-9a-f]{16}$/u);

const repeated = setCaptionRange(karaoke, {
  kind: "set-caption-range",
  wordIds: words.slice(1),
  styleId: "karaoke",
  mode: "karaoke-word",
  placement: "top-center",
});
assert.equal(repeated.captionsTrack?.groups.length, 1);
assert.equal(
  repeated.captionsTrack?.groups[0].groupId,
  karaoke.captionsTrack?.groups[0].groupId,
);

const corrected = correctCaptionWords(repeated, {
  kind: "correct-caption-words",
  sourceWordIds: [words[2]],
  displayTokens: ["Sniper"],
  reason: "proper name",
});
assert.equal(corrected.captionCorrectionLedger?.corrections.length, 1);
assert.match(
  corrected.captionCorrectionLedger!.corrections[0].correctionId,
  /^cc-[0-9a-f]{16}$/u,
);

const boundaryReason = "😀".repeat(500);
const astralCorrection = correctCaptionWords(repeated, {
  kind: "correct-caption-words",
  sourceWordIds: [words[2]],
  displayTokens: ["Sniper"],
  reason: boundaryReason,
});
assert.equal(
  astralCorrection.captionCorrectionLedger?.corrections[0].reason,
  boundaryReason,
);
assert.equal(pythonAcceptsReason(boundaryReason), true);
for (const reason of ["😀".repeat(501), "\u0085", "\ufeff"]) {
  assert.throws(() => correctCaptionWords(repeated, {
    kind: "correct-caption-words",
    sourceWordIds: [words[2]],
    displayTokens: ["Sniper"],
    reason,
  }), /reason is invalid/u);
  assert.equal(pythonAcceptsReason(reason), false);
}
for (const token of ["\u0085", "\ufeff"]) {
  assert.throws(() => correctCaptionWords(repeated, {
    kind: "correct-caption-words",
    sourceWordIds: [words[2]],
    displayTokens: [token],
  }), /displayTokens contain invalid text/u);
}

const bound = structuredClone(initial);
bound.captionsTrack!.transcriptCorrectionHash =
  "199e7df4efe8532ed9a45b5fe955712a38020fd1a13292b0fa8e6db40dbcade1";
const correctedBound = correctCaptionWords(bound, {
  kind: "correct-caption-words",
  sourceWordIds: [words[2]],
  displayTokens: ["Sniper"],
});
assert.equal(
  correctedBound.captionsTrack?.transcriptCorrectionHash,
  captionCorrectionLedgerHash(correctedBound.captionCorrectionLedger!),
);

const tampered = structuredClone(corrected);
tampered.captionsTrack!.groups[0].groupId = "cg-0000000000000000";
tampered.captionCorrectionLedger!.corrections[0].correctionId =
  "cc-0000000000000000";
const reconciled = reconcileCaptionAuthority(tampered);
assert.equal(reconciled.stampedGroups, 1);
assert.equal(reconciled.stampedCorrections, 1);
assert.deepEqual(reconciled.plan, corrected);

const overlap = structuredClone(corrected);
overlap.captionsTrack!.groups.push({
  ...overlap.captionsTrack!.groups[0],
  groupId: "cg-aaaaaaaaaaaaaaaa",
});
assert.throws(
  () => reconcileCaptionAuthority(overlap),
  /overlap on stable word ids/u,
);

assert.throws(
  () => reconcileCaptionAuthority({
    captionCorrectionLedger: corrected.captionCorrectionLedger,
  }),
  /require captionsTrack/u,
);

console.log("caption-operations-v1 tests passed");
