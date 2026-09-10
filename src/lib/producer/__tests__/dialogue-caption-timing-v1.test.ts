import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {
  parseDialogueCaptionTimingV1,
  validateDialogueCaptionTimingV1,
} from "../contracts/dialogue-caption-timing-v1";
import { parseDialogueMapV1 } from "../contracts/dialogue-map-v1";
import { canonicalJsonSha256 } from "../../server/auto-edit-hash";

const load = (name: string): Record<string, unknown> => JSON.parse(
  fs.readFileSync(path.join(
    process.cwd(), "scripts/producer/tests/fixtures", name,
  ), "utf8"),
) as Record<string, unknown>;

const authority = load("dialogue-authority-v1.json");
const golden = load("dialogue-caption-timing-v1.json");
const dialogueMap = parseDialogueMapV1(authority.map);
const verifiedMapHash = canonicalJsonSha256(dialogueMap);
const timing = validateDialogueCaptionTimingV1(
  golden.timing,
  dialogueMap,
  verifiedMapHash,
);

assert.equal(timing.dialogueMapHash, verifiedMapHash);
assert.deepEqual(
  timing.words[0]!.dialogueRoles,
  ["j-cut-handle", "primary"],
);
assert.deepEqual(
  timing.words[1]!.dialogueRoles,
  ["primary", "l-cut-handle"],
);
assert.equal(timing.words[0]!.startSample, 143_553);
assert.equal(timing.words[0]!.endSampleExclusive, 144_642);
assert.equal(timing.words[1]!.startFrame, 149);
assert.equal(timing.words[1]!.endFrameExclusive, 151);

const staleSample = structuredClone(golden.timing) as {
  words: Array<Record<string, unknown>>;
};
staleSample.words[0]!.startSample = 143_554;
assert.throws(
  () => validateDialogueCaptionTimingV1(
    staleSample,
    dialogueMap,
    verifiedMapHash,
  ),
  /stale mapped timing/,
);

const staleCover = structuredClone(golden.timing) as {
  words: Array<Record<string, unknown>>;
};
staleCover.words[0]!.coveringCutSegmentIds = ["cut-c", "cut-b"];
assert.throws(
  () => validateDialogueCaptionTimingV1(
    staleCover,
    dialogueMap,
    verifiedMapHash,
  ),
  /binding is stale/,
);

const duplicate = structuredClone(golden.timing) as {
  words: Array<Record<string, unknown>>;
};
duplicate.words[1]!.wordId = duplicate.words[0]!.wordId;
assert.throws(
  () => parseDialogueCaptionTimingV1(duplicate),
  /occurrence IDs must be unique/,
);

assert.throws(
  () => validateDialogueCaptionTimingV1(
    golden.timing,
    dialogueMap,
    "d".repeat(64),
  ),
  /does not bind/,
);

console.log("dialogue-caption-timing-v1 tests passed");
