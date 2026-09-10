import assert from "node:assert/strict";
import {
  mkdirSync, mkdtempSync, rmSync, writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  buildCaptionWordIndex,
  resolveCaptionRequestAnchors,
} from "@/app/api/producer/ai-edit/caption-word-index-v1";
import { preparePlanForAi } from
  "@/app/api/producer/ai-edit/execution";
import type { EditPlan } from "@/lib/producer/edit-plan";

const root = mkdtempSync(path.join(os.tmpdir(), "caption-word-index-"));
const producer = path.join(root, "producer");
const source = path.join(root, "source");
mkdirSync(producer);
mkdirSync(source);

try {
  const transcriptPath = path.join(source, "raw.transcript.json");
  const manifestPath = path.join(source, "asset_manifest.json");
  const planPath = path.join(producer, "edit_plan.json");
  const words = [
    ["Project", 0, 0.3],
    ["Sniper", 0.31, 0.7],
    ["works", 0.71, 1],
    ["Project", 3, 3.3],
    ["Sniper", 3.31, 3.7],
    ["again", 3.71, 4],
  ].map(([word, start, end]) => ({ word, start, end }));
  writeFileSync(transcriptPath, JSON.stringify({
    transcript: [{
      start: 0, end: 4, text: "Project Sniper works Project Sniper again",
      words,
    }],
  }));
  writeFileSync(manifestPath, JSON.stringify({
    sources: [{ id: "raw", transcriptPath: "raw.transcript.json" }],
  }));
  const plan: EditPlan = {
    target: { mode: "short" },
    cutTrack: [{ sourceId: "raw", start: 0.005, end: 5 }],
  };
  writeFileSync(planPath, `${JSON.stringify(plan, null, 1)}\n`);
  const index = buildCaptionWordIndex({
    plan, manifestPath, transcriptsDir: source,
  });
  assert.equal(index.words.length, 6);
  assert.deepEqual(
    index.words.slice(0, 4).map((word) => word.wordId),
    [
      "w-f6b7a7ad45b08289",
      "w-62f9c9c52a3edcff",
      "w-7430f2857386ecc1",
      "w-798a632ebecd6596",
    ],
    "TypeScript stable IDs must equal the Python CaptionTrackV1 contract",
  );
  assert.equal(index.words[0].outputStart, 0);

  const reused = buildCaptionWordIndex({
    plan: {
      target: { mode: "short" },
      cutTrack: [
        { id: "first-use", sourceId: "raw", start: 0, end: 1 },
        { id: "second-use", sourceId: "raw", start: 0, end: 1 },
      ],
    },
    manifestPath,
    transcriptsDir: source,
  });
  assert.equal(reused.words.length, 6);
  assert.deepEqual(
    reused.words.filter((word) =>
      word.sourceWordId === "w-f6b7a7ad45b08289").map((word) => ({
      wordId: word.wordId,
      occurrence: word.occurrence,
      cutSegmentIndex: word.cutSegmentIndex,
      outputStart: word.outputStart,
    })),
    [
      {
        wordId: "w-03edcd5234f6a826", occurrence: 1,
        cutSegmentIndex: 0, outputStart: 0,
      },
      {
        wordId: "w-8a21a9391090d9d8", occurrence: 2,
        cutSegmentIndex: 1, outputStart: 1,
      },
    ],
    "reused source words must use Python-parity occurrence IDs",
  );
  const reusedAnchor = resolveCaptionRequestAnchors(
    'at 1.2 seconds make "Project Sniper works" karaoke', reused,
  );
  assert.equal(reusedAnchor[0].status, "resolved");
  assert.deepEqual(
    reusedAnchor[0].wordIds,
    reused.words.slice(3).map((word) => word.wordId),
  );

  const ambiguous = resolveCaptionRequestAnchors(
    'make "Project Sniper" karaoke', index,
  );
  assert.equal(ambiguous[0].status, "ambiguous");
  const resolved = resolveCaptionRequestAnchors(
    'at 3 seconds make "Project Sniper" karaoke', index,
  );
  assert.equal(resolved[0].status, "resolved");
  assert.deepEqual(
    resolved[0].wordIds,
    index.words.slice(3, 5).map((word) => word.wordId),
  );
  const correction = resolveCaptionRequestAnchors(
    'at 3 seconds change "Project Sniper" to "Project Sniper Pro" in the captions',
    index,
  );
  assert.equal(correction.length, 1);
  assert.equal(correction[0].phrase, "Project Sniper");
  assert.equal(correction[0].status, "resolved");
  assert.deepEqual(
    correction[0].wordIds,
    index.words.slice(3, 5).map((word) => word.wordId),
  );
  const timestampMismatch = resolveCaptionRequestAnchors(
    'at 30 seconds make "works" karaoke', index,
  );
  assert.equal(timestampMismatch[0].status, "timestamp-mismatch");
  assert.deepEqual(timestampMismatch[0].wordIds, []);
  assert.deepEqual(timestampMismatch[0].candidates, []);

  assert.throws(
    () => preparePlanForAi(planPath, plan, {
      request: 'make "Project Sniper" karaoke',
      manifestPath,
      transcriptsDir: source,
    }),
    /ambiguous/u,
  );
  const staged = preparePlanForAi(planPath, plan, {
    request: 'at 3 seconds make "Project Sniper" karaoke',
    manifestPath,
    transcriptsDir: source,
  });
  assert.equal(path.basename(staged.captionWordIndexPath!), "caption-word-index.json");
  assert.equal(path.dirname(staged.captionWordIndexPath!), staged.stagingDir);
  rmSync(staged.stagingDir, { recursive: true, force: true });
  assert.throws(
    () => preparePlanForAi(planPath, plan, {
      request: 'at 30 seconds make "works" karaoke',
      manifestPath,
      transcriptsDir: source,
    }),
    /within 2 seconds/u,
  );
} finally {
  rmSync(root, { recursive: true, force: true });
}

console.log("caption-word-index-v1 tests passed");
