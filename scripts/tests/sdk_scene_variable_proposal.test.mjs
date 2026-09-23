/** Installed SDK structural compatibility only: no browser, rendering or HTML publication. */
import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { proposeSceneVariable } from "../producer/studio/sdk_scene_variable_proposal.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const BUNDLE = join(ROOT, "scripts/producer/tests/fixtures/fire-sparkles-bundle");
const HTML = join(BUNDLE, "compositions/unit-right.html");
const sha = value => createHash("sha256").update(value).digest("hex");
const PYTHON = `
import copy, json, pathlib, sys
from dataclasses import asdict
from edit.exact_timing import PositiveRational
from graphics.scene_bundle import capture_bundle
from graphics.scene_lint import validate_scene_bundle
from planner.treatment_models import TreatmentState
from planner.treatment_operations import apply_treatment_operation
from tests.scene_fixtures import fire_sparkles_scene
request = json.load(sys.stdin)
bundle = capture_bundle(str(pathlib.Path(request.get("bundleDir", "scripts/producer/tests/fixtures/fire-sparkles-bundle")).resolve()))
scene = validate_scene_bundle(fire_sparkles_scene(bundle.digest), bundle)
if "operation" not in request:
    print(json.dumps({"scene": scene, "bundle": {"hash": bundle.digest, "manifest": bundle.manifest, "files": bundle.files}}))
else:
    assert request["bundleHash"] == bundle.digest
    plan = {"cutTrack": [{"sourceId": "source-main", "srcStart": 0, "srcEnd": 60}], "music": {"enabled": False}}
    state = TreatmentState(plan, (scene,), PositiveRational(30, 1), 1800)
    original = copy.deepcopy(state)
    result = apply_treatment_operation(state, request["operation"])
    assert state == original, "actual handler changed its original state"
    print(json.dumps({"original": asdict(original), "state": asdict(result.state), "receipt": result.receipt}))
`;

