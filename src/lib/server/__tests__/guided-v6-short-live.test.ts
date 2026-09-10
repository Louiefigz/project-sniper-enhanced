/** Inert TEST boundaries unless explicitly opted in; no existing creator directory can be supplied. */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { test, type TestContext } from "node:test";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { bootstrapGuidedProject, bootstrapServices } from "../guided-project-bootstrap";
import { parseBootstrapRequest } from "../guided-project-bootstrap-contract";
import { BOOTSTRAP_INTAKE, BOOTSTRAP_UNKNOWN } from "../guided-project-bootstrap-store";
import { bindV6ShortSynthetic } from "./_guided-v6-short-live-guard";
import { approveLiveSynthetic, generateLiveBody, type SyntheticLiveFlow } from "./_guided-body-live-flow";
import { assertShortNoGraphicsScreen, runV6ShortLiveFixture, shortSetupRemaining,
  V6_SHORT_MEDIA_OPT_IN, V6_SHORT_MEDIA_OBSERVATION_MS } from "./_guided-v6-short-live-fixture";

/** Fake admission EXPECTATIONS only. No source verifier, critics, preview, quiescence or decision is invoked. */
async function metadataFixture(t: TestContext) {
  const workspace = realpathSync(mkdtempSync(path.join(tmpdir(), "sniper-v6-short-")));
  const previous = process.env.SNIPER_WORKSPACE_ROOT; process.env.SNIPER_WORKSPACE_ROOT = workspace;
  t.after(() => {
    if (previous === undefined) delete process.env.SNIPER_WORKSPACE_ROOT; else process.env.SNIPER_WORKSPACE_ROOT = previous;
    rmSync(workspace, { recursive: true, force: true });
  });
  const sourceRoot = path.join(workspace, "TEST-source"), source = path.join(sourceRoot, "source"); mkdirSync(source, { recursive: true });
  const intent = { mode: "short", scope: "light", lanes: { captions: "auto", motion: "off", graphics: "off" } };
  const plan = { planVersion: 1, target: { ...intent, width: 1080, height: 1920, fps: 30 },
    cutTrack: [{ sourceId: "raw-1", start: 0, end: 16, speed: 1, rationale: "TEST ONLY retain the complete synthetic program." }],
    cutDecisions: { schemaVersion: 1, removals: [] } };
  const write = (file: string, value: unknown) => writeFileSync(file, JSON.stringify(value), { flag: "wx" });
  const marker = path.join(workspace, "TEST-ONLY.json"), candidate = path.join(sourceRoot, "TEST-previsual-plan.json");
  const manifest = path.join(source, "asset_manifest.json"), transcript = path.join(source, "raw.transcript.json");
  write(marker, { synthetic: true, genuineHumanAcceptance: false, actualAsr: false, providerCalls: 0,
    launchTransport: "in-process TEST controller, not detached qualification" });
  write(candidate, plan); write(transcript, { TEST_ONLY: "metadata, not ASR or admitted source" });
  write(path.join(sourceRoot, "TEST-initial-documents.json"), { plan, intent, scope: "TEST-only-synthetic-text-not-ASR-or-human-approval" });
  write(manifest, { sources: [{ id: "raw-1", transcriptPath: "raw.transcript.json" }], sourceSetAdmission: { schemaVersion: 1 } });
  const original = readCutPreviewObject(candidate);
  const request = parseBootstrapRequest({ schemaVersion: 1, operation: "bootstrap-existing-cut", idempotencyKey: randomUUID(), intent,
    candidate: { path: candidate, sha256: original.sha256 }, manifest: { path: manifest, sha256: readCutPreviewObject(manifest).sha256 } });
  t.mock.method(bootstrapServices, "pin", ({ ctx }: Parameters<typeof bootstrapServices.pin>[0]) => ctx);
  t.mock.method(bootstrapServices, "launch", async () => 7777); // No process is launched or declared stopped.
  const result = await bootstrapGuidedProject(request), dir = result.producerDir;
  return { workspace, sourceRoot, request, original, dir, root: path.dirname(dir), saved: readCutPreviewObject(path.join(dir, "edit_plan.json")), marker, transcript };
}

test("short TEST metadata guard holds exact fresh intake, original bytes and only four previsual fields", async (t) => {
  const f = await metadataFixture(t), before = readFileSync(f.request.candidate.path), guard = bindV6ShortSynthetic(f);
  guard(); guard(); assert.deepEqual(readFileSync(f.request.candidate.path), before);
  assert.equal(f.saved.value.planVersion, 2); assert.equal(f.original.value.planVersion, 1);
  assert.deepEqual(Object.keys(f.original.value).sort(), ["cutDecisions", "cutTrack", "planVersion", "target"]);
  assert.throws(() => bindV6ShortSynthetic({ ...f, workspace: path.dirname(f.workspace) }));
  assert.throws(() => bindV6ShortSynthetic({ ...f, dir: path.join(f.root, "other") }));
  assert.throws(() => bindV6ShortSynthetic({ ...f, request: { ...f.request, idempotencyKey: randomUUID() } }));
  assert.throws(() => bindV6ShortSynthetic({ ...f, original: { ...f.original, value: { ...f.original.value, reframe: {} } } }));
});

