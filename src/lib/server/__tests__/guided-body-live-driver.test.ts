/** No ASR, model, renderer, Docker or creator approval: tests only the expensive driver's boundaries. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { assertBodyLiveSynthetic, bodyLiveMain, parseBodyLiveMode } from "./_guided-body-live-fixture";
import { bodyLiveBodyCommand, bodyLiveCommand, bodyLiveObserverTimeout,
  bodyOperationInventory, newBodyLiveLog, retainBodyLive } from "./_guided-body-live-support";
import { assertBodyLiveConflict, bodyLiveAuditSummary, bodyLiveMetadataInventory } from "./_guided-body-live-result";
import { captionedProgramDocuments } from "./_human-cut-fixture";

function fixture() {
  const workspace = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-body-driver-unit-")));
  const log = newBodyLiveLog(workspace), root = path.join(workspace, "test-only-cut-review-1234abcd"), dir = path.join(root, "producer");
  mkdirSync(dir, { recursive: true });
  const marker = path.join(root, "SYNTHETIC-TEST-ONLY.json");
  writeFileSync(marker, JSON.stringify({ synthetic: true, program: "longform-body-300", modelCalls: 0, humanAccepted: false, creativeQualityQualified: false }));
  return { log, dir, marker, cleanup: () => rmSync(workspace, { recursive: true, force: true }) };
}

test("live driver defaults to help and forbids old/creator paths or weaker profiles", async () => {
  assert.equal(parseBodyLiveMode([]), "help"); assert.equal(parseBodyLiveMode(["--run"]), "run");
  assert.equal(parseBodyLiveMode(["--run-captioned"]), "run-captioned");
  assert.equal(parseBodyLiveMode(["--check-controls"]), "check-controls");
  for (const args of [["/Users/aaronfigueroa/Downloads/C0679.MP4"], ["--run", "/tmp/run14"], ["--program=longform-96"], ["--run", "--no-gates"]]) {
    assert.throws(() => parseBodyLiveMode(args), /existing projects are forbidden/);
  }
  const help = await bodyLiveMain(["--help"]);
  assert.equal("genuineHumanAcceptance" in help && help.genuineHumanAcceptance, false);
  assert.match(JSON.stringify(help), /never public final/);
});

test("synthetic attestation requires exact driver-owned project and expected TEST marker", () => {
  const f = fixture();
  try {
    assert.doesNotThrow(() => assertBodyLiveSynthetic(f.log, f.dir));
    assert.throws(() => assertBodyLiveSynthetic({ ...f.log, workspace: path.dirname(f.log.workspace) }, f.dir));
    writeFileSync(f.marker, JSON.stringify({ synthetic: true, program: "longform-body-300", modelCalls: 0, humanAccepted: true, creativeQualityQualified: false }));
    assert.throws(() => assertBodyLiveSynthetic(f.log, f.dir));
    writeFileSync(f.marker, JSON.stringify({ synthetic: true, program: "longform-300", modelCalls: 0, humanAccepted: false, creativeQualityQualified: false }));
    assert.throws(() => assertBodyLiveSynthetic(f.log, f.dir), /longform-body-300/);
  } finally { f.cleanup(); }
});

test("captioned TEST class authors matching initial lane ownership without altering any other program fields", () => {
  const lanes = { motion: "off", captions: "off", transitions: "off", broll: "off" };
  const project = { intent: { mode: "longform", scope: "produced", lanes, music: false }, TEST: true };
  const plan = { target: { mode: "longform", scope: "produced", width: 1920, height: 1080, lanes },
    cutTrack: [{ sourceId: "TEST", start: 0, end: 312 }], cutDecisions: { schemaVersion: 1, removals: [] } };
  const before = structuredClone({ project, plan }), changed = captionedProgramDocuments(project, plan);
  assert.deepEqual({ project, plan }, before);
  assert.deepEqual(changed.project, { ...project, intent: { ...project.intent, lanes: { ...lanes, captions: "auto" } } });
  assert.deepEqual(changed.plan, { ...plan, target: { ...plan.target, lanes: { ...lanes, captions: "auto" } } });
  assert.throws(() => captionedProgramDocuments(changed.project, changed.plan));
  assert.throws(() => captionedProgramDocuments(project, { ...plan, target: { ...plan.target, scope: "trim" } }));
});

test("CLI seam uses actual command form and retains exactly one bounded completion", async () => {
  const f = fixture(); let calls = 0;
  try {
    const result = await bodyLiveCommand({ log: f.log, dir: f.dir, command: "status" }, async (input) => {
      calls += 1; assert.equal(input.command, process.execPath);
      assert.deepEqual(input.args, ["--import", "tsx", "scripts/producer/guided-opening.ts", "status", f.dir]);
      assert.equal(input.env.SNIPER_WORKSPACE_ROOT, f.log.workspace); assert.equal(input.timeoutMs, 180_000);
      return { stdout: '{"state":"TEST-only"}\n', stderr: "TEST diagnostics\n" };
    });
    assert.deepEqual(result, { state: "TEST-only" }); assert.equal(calls, 1);
    const saved = JSON.parse(readFileSync(path.join(f.log.root, "0001-cli-status.output.json"), "utf8"));
    assert.equal(saved.stderr, "TEST diagnostics\n");
  } finally { f.cleanup(); }
});

test("malformed or extra CLI stdout fails without selecting last-match JSON", async () => {
  const f = fixture();
  try {
    await assert.rejects(bodyLiveCommand({ log: f.log, dir: f.dir, command: "status" }, async () => ({ stdout: '{}\n{}\n', stderr: "" })), /exactly one/);
    assert.ok(readdirSync(f.log.root).some((name) => name.endsWith("failed.json")));
  } finally { f.cleanup(); }
});

test("unknown launch failure retains stop uncertainty and never retries", async () => {
  const f = fixture(); let calls = 0;
  try {
    await assert.rejects(bodyLiveCommand({ log: f.log, dir: f.dir, command: "launch", request: "/TEST/request.json" }, async () => {
      calls += 1; throw new CutPreviewProcessError("TEST lost launch response", {
        stdout: "TEST partial", stderr: "TEST failure", timedOut: true, groupStopped: false, forcedStop: true });
    }), /lost launch response/);
    assert.equal(calls, 1);
    const failure = JSON.parse(readFileSync(path.join(f.log.root, "0001-cli-launch.failed.json"), "utf8"));
    assert.equal(failure.process.groupStopped, false); assert.equal(failure.automaticRetry, false);
    assert.equal(failure.cleanupClaim, "not-inferred-by-test-driver");
  } finally { f.cleanup(); }
});

test("retained files are new-only and replay inventory detects edits/new files and refuses links", () => {
  const f = fixture();
  try {
    retainBodyLive(f.log, "held.json", { a: 1 });
    assert.throws(() => retainBodyLive(f.log, "held.json", { a: 2 }), /EEXIST/);
    const before = bodyOperationInventory(f.log.root);
    retainBodyLive(f.log, "new.json", { b: 1 }); assert.notDeepEqual(bodyOperationInventory(f.log.root), before);
    symlinkSync(f.marker, path.join(f.log.root, "link.json")); assert.throws(() => bodyOperationInventory(f.log.root), /refuses links/);
  } finally { f.cleanup(); }
});

test("body CLI observer has separate bounded cleanup headroom, never a new generation clock", () => {
  const start = "2026-09-07T12:00:00.000Z", began = Date.parse(start), minute = 60_000;
  assert.equal(bodyLiveObserverTimeout(start, began), 60 * minute + 10_000);
  assert.equal(bodyLiveObserverTimeout(start, began + 115 * minute), 10 * minute + 10_000);
  assert.equal(bodyLiveObserverTimeout(start, began + 120 * minute), 5 * minute + 10_000);
  for (const now of [began - 1, NaN, Infinity, began + 0.5, began + 125 * minute + 10_000]) {
    assert.throws(() => bodyLiveObserverTimeout(start, now));
  }
  assert.throws(() => bodyLiveObserverTimeout("2026-09-07T12:00:00Z", began));
});

test("body foreground observer invokes actual run form with separate process class and does not retry", async () => {
  const f = fixture(); let calls = 0;
  try {
    const result = await bodyLiveBodyCommand({ log: f.log, dir: f.dir, command: "run",
      request: "/TEST/body-request.json", generationStartedAt: new Date().toISOString() }, async (input) => {
      calls += 1;
      assert.deepEqual(input.args, ["--import", "tsx", "scripts/producer/guided-body.ts", "run", f.dir, "/TEST/body-request.json"]);
      assert.equal(input.purpose, "guided-body-command"); assert.equal(input.timeoutMs, 3_610_000);
      return { stdout: '{"state":"TEST-only-private"}\n', stderr: "TEST body diagnostics\n" };
    });
    assert.deepEqual(result, { state: "TEST-only-private" }); assert.equal(calls, 1);
    await assert.rejects(bodyLiveBodyCommand({ log: f.log, dir: f.dir, command: "run",
      generationStartedAt: new Date().toISOString() }), /exact request/);
  } finally { f.cleanup(); }
});

test("TEST audit summary preserves warnings and never labels missing or failed required checks as quality", () => {
  const expected = { path: "/TEST/NOT-REAL/final.mp4", sha256: "a".repeat(64) };
  const names = ["duration", "audio_decode_complete", "loudness_integrated", "loudness_true_peak", "format_resolution",
    "format_vcodec", "format_profile", "format_pix_fmt", "format_cfr", "format_faststart", "format_acodec",
    "format_arate", "format_achannels", "audio_av_timing", "final_identity"];
  const audit = { TEST_ONLY: true, final: expected.path, finalSha256: expected.sha256, exitCode: 0, overall: "warn",
    counts: { pass: names.length, warn: 1, fail: 0 }, audioDelivery: { audioDecodeSucceeded: true },
    checks: [...names.map((name) => ({ name, status: "pass" })), { name: "TEST pacing review", status: "warn" }] };
  const result = bodyLiveAuditSummary(audit, expected);
  assert.deepEqual(result.warnings, [{ name: "TEST pacing review", status: "warn" }]);
  assert.equal(result.listeningPerformed, false); assert.equal(result.creativeQualityQualified, false);
  assert.throws(() => bodyLiveAuditSummary(audit, { ...expected, requireCaptions: true }), /caption authority/);
  const captioned = { ...audit, counts: { pass: names.length + 1, warn: 1, fail: 0 },
    checks: [...audit.checks, { name: "caption_authority", status: "pass" }] };
  assert.doesNotThrow(() => bodyLiveAuditSummary(captioned, { ...expected, requireCaptions: true }));
  for (const changed of [{ ...audit, checks: audit.checks.slice(1) }, { ...audit, finalSha256: "b".repeat(64) },
    { ...audit, overall: "pass" }, { ...audit, checks: [...audit.checks, { name: "TEST missed graphic", status: "fail" }] },
    { ...audit, audioDelivery: { audioDecodeSucceeded: false } }]) assert.throws(() => bodyLiveAuditSummary(changed, expected));
});

test("TEST replay metadata covers binary files without loading bytes and detects new attempts and links", () => {
  const f = fixture();
  try {
    const binary = path.join(f.dir, "TEST-binary.mp4"); writeFileSync(binary, "TEST-not-video");
    const before = bodyLiveMetadataInventory(f.dir);
    assert.equal(before["TEST-binary.mp4"].size, "14");
    assert.equal("sha256" in before["TEST-binary.mp4"], false, "Stat inventory must not pretend to hash bytes");
    mkdirSync(path.join(f.dir, "TEST-new-attempt"));
    assert.notDeepEqual(bodyLiveMetadataInventory(f.dir), before);
    symlinkSync(binary, path.join(f.dir, "TEST-link"));
    assert.throws(() => bodyLiveMetadataInventory(f.dir), /refuses links/);
  } finally { f.cleanup(); }
});

test("different-request proof requires exact conflict denial and normal stopped process, not just any error", () => {
  const details = { timedOut: false, groupStopped: true, forcedStop: false, stdout: "",
    stderr: JSON.stringify({ ok: false, code: "BODY_REQUEST_CONFLICT", error: "TEST explicit existing request conflict" }) };
  assert.doesNotThrow(() => assertBodyLiveConflict(new CutPreviewProcessError("TEST normal nonzero", details, 1)));
  for (const change of [{ timedOut: true }, { groupStopped: false }, { forcedStop: true }, { stdout: "{}\n" },
    { stderr: "TEST cannot import CLI" }, { stderr: '{}\n{}\n' },
    { stderr: JSON.stringify({ ok: false, code: "BODY_COMMAND_FAILED", error: "TEST unrelated failure" }) },
    { stderr: JSON.stringify({ ok: false, code: "BODY_REQUEST_CONFLICT", error: "TEST conflict", unexpected: true }) }]) {
    assert.throws(() => assertBodyLiveConflict(new CutPreviewProcessError("TEST negative", { ...details, ...change }, 1)));
  }
  for (const code of [undefined, null, 0, 256]) assert.throws(() => assertBodyLiveConflict(new CutPreviewProcessError("TEST exit", details, code)));
  assert.throws(() => assertBodyLiveConflict(new Error("TEST not an actual owned process outcome")));
});