function python(request = {}) {
  const result = spawnSync(join(ROOT, ".venv/bin/python"), ["-B", "-c", PYTHON], {
    cwd: ROOT, env: { ...process.env, PYTHONPATH: join(ROOT, "scripts/producer"), PYTHONDONTWRITEBYTECODE: "1" },
    input: JSON.stringify(request), encoding: "utf8", timeout: 10000, maxBuffer: 2 * 1024 * 1024,
  });
  assert.ifError(result.error); assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

async function existingSdk() {
  const installed = join(ROOT, "node_modules/@hyperframes/sdk");
  assert.equal(realpathSync(fileURLToPath(import.meta.resolve("@hyperframes/sdk"))), realpathSync(join(installed, "dist/index.js")));
  const metadata = JSON.parse(readFileSync(join(installed, "package.json"), "utf8"));
  assert.equal(metadata.name, "@hyperframes/sdk"); assert.equal(metadata.version, "0.8.31");
  const project = JSON.parse(readFileSync(join(ROOT, "package.json"), "utf8"));
  assert.equal(project.dependencies["@hyperframes/sdk"], "0.8.31");
  return import("@hyperframes/sdk");
}

function fixture(bundleDir = BUNDLE) {
  const supplied = python({ bundleDir }), html = readFileSync(join(bundleDir, "compositions/unit-right.html"), "utf8");
  return { ...supplied, html, originalHtmlSha256: sha(html), unitId: "unit-right", elementId: "right-copy",
    variable: "rightTitle", expectedValue: "Change only this card", value: "Keep the original footage until the export passes review",
    expectedSceneVersion: 1 };
}

function currentBundleFixture(t) {
  const directory = realpathSync(mkdtempSync(join(tmpdir(), "sniper-sdk-bundle-")));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  mkdirSync(join(directory, "compositions"));
  const files = ["bundle.json", "compositions/full.html", "compositions/unit-left.html",
    "compositions/unit-right.html", "compositions/scene-common.js", "compositions/scene.css"];
  for (const name of files) {
    const original = readFileSync(join(BUNDLE, name), "utf8");
    const value = name === "bundle.json" ? original.replace('"hyperframesVersion":"0.7.33"', '"hyperframesVersion":"0.8.31"') : original;
    writeFileSync(join(directory, name), value, { flag: "wx", mode: 0o600 });
  }
  return directory;
}

function suppliedHtml(input, html) {
  input.html = html; input.originalHtmlSha256 = sha(html);
  Object.assign(input.bundle.files.find(row => row.path === "compositions/unit-right.html"), {
    sha256: input.originalHtmlSha256, sizeBytes: Buffer.byteLength(html),
  });
}

async function wrapped(overrides = () => undefined) {
  const sdk = await existingSdk(), events = { disposed: [], opened: 0 };
  const factory = { async openComposition(html, options) {
    assert.deepEqual(options, { history: false });
    const session = await sdk.openComposition(html, options), index = events.opened++;
    return new Proxy(session, { get(target, key) {
      const value = Reflect.get(target, key), bound = typeof value === "function" ? value.bind(target) : value;
      const custom = overrides({ index, key, bound, events });
      if (key === "dispose") return async () => { events.disposed.push(index); await (custom ?? bound)(); };
      return custom ?? bound;
    } });
  } };
  return { factory, events };
}

const includes = pattern => error => pattern.test([error.message, ...(error.errors ?? []).map(row => row.message)].join(" "));

test("closed/bounded JSON and factory accessors refuse without opening or evaluating getters", async () => {
  let called = 0;
  const sdk = { openComposition: () => { called++; throw new Error("must not open"); } };
  await assert.rejects(proposeSceneVariable({ html: "x".repeat(1024 * 1024 + 1) }, sdk), /input strings exceed/);
  await assert.rejects(proposeSceneVariable({ ["x".repeat(1024 * 1024 + 1)]: 1 }, sdk), /input keys exceed/);
  const bad = {}; Object.defineProperty(bad, "html", { enumerable: true, get() { called++; return ""; } });
  await assert.rejects(proposeSceneVariable(bad, sdk), /accessors/);
  const accessor = {}; Object.defineProperty(accessor, "openComposition", { enumerable: true, get() { called++; return sdk.openComposition; } });
  await assert.rejects(proposeSceneVariable({}, accessor), /own data SDK factory/);
  for (const value of [undefined, NaN, () => {}, Symbol("TEST"), new Array(1)]) {
    await assert.rejects(proposeSceneVariable({ value }, sdk));
  }
  assert.equal(called, 0);
});

test("project-installed default SDK → actual validated Python treatment handler changes only the authorized unit", async () => {
  await existingSdk();
  const input = fixture(), before = structuredClone(input);
  assert.equal(input.bundle.manifest.runtime.hyperframesVersion, "0.7.33");
  const proposal = await proposeSceneVariable(input);
  assert.deepEqual(input, before); assert.equal(readFileSync(HTML, "utf8"), input.html);
  assert.deepEqual(Object.keys(proposal).sort(), ["applied", "approved", "operation", "proposalOnly", "renderVerified", "suppliedBindingsOnly"]);
  assert.equal(proposal.proposalOnly, true); assert.equal(proposal.suppliedBindingsOnly, true);
  assert.equal(proposal.applied, false); assert.equal(proposal.approved, false); assert.equal(proposal.renderVerified, false);
  const result = python({ operation: proposal.operation, bundleHash: input.bundle.hash });
  const expected = structuredClone(result.original); expected.scenes[0].version = 2;
  expected.scenes[0].composition.variables.rightTitle = input.value;
  expected.scenes[0].elements.find(row => row.elementId === "right-copy").values.rightTitle = input.value;
  const source = result.state.scenes[0].visualSources;
  assert.notEqual(source.subjectSha256, expected.scenes[0].visualSources.subjectSha256);
  assert.deepEqual({ ...source, subjectSha256: null }, { ...expected.scenes[0].visualSources, subjectSha256: null });
  expected.scenes[0].visualSources.subjectSha256 = source.subjectSha256;
  assert.deepEqual(result.state, expected);
  assert.deepEqual(result.receipt.invalidatedNodes.sort(), ["composite:scene-045", "palmier-binding:scene-045:unit-right", "scene-unit-media:scene-045:unit-right"]);
  assert.deepEqual(result.receipt.dirtyWindows, [{ startFrame: 1350, endFrameExclusive: 1530 }]);
  assert.equal(result.receipt.mediaReused, false);
});

test("new captured 0.8.31 bundle uses default SDK without relabeling the original 0.7.33 bundle", async t => {
  const original = fixture(), bundleDir = currentBundleFixture(t), input = fixture(bundleDir), before = structuredClone(input);
  assert.equal(input.bundle.manifest.runtime.hyperframesVersion, "0.8.31");
  assert.notEqual(input.bundle.hash, original.bundle.hash);
  const proposal = await proposeSceneVariable(input);
  const result = python({ bundleDir, operation: proposal.operation, bundleHash: input.bundle.hash });
  assert.equal(result.state.scenes[0].composition.variables.rightTitle, input.value);
  assert.deepEqual(result.state.scenes[0].renderUnits, original.scene.renderUnits);
  assert.deepEqual(result.receipt.dirtyWindows, [{ startFrame: 1350, endFrameExclusive: 1530 }]);
  assert.equal(proposal.renderVerified, false); assert.deepEqual(input, before);
  assert.deepEqual(fixture(), original);
});

test("stale, shared, wrong raw binding and no-op inputs refuse before SDK callbacks", async () => {
  const input = fixture(); let calls = 0;
  const edits = [value => { value.originalHtmlSha256 = "a".repeat(64); }, value => { value.expectedSceneVersion++; },
    value => { value.value = value.expectedValue; }, value => { value.value = "x".repeat(121); },
    value => { value.value = 12; }, value => { value.elementId = "unknown-dynamic-element"; },
    value => { value.bundle.manifest.runtime.hyperframesVersion = "0.8.30"; },
    value => { value.bundle.manifest.runtime.hyperframesVersion = 0.831; },
    value => { value.bundle.files.find(row => row.path === "compositions/unit-right.html").sizeBytes++; },
    value => { value.bundle.manifest.variables.find(row => row.id === "rightTitle").elementIds.push("left-blue-card"); },
    value => { value.scene.elements[0].exposedProperties.push("rightTitle"); },
    value => { value.scene.renderUnits[0].elementIds.push("right-copy"); },
    value => { value.scene.composition.variables.rightTitle = "Different original"; },
    value => { value.variable = "seed"; value.elementId = "seeded-sparkles"; value.expectedValue = 424242; value.value = 7; },
    value => { value.extra = "unsupported"; }];
  for (const edit of edits) {
    const changed = structuredClone(input); edit(changed);
    await assert.rejects(proposeSceneVariable(changed, { openComposition: () => { calls++; } }));
  }
  assert.equal(calls, 0);
});

test("declared Unicode copy remains complete, never truncated", async () => {
  const input = fixture(), { factory } = await wrapped(); input.value = "🎬".repeat(120);
  const result = await proposeSceneVariable(input, factory); assert.equal(result.operation.text, input.value);
  input.value += "🎬"; await assert.rejects(proposeSceneVariable(input, factory), /copy exceeds/);
});

test("headless SDK parsing never executes supplied inline scripts or external scripts", async () => {
  const input = fixture(), { factory } = await wrapped(), marker = "__SNIPER_TEST_SDK_EXECUTED__";
  assert.equal(globalThis[marker], undefined);
  suppliedHtml(input, input.html + `<script>globalThis.${marker}=true;throw new Error('TEST script must not run')</script>`);
  await proposeSceneVariable(input, factory); assert.equal(globalThis[marker], undefined);
});

test("static root geometry and exact frame duration are bound, including NTSC rational rates", async () => {
  const input = fixture(), { factory } = await wrapped();
  for (const [oldValue, changed] of [['data-duration="6"', 'data-duration="7"'],
    ['data-width="1920"', 'data-width="1280"'], ['data-duration="6"', 'data-duration="6e0"']]) {
    const mismatch = structuredClone(input); suppliedHtml(mismatch, mismatch.html.replace(oldValue, changed));
    await assert.rejects(proposeSceneVariable(mismatch, factory), includes(/root geometry|root duration/));
  }
  input.scene.timing.fps = { numerator: "30000", denominator: "1001" };
  suppliedHtml(input, input.html.replace('data-duration="6"', 'data-duration="6.006"'));
  const before = structuredClone(input); await proposeSceneVariable(input, factory); assert.deepEqual(input, before);
  suppliedHtml(input, input.html.replace('data-duration="6.006"', 'data-duration="6.005999999999999999"'));
  await assert.rejects(proposeSceneVariable(input, factory), includes(/root duration differs/));
});

test("patch whitelist refuses extra paths and differently typed values", async () => {
  const input = fixture();
  for (const alter of [event => event.patches.push({ op: "replace", path: "/html", value: "TEST" }),
    event => { event.patches[0].value = 12; }, event => { event.inversePatches.pop(); }]) {
    const { factory, events } = await wrapped(({ key, bound }) => key === "on" ? (name, callback) =>
      bound(name, event => { const copy = structuredClone(event); alter(copy); callback(copy); }) : undefined);
    await assert.rejects(proposeSceneVariable(input, factory), includes(/patch paths/)); assert.deepEqual(events.disposed, [0]);
  }
});

test("reopen/inverse serialization refuses code changes, including normalization-dropped code", async () => {
  const input = fixture();
  for (const change of [html => `${html}<!-- TEST-unrequested-code -->`,
    html => html.replace("</body>", "<!-- TEST-unrequested-code --></body>")]) {
    let serialized = 0;
    const { factory, events } = await wrapped(({ index, key, bound }) => index === 0 && key === "serialize" ? () => {
      const html = bound(); return ++serialized === 2 ? change(html) : html;
    } : undefined);
    await assert.rejects(proposeSceneVariable(input, factory), includes(/serialized/)); assert.deepEqual(events.disposed, [1, 0]);
  }
});

test("reopened timing and every unaffected declaration must remain exact", async () => {
  const input = fixture();
  for (const target of ["getElementTimings", "listVariables"]) {
    const { factory, events } = await wrapped(({ index, key, bound }) => index === 1 && key === target ? () => {
      const value = structuredClone(bound());
      if (target === "listVariables") value.find(row => row.id === "seed").default++;
      else value["TEST-unrequested-timing"] = { start: 0, duration: 1 };
      return value;
    } : undefined);
    await assert.rejects(proposeSceneVariable(input, factory), includes(/reopened/)); assert.deepEqual(events.disposed, [1, 0]);
  }
});

test("readback and disposal failures retain both errors and attempt both session disposals", async () => {
  const { factory, events } = await wrapped(({ index, key, bound }) => {
    if (index === 1 && key === "getVariableValue") return () => "wrong TEST value";
    if (key === "dispose") return async () => { await bound(); throw new Error(`TEST-dispose-${index}`); };
    return undefined;
  });
  await assert.rejects(proposeSceneVariable(fixture(), factory), error => {
    assert.ok(includes(/reopened/)(error)); assert.ok(includes(/TEST-dispose-0/)(error));
    assert.ok(includes(/TEST-dispose-1/)(error)); return true;
  });
  assert.deepEqual(events.disposed, [1, 0]);
});

test("successful readback still refuses disposal failure or late caller/factory substitution", async () => {
  const input = fixture();
  for (const fault of ["dispose", "input", "factory"]) {
    const original = structuredClone(input);
    const { factory, events } = await wrapped(({ index, key, bound }) => index === 0 && key === "dispose" ? async () => {
      await bound();
      if (fault === "dispose") throw new Error("TEST-dispose-only");
      if (fault === "input") original.expectedSceneVersion++;
      if (fault === "factory") factory.openComposition = () => { throw new Error("must not call"); };
    } : undefined);
    await assert.rejects(proposeSceneVariable(original, factory)); assert.deepEqual(events.disposed, [1, 0]);
  }
});

test("first SDK callback cannot rebaseline original supplied input", async () => {
  const input = fixture(), sdk = await wrapped(), open = sdk.factory.openComposition;
  sdk.factory.openComposition = async (...args) => { const session = await open(...args); input.scene.version++; return session; };
  await assert.rejects(proposeSceneVariable(input, sdk.factory), includes(/original supplied input/));
  assert.deepEqual(sdk.events.disposed, [0]);
});

test("late getter substitution refuses without executing the substituted getter", async () => {
  const input = fixture(), html = input.html; let getters = 0;
  const { factory, events } = await wrapped(({ index, key, bound }) => index === 0 && key === "dispose" ? async () => {
    await bound();
    Object.defineProperty(input, "html", { enumerable: true, configurable: true, get() { getters++; return html; } });
  } : undefined);
  await assert.rejects(proposeSceneVariable(input, factory), includes(/accessors/));
  assert.equal(getters, 0); assert.deepEqual(events.disposed, [1, 0]);
});