test("short TEST guards reject changed original, saved, manifest, transcript, marker and intake bytes", async (t) => {
  const f = await metadataFixture(t), guard = bindV6ShortSynthetic(f);
  const files = [f.request.candidate.path, path.join(f.dir, "edit_plan.json"), f.request.manifest.path,
    f.transcript, f.marker, path.join(f.root, BOOTSTRAP_INTAKE), path.join(f.sourceRoot, "TEST-initial-documents.json")];
  for (const file of files) {
    const before = readFileSync(file); writeFileSync(file, Buffer.concat([before, Buffer.from("\n")]));
    assert.throws(guard, file); writeFileSync(file, before); guard();
  }
});

test("short TEST marker is closed and a live unknown marker blocks before any decision", async (t) => {
  const f = await metadataFixture(t), marker = JSON.parse(readFileSync(f.marker, "utf8"));
  for (const patch of [{ actualAsr: true }, { genuineHumanAcceptance: true }, { providerCalls: 1 }, { arbitraryMode: "creator" }]) {
    writeFileSync(f.marker, JSON.stringify({ ...marker, ...patch })); assert.throws(() => bindV6ShortSynthetic(f));
  }
  writeFileSync(f.marker, JSON.stringify(marker)); const guard = bindV6ShortSynthetic(f);
  writeFileSync(path.join(f.root, BOOTSTRAP_UNKNOWN), "TEST UNKNOWN"); assert.throws(guard, /unknown/);
});

test("short TEST inputs cannot switch to symlink aliases or a public final", async (t) => {
  const f = await metadataFixture(t), guard = bindV6ShortSynthetic(f);
  const alias = path.join(f.sourceRoot, "TEST-alias.json"); symlinkSync(f.request.candidate.path, alias);
  assert.throws(() => bindV6ShortSynthetic({ ...f, request: { ...f.request, candidate: { ...f.request.candidate, path: alias } } }));
  writeFileSync(path.join(f.dir, "final.mp4"), "TEST not media"); assert.throws(guard);
});

test("shared TEST synthetic guard rejects before reading approval data, writing attestations or invoking any CLI", async () => {
  let checks = 0;
  const scope: SyntheticLiveFlow = { dir: "/TEST-never-read", log: { workspace: "/TEST-never-read", root: "/TEST-never-written", sequence: 0, began: 0 },
    assertSynthetic: () => { checks++; throw new Error("TEST forbidden fixture"); } };
  const absent = null as unknown as Parameters<typeof approveLiveSynthetic>[1];
  await assert.rejects(approveLiveSynthetic(scope, absent), /forbidden fixture/);
  await assert.rejects(generateLiveBody(scope, absent, true), /forbidden fixture/);
  assert.equal(checks, 2);
});

test("short full-media entry is inert without exact opt-in and setup clock is not replenished", async (t) => {
  const prior = process.env[V6_SHORT_MEDIA_OPT_IN]; delete process.env[V6_SHORT_MEDIA_OPT_IN];
  try { await assert.rejects(runV6ShortLiveFixture(t), /exact explicit opt-in/); }
  finally { if (prior !== undefined) process.env[V6_SHORT_MEDIA_OPT_IN] = prior; }
  const controller = new AbortController(), start = performance.now(), remaining = shortSetupRemaining(start, controller.signal);
  const now = t.mock.method(performance, "now", () => start + 5000);
  assert.equal(remaining(), 595_000);
  now.mock.mockImplementation(() => start + 600_000); assert.throws(remaining, /expired/); now.mock.restore();
  for (const value of [-1, NaN, Infinity]) assert.throws(() => shortSetupRemaining(value, controller.signal), /Malformed/);
  controller.abort(); assert.throws(remaining, /expired/);
  assert.equal(V6_SHORT_MEDIA_OBSERVATION_MS, 150 * 60_000, "Outer observation includes original generation and cleanup headroom, not new work credit");
});

test("graphics-off short requires actual not-applicable caption screen without upgrading it to quality", () => {
  const hash = "a".repeat(64), row = { schemaVersion: 2, policy: "native-caption-layout-screen-v2",
    scope: "held-envelope-screen-not-pixel-legibility-or-creative-approval", state: "not-applicable",
    clock: { frameRate: "30/1", totalFrames: 480, width: 1080, height: 1920 }, coverage: { startFrame: 0, endFrameExclusive: 480 },
    captionProjectionHash: hash, inputHash: "b".repeat(64), graphics: [], qcPassed: false, creativeApproved: false, deliveryApproved: false };
  assert.doesNotThrow(() => assertShortNoGraphicsScreen(row, hash));
  for (const patch of [{ state: "screened-no-overlap" }, { qcPassed: true }, { creativeApproved: true }, { deliveryApproved: true },
    { captionProjectionHash: "c".repeat(64) }, { graphics: [{}] }, { inputHash: "" }, { clock: { ...row.clock, width: 1920 } },
    { coverage: { startFrame: 0, endFrameExclusive: 479 } }, { waived: true }]) {
    assert.throws(() => assertShortNoGraphicsScreen({ ...row, ...patch }, hash));
  }
  assert.throws(() => assertShortNoGraphicsScreen(undefined, hash));
});

test("actual fresh V6 short opening, explicit TEST decision, full body/AuditB and no-work replay", {
  skip: process.env[V6_SHORT_MEDIA_OPT_IN] !== "1", timeout: V6_SHORT_MEDIA_OBSERVATION_MS,
}, async (t) => {
  const result = await runV6ShortLiveFixture(t);
  assert.equal(result.state, "TEST-V6-short-private-body-mechanics-passed");
  assert.equal(result.bodyApproved, false); assert.equal(result.deliveryApproved, false);
});
