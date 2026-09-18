import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  findWordTranscript,
  stableReferenceId,
} from "../../../app/api/_lib/reference-library";
import {
  evictReferenceJsonUnder,
  readDeepStudyVideo,
  readReferenceJson,
  referenceJsonCacheStats,
} from "../../../app/api/_lib/reference-json";

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "reference-library-"));
try {
  const videoA = path.join(dir, "a.mp4");
  const videoB = path.join(dir, "b.mp4");
  fs.writeFileSync(videoA, "a");
  fs.writeFileSync(videoB, "b");
  fs.mkdirSync(path.join(dir, "b.study"));
  fs.writeFileSync(path.join(dir, "b.study", "transcript.json"), JSON.stringify({
    transcript: [{ words: [{ word: "wrong", start: 0, end: 1 }] }],
  }));
  assert.equal(findWordTranscript(videoA), null, "another reference transcript must not leak across");
  const vtt = path.join(dir, "a.en.vtt");
  fs.writeFileSync(vtt, "WEBVTT\n<c>hello</c>");
  assert.equal(findWordTranscript(videoA), vtt);
  const staleVideo = path.join(dir, "stale.mp4");
  const staleVtt = path.join(dir, "stale.en.vtt");
  fs.writeFileSync(staleVideo, "new video");
  fs.writeFileSync(staleVtt, "WEBVTT\n<c>old words</c>");
  fs.utimesSync(staleVtt, new Date(1), new Date(1));
  assert.equal(findWordTranscript(staleVideo), null, "stale captions must not bind to replaced media");
  assert.equal(stableReferenceId(videoA), stableReferenceId(videoA));
  assert.notEqual(stableReferenceId(videoA), stableReferenceId(videoB));

  const deep = path.join(dir, "deep_study.json");
  const recordedVideo = path.join(dir, 'quoted-"video.mp4');
  fs.writeFileSync(deep, JSON.stringify({ video: recordedVideo, signals: "x".repeat(2 * 1024 * 1024) }));
  const cacheBeforeDeep = referenceJsonCacheStats();
  assert.equal(readDeepStudyVideo(deep), recordedVideo);
  assert.equal(readReferenceJson<{ video: string }>(deep)?.video, recordedVideo);
  assert.deepEqual(referenceJsonCacheStats(), cacheBeforeDeep,
    "deep-study reads must not retain the multi-megabyte payload");

  const cacheDir = path.join(dir, "cache");
  fs.mkdirSync(cacheDir);
  for (let index = 0; index < 80; index += 1) {
    const file = path.join(cacheDir, `${index}.json`);
    fs.writeFileSync(file, JSON.stringify({ index, payload: "x".repeat(32 * 1024) }));
    assert.equal(readReferenceJson<{ index: number }>(file)?.index, index);
  }
  const bounded = referenceJsonCacheStats();
  assert.ok(bounded.entries <= 64, `cache retained ${bounded.entries} entries`);
  assert.ok(bounded.sourceBytes <= 1024 * 1024,
    `cache retained ${bounded.sourceBytes} source bytes`);
  evictReferenceJsonUnder(cacheDir);
  for (let index = 0; index < 80; index += 1) {
    assert.equal(readReferenceJson<{ index: number }>(path.join(cacheDir, `${index}.json`))?.index, index);
  }
  assert.ok(referenceJsonCacheStats().entries <= 64, "small-document cache must obey its entry cap");

  const deleted = path.join(cacheDir, "deleted.json");
  fs.writeFileSync(deleted, JSON.stringify({ ok: true }));
  assert.equal(readReferenceJson<{ ok: boolean }>(deleted)?.ok, true);
  fs.unlinkSync(deleted);
  assert.equal(readReferenceJson(deleted), null, "deleted documents must invalidate their cache entry");
  evictReferenceJsonUnder(cacheDir);
  assert.deepEqual(referenceJsonCacheStats(), cacheBeforeDeep,
    "hiding a reference must evict its cached control documents");
} finally {
  fs.rmSync(dir, { recursive: true, force: true });
}

console.log("reference-library.test.ts: all assertions passed");
