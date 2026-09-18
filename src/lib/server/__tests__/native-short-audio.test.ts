/** Explicit cleanup/gain decisions must keep their source rationale and output clock. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { assertNativeShortAudio, type NativeShortAudio } from "../native-short-audio";

function finishing(): NativeShortAudio {
  return { schemaVersion: 1, rationale: "Reduce steady fan noise in this recording.",
    audioEnhance: { preset: "voice" } };
}

function assertRejected(value: unknown, duration = 4): void {
  assert.throws(() => assertNativeShortAudio(value as NativeShortAudio, duration));
}

test("omitted processing remains absent; installed cleanup decisions preserve their inputs", () => {
  assert.doesNotThrow(() => assertNativeShortAudio(undefined, 4));
  for (const preset of ["voice", "voice-strong", "voice-rnn"] as const) {
    const value = { ...finishing(), audioEnhance: { preset } }, before = structuredClone(value);
    assert.doesNotThrow(() => assertNativeShortAudio(value, 4));
    assert.deepEqual(value, before);
  }
});

test("finishing requires a closed versioned decision and a meaningful bounded rationale", () => {
  for (const value of [null, [], false, {}, { ...finishing(), schemaVersion: 2 },
    { ...finishing(), rationale: "  " }, { ...finishing(), rationale: "ab" },
    { ...finishing(), rationale: "x".repeat(2401) }, { ...finishing(), rationale: "room\0tone" },
    { ...finishing(), unauthorizedProcessor: "remote" },
    { schemaVersion: 1, rationale: "A recording needs review." }]) assertRejected(value);
});

test("unavailable presets and undeclared enhancement knobs cannot silently fall back", () => {
  for (const audioEnhance of [null, [], {}, { preset: "separate" }, { preset: "dereverb" },
    { preset: "VOICE" }, { preset: "voice", strength: 100 }, { preset: 1 }]) {
    assertRejected({ ...finishing(), audioEnhance });
  }
});

test("an active decision needs a finite positive output duration", () => {
  for (const duration of [0, -1, NaN, Infinity, -Infinity]) assertRejected(finishing(), duration);
});

test("touching gain windows and both maximum gains are valid without rewriting order", () => {
  const value: NativeShortAudio = { schemaVersion: 1, rationale: "Match two microphone levels.",
    audioGain: [{ outStart: 0, outEnd: 2, dB: -12 }, { outStart: 2, outEnd: 4, dB: 12 }] };
  const before = structuredClone(value);
  assert.doesNotThrow(() => assertNativeShortAudio(value, 4));
  assert.deepEqual(value, before);
});

test("gain windows reject overlap, reverse order and windows beyond the exact output", () => {
  const window = { outStart: 0, outEnd: 2, dB: 3 };
  const invalid = [
    [{ ...window, outStart: -0.001 }], [{ ...window, outEnd: 0 }],
    [{ ...window, outEnd: 4.000001 }], [window, { ...window, outStart: 1, outEnd: 3 }],
    [{ ...window, outStart: 2, outEnd: 3 }, window],
  ];
  for (const audioGain of invalid) assertRejected({ ...finishing(), audioGain });
});

test("gain bounds and JSON number types fail closed including nested unknown fields", () => {
  const window = { outStart: 0, outEnd: 2, dB: 3 };
  for (const bad of [{ ...window, dB: -12.001 }, { ...window, dB: 12.001 },
    { ...window, dB: NaN }, { ...window, dB: Infinity }, { ...window, dB: true },
    { ...window, outEnd: "2" }, { ...window, outStart: NaN },
    { ...window, rationale: "not part of the gain contract" }, null]) {
    assertRejected({ ...finishing(), audioGain: [bad] });
  }
});

test("gain lists are explicitly bounded to 128 nonempty windows", () => {
  for (const audioGain of [null, {}, [], Array.from({ length: 129 }, (_, index) =>
    ({ outStart: index, outEnd: index + 1, dB: 0 }))]) {
    assertRejected({ ...finishing(), audioGain }, 129);
  }
  const audioGain = Array.from({ length: 128 }, (_, index) =>
    ({ outStart: index, outEnd: index + 1, dB: 0 }));
  assert.doesNotThrow(() => assertNativeShortAudio({ ...finishing(), audioGain }, 128));
});
