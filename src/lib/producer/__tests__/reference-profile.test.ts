import assert from "node:assert/strict";
import { buildReferenceStyleProfile } from "../../../app/api/_lib/reference-profile";

const profile = buildReferenceStyleProfile({
  id: "ref_test",
  title: "Punch sample",
  video: "/tmp/iampunch/sample.mp4",
  sha256: "a".repeat(64),
  deep: {
    source: { width: 1080, height: 1920, fps: 30, durationS: 60 },
    events: [
      { type: "cut", transition: { class: "hard-cut" } },
      { type: "cut", transition: { class: "hard-cut" } },
      { type: "graphic-in", transition: { class: "pop" } },
    ],
    text: {
      graphics: [{ textColor: "#ffffff", bgColor: "#111111" }],
      captions: { detected: true, positionBand: "bottom", cuesPerMin: 72,
        wordsPerCueMean: 2.5, karaoke: false },
    },
    wordLock: { events: [{ eventId: "ev-1" }], within150msPct: 90 },
    semantics: { ran: false },
    unclassifiedRuns: 1,
  },
  fingerprint: {
    pacing: { cuts_per_min: 2, shot_p50: 3.5, longest_static_s: 8 },
    audio: { integrated_lufs: -14.2, music: { label: "likely", confidence: "medium" } },
    states: [{ rep_path: "/tmp/frame.jpg" }],
  },
});

assert.equal(profile.schemaVersion, 1);
assert.equal(profile.suggestedMode, "short");
assert.equal(profile.suggestedKnownStyle, "punch");
assert.equal(profile.source.sha256, "a".repeat(64));
assert.equal(profile.mechanics.eventCounts.cut, 2);
assert.equal(profile.mechanics.eventRatesPerMin.cut, 2);
assert.deepEqual(profile.mechanics.transitionClasses, { "hard-cut": 2, pop: 1 });
assert.deepEqual(profile.mechanics.colors, { text: ["#ffffff"], background: ["#111111"] });
assert.equal(profile.quality.wordLockAvailable, true);
assert.equal(profile.quality.unclassifiedRuns, 1);
assert.deepEqual(profile.representativeFrames, ["/tmp/frame.jpg"]);

console.log("reference-profile.test.ts: all assertions passed");
