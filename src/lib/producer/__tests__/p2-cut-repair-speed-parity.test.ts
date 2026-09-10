import assert from "node:assert/strict";
import { parseCutRepairRetimeV1 } from
  "@/lib/producer/contracts/cut-repair-retime";
import { parseCutRestoreSpeechV1 } from
  "@/lib/producer/contracts/cut-restore-speech-v1";
import { parsePalmierCutRepairDispositionV1 } from
  "@/lib/producer/contracts/palmier-cut-repair-disposition";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import {
  cutRestoreAction,
} from "./_cut-restore-speech-fixture";

const hash = (value: string): string => value.repeat(64);

function actionAndRetime() {
  const action = parseCutRestoreSpeechV1({
    ...cutRestoreAction(hash("1"), hash("2")),
    speed: { numerator: "5", denominator: "4" },
    sourceExtension: {
      startSample: 48_000, endSampleExclusive: 52_800,
    },
    extensionOutputSamples: 3_840,
  });
  const retime = parseCutRepairRetimeV1({
    requestedSpeed: action.speed,
    sourceSampleRange: action.sourceExtension,
    sourceSampleRate: action.sourceSampleRate,
    normalizedSourceSampleRange: action.sourceExtension,
    outputSamples: action.extensionOutputSamples,
    effectiveRatio: action.speed,
  });
  return { action, retime };
}

function disposition() {
  const { action, retime } = actionAndRetime();
  const payload = {
    schemaVersion: 1,
    kind: "palmier-cut-repair-disposition",
    selected: true,
    operationHash: canonicalJsonSha256(action),
    nativeStatus: "unsupported",
    deliveryDisposition: "baked-exact-master",
    sampleExact: false,
    repairSpeed: action.speed,
    repairRetime: retime,
    reason: "sample-exact native readback is unavailable",
    requiresRepairFragmentImport: true,
  } as const;
  return {
    action,
    retime,
    value: { ...payload, projectionHash: canonicalJsonSha256(payload) },
  };
}

function exactParityPasses(): void {
  const expected = disposition();
  const parsed = parsePalmierCutRepairDispositionV1(expected.value);
  assert.equal(parsed.selected, true);
  if (!parsed.selected) throw new Error("selected disposition was lost");
  assert.deepEqual(parsed.repairSpeed, expected.action.speed);
  assert.deepEqual(parsed.repairRetime, expected.retime);
}

function staleParityFailsClosed(): void {
  const expected = disposition();
  const wrongSpeed = {
    ...expected.value,
    repairSpeed: { numerator: "1", denominator: "1" },
  };
  const wrongPayload = { ...wrongSpeed } as Record<string, unknown>;
  delete wrongPayload.projectionHash;
  assert.throws(() => parsePalmierCutRepairDispositionV1({
    ...wrongSpeed,
    projectionHash: canonicalJsonSha256(wrongPayload),
  }), /speed and renderer retime disagree/);
  assert.throws(() => parseCutRepairRetimeV1({
    ...expected.retime,
    effectiveRatio: { numerator: "4", denominator: "5" },
  }), /effective ratio does not match/);
}

exactParityPasses();
staleParityFailsClosed();
console.log("p2-cut-repair-speed-parity tests passed");
