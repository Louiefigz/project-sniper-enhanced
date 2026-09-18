import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { boundedDeepStudyContext } from "../../../app/api/producer/auto-edit/reference-review-context";

const root = mkdtempSync(path.join(os.tmpdir(), "sniper-reference-review-"));
try {
  const filePath = path.join(root, "deep_study.json");
  const events = Array.from({ length: 5_000 }, (_, index) => ({
    t: index / 24,
    type: index % 2 ? "graphic-in" : "cut",
    durationFrames: 4,
    transition: { class: "sweep", direction: "from-left", frames: 4 },
    easing: { bestFit: "power3-out", r2: 0.98, fits: { forbidden: "huge" } },
    detail: { forbidden: "raw-detail-sentinel" },
  }));
  writeFileSync(filePath, JSON.stringify({
    source: { durationS: 210, injected: "source-sentinel".repeat(100_000) },
    params: { fps: 24, injected: "params-sentinel".repeat(100_000) },
    events: [...events, ...Array.from({ length: 500 }, (_, index) => ({
      type: `unbounded-count-key-${index}-${"x".repeat(100)}`,
    }))],
    signals: ["raw-signal-sentinel".repeat(100_000)],
    text: {
      graphics: Array.from({ length: 900 }, () => ({ text: "raw-ocr-sentinel" })),
      states: [{ state: "talking-head" }],
      captions: { detected: true, cuesPerMin: 22, cues: [{ text: "cue-sentinel" }] },
    },
    wordLock: { events: Array.from({ length: 300 }, () => ({ word: "word-sentinel" })) },
    semantics: { ran: true, events: [{ label: "semantic-sentinel" }] },
  }));
  const bound = boundedDeepStudyContext(filePath);
  const summary = JSON.parse(bound.content);
  assert.match(bound.byteHash, /^[0-9a-f]{64}$/);
  assert.equal(summary.mechanics.eventCount, 5_500);
  assert.equal(summary.mechanics.sampledEvents.length, 64);
  assert.equal(summary.mechanics.eventTypes.cut, 2_500);
  assert.equal(summary.text.graphicObservationCount, 900);
  assert.equal(summary.wordLock.availableEventCount, 300);
  assert.ok(Buffer.byteLength(bound.content) < 64 * 1024);
  for (const forbidden of [
    "raw-signal-sentinel", "raw-detail-sentinel", "raw-ocr-sentinel",
    "cue-sentinel", "word-sentinel", "semantic-sentinel", "source-sentinel",
    "params-sentinel",
  ]) assert.equal(bound.content.includes(forbidden), false);
} finally {
  rmSync(root, { recursive: true, force: true });
}

console.log("reference-review-context.test.ts: all assertions passed");
