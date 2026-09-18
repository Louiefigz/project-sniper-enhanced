import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { audioAuditFailure } from "../audit-audio-policy";
import { audioAuditFixture } from "./audit-audio-fixture";

const clean = audioAuditFixture();
assert.equal(audioAuditFailure(clean, clean.finalSha256), null);
assert.match(audioAuditFailure(clean, "b".repeat(64))!, /expected candidate/);
assert.match(audioAuditFailure({ overall: "pass", checks: [] })!, /policy v2/);
for (const peak of [-1.5, -1.49, -0.6]) {
  const value = audioAuditFixture();
  const passed = peak <= -1.5;
  value.audioDelivery.truePeakDbtp = peak;
  value.audioDelivery.truePeakExcessDb = Math.max(0, peak + 1.5);
  value.audioDelivery.truePeakWithinCeiling = passed;
  value.audioDelivery.qualified = passed;
  value.checks.find((row) => row.name === "loudness_true_peak")!.status = passed ? "pass" : "fail";
  assert.equal(audioAuditFailure(value) === null, passed);
}
for (const key of Object.keys(clean.audioDelivery)) {
  const evidence: Record<string, unknown> = { ...clean.audioDelivery };
  delete evidence[key];
  assert.ok(audioAuditFailure({ ...clean, audioDelivery: evidence }), key);
}
for (const invalid of [NaN, Infinity, -Infinity, "-14", undefined]) {
  assert.ok(audioAuditFailure({ ...clean,
    audioDelivery: { ...clean.audioDelivery, integratedLufs: invalid } }));
}
for (const check of clean.checks) {
  assert.ok(audioAuditFailure({ ...clean, checks: clean.checks.filter((row) => row !== check) }));
  assert.ok(audioAuditFailure({ ...clean, checks: [...clean.checks, check] }));
}
assert.ok(audioAuditFailure({ ...clean, audioDelivery: { ...clean.audioDelivery, unknown: true } }));
assert.ok(audioAuditFailure({ ...clean, audioDelivery: { ...clean.audioDelivery, audioDecodeExitCode: 1 } }));
assert.ok(audioAuditFailure({ ...clean, audioDelivery: { ...clean.audioDelivery, lufsResidual: 1 } }));
assert.ok(audioAuditFailure({ ...clean, checks: clean.checks.map((row) => ({ ...row, status: "warn" })) }));

// Cross-runtime real media: consume Python's actual Audit B report, then the
// same synthetic file with damaged AAC tail. This does not run model reviews.
const root = mkdtempSync(path.join(os.tmpdir(), "sniper-audio-audit-media-"));
try {
  const code = [
    "import json, sys",
    "from pathlib import Path",
    "from test_audio_mix_without_media import _source, _corrupt_audio_tail",
    "from audit.audit_render import run_audit, report_to_dict",
    "root=Path(sys.argv[1]); final=root/'final.mp4'",
    "_source(root,(0.2,0.2)).rename(final)",
    "clean=report_to_dict(run_audit(str(root)))",
    "_corrupt_audio_tail(final)",
    "damaged=report_to_dict(run_audit(str(root)))",
    "print(json.dumps({'clean':clean,'damaged':damaged}))",
  ].join("\n");
  const result = spawnSync(path.resolve(".venv/bin/python"), ["-c", code, root], {
    env: { ...process.env, PYTHONPATH: "scripts/producer:scripts/producer/tests", PYTHONDONTWRITEBYTECODE: "1" },
    encoding: "utf8", timeout: 60_000,
  });
  assert.equal(result.status, 0, result.stderr);
  const observed = JSON.parse(result.stdout);
  assert.equal(audioAuditFailure(observed.clean, observed.clean.finalSha256), null);
  assert.match(audioAuditFailure(observed.damaged)!, /complete-decode/);
  assert.notEqual(observed.clean.finalSha256, observed.damaged.finalSha256);
} finally {
  rmSync(root, { recursive: true, force: true });
}
console.log("audit-audio-policy.test.ts: all assertions passed (including real FFmpeg reports)");
