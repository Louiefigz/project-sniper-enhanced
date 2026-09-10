import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { reconcileCaptionPlanAuthority } from
  "@/app/api/producer/ai-edit/caption-plan-authority-v1";
import type { EditPlan } from "@/lib/producer/edit-plan";

function pythonChapterTitle(title: string): string | null {
  const script = `
import json, sys
from captions.caption_outputs import validate_chapter_anchors
title = json.load(sys.stdin)
try:
    value = validate_chapter_anchors([{
        "chapterId": "chapter-intro", "title": title,
        "wordId": "w-1111111111111111"}])
except ValueError:
    print("null")
else:
    print(json.dumps(value[0]["title"], ensure_ascii=False))
`;
  const result = spawnSync(
    path.join(process.cwd(), ".venv", "bin", "python3"),
    ["-c", script],
    {
      encoding: "utf8", input: JSON.stringify(title),
      env: {
        ...process.env,
        PYTHONPATH: path.join(process.cwd(), "scripts", "producer"),
      },
    },
  );
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout.trim()) as string | null;
}

const plan: EditPlan = {
  target: { mode: "longform" },
  captionsTrack: {
    schemaVersion: 1,
    source: "kept-transcript",
    defaultPolicy: "line",
    groups: [],
  },
  captionChapters: [{
    chapterId: "chapter-intro",
    title: "  Intro  ",
    wordId: "w-1111111111111111",
  }],
};

const reconciled = reconcileCaptionPlanAuthority(plan).plan;
assert.equal(reconciled.captionChapters?.[0].title, "Intro");

const planWithTitle = (title: string): EditPlan => ({
  ...plan,
  captionChapters: [{
    ...plan.captionChapters![0],
    title,
  }],
});
const boundaryTitle = "😀".repeat(500);
assert.equal(
  reconcileCaptionPlanAuthority(planWithTitle(boundaryTitle))
    .plan.captionChapters?.[0].title,
  boundaryTitle,
);
assert.equal(pythonChapterTitle(boundaryTitle), boundaryTitle);
for (const title of ["😀".repeat(501), "\u0085", "\ufeff"]) {
  assert.throws(
    () => reconcileCaptionPlanAuthority(planWithTitle(title)),
    /title is invalid/u,
  );
  assert.equal(pythonChapterTitle(title), null);
}
const padded = "\u0085\ufeffIntro\ufeff\u0085";
assert.equal(
  reconcileCaptionPlanAuthority(planWithTitle(padded))
    .plan.captionChapters?.[0].title,
  "Intro",
);
assert.equal(pythonChapterTitle(padded), "Intro");

assert.throws(
  () => reconcileCaptionPlanAuthority({
    ...plan,
    target: { mode: "short" },
  }),
  /longform-only/u,
);

assert.throws(
  () => reconcileCaptionPlanAuthority({
    ...plan,
    chapters: [{ outStart: 0, title: "legacy" }],
  }),
  /not legacy chapters/u,
);

assert.throws(
  () => reconcileCaptionPlanAuthority({
    target: { mode: "longform" },
    captionChapters: plan.captionChapters,
  }),
  /require captionsTrack/u,
);

console.log("caption-chapters-v1 tests passed");
