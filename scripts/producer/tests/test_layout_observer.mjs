// Pure Node/VM metadata tests. Fake DOM rectangles are not browser observations.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { browserExpression } from "../../../templates/motion/container/layout_observer_browser.mjs";
import { createRecorder, parseRequest, POLICY, PIPELINE_POLICY } from "../../../templates/motion/container/layout_observer_host.mjs";
import { instrument } from "../../../templates/motion/container/layout_observer_patch.mjs";

const request = () => ({ schemaVersion: 1, profile: POLICY, snapshotSha256: "a".repeat(64),
  composition: "compositions/agenda-slide.html", frameRate: "30000/1001", totalFrames: 2, width: 1920, height: 1080 });
const encoded = (value) => Buffer.from(JSON.stringify(value)).toString("base64");
const observation = () => ({ issues: [], roles: [{ id: "title", text: "TEST", bounds: [10, 20, 30, 40], opacity: 1, issues: [] }] });

test("closed JS admission exactly matches rational native frame policy", () => {
  assert.deepEqual(parseRequest(encoded(request())).value, request());
  for (const changes of [{ extra: false }, { schemaVersion: true }, { width: 1080, height: 1920 },
    { totalFrames: 1800 }, { frameRate: "29.97" }, { frameRate: "60000/2002" },
    { composition: "compositions/other.html" }, { totalFrames: 0 }, { profile: "legacy" },
    { frameRate: ["30000/1001"] }, { snapshotSha256: ["a".repeat(64)] }]) {
    assert.throws(() => parseRequest(encoded({ ...request(), ...changes })));
  }
});

test("exact actual write acknowledgment, not warmup/calibration, commits a frame", () => {
  const recorder = createRecorder(parseRequest(encoded(request())));
  const buffer = Buffer.from("TEST screenshot bytes");
  recorder.stage(1, 1001 / 30000, observation(), buffer); // Calibration never acknowledges.
  recorder.stage(0, 0, observation(), buffer);
  recorder.commit(0, buffer);
  recorder.stage(1, 1001 / 30000, observation(), buffer);
  recorder.commit(1, buffer);
  assert.equal(recorder.finish().framesObserved, 2);
});

test("missing, wrong-buffer, duplicate, reordered or wrong-time acknowledgment fails", () => {
  const recorder = createRecorder(parseRequest(encoded(request())));
  assert.throws(() => recorder.finish());
  assert.throws(() => recorder.commit(0, Buffer.from("TEST")));
  assert.throws(() => recorder.stage(0, 1, observation(), Buffer.from("TEST")));
  recorder.stage(0, 0, observation(), Buffer.from("TEST"));
  assert.throws(() => recorder.commit(0, Buffer.from("different")));
  recorder.commit(0, Buffer.from("TEST"));
  assert.throws(() => recorder.commit(0, Buffer.from("TEST")));
});

test("changed lexical inventory rejects; unsupported geometry is never observed", () => {
  const recorder = createRecorder(parseRequest(encoded(request())));
  recorder.stage(0, 0, observation(), Buffer.from("TEST"));
  recorder.commit(0, Buffer.from("TEST"));
  const altered = observation();
  altered.roles[0].text = "different";
  recorder.stage(1, 1001 / 30000, altered, Buffer.from("TEST"));
  assert.throws(() => recorder.commit(1, Buffer.from("TEST")));
  const unsupported = observation();
  unsupported.issues = ["unsupported-filter"];
  recorder.stage(1, 1001 / 30000, unsupported, Buffer.from("TEST"));
  recorder.commit(1, Buffer.from("TEST"));
  assert.equal(recorder.finish().status, "unqualified");
});

test("missing actual visibility cannot be dressed as safe", () => {
  const recorder = createRecorder(parseRequest(encoded({ ...request(), totalFrames: 1 })));
  const hidden = observation();
  hidden.roles[0].bounds = null;
  hidden.roles[0].opacity = 0;
  recorder.stage(0, 0, hidden, Buffer.from("TEST"));
  recorder.commit(0, Buffer.from("TEST"));
  assert.equal(recorder.finish().status, "unqualified");
});

test("only the exact installed CLI bytes accept the narrow instrumentation", () => {
  const path = "/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/templates/motion/node_modules/hyperframes/dist/cli.js";
  const source = readFileSync(path, "utf8"), patched = instrument(source);
  assert.ok(patched.includes("__sniperLayoutCdp = await getCdpSession(page)"));
  assert.ok(patched.includes("ensureFrameWritten(await currentEncoder.writeFrame(buffer), i2, currentEncoder);\n            __sniperLayout.commit(i2, buffer);"));
  assert.ok(patched.includes("session.staticDedupEnabled = false; return;"));
  assert.throws(() => instrument(source + "\n"), /exact HyperFrames/);
});

function domFixture() {
  const style = { opacity: "1", display: "block", visibility: "visible", filter: "none",
    backdropFilter: "none", clipPath: "none", maskImage: "none", textShadow: "none", boxShadow: "none",
    mixBlendMode: "normal", perspective: "none", outlineStyle: "none", outlineWidth: "0px",
    textOverflow: "clip", webkitLineClamp: "none", overflowX: "visible", overflowY: "visible",
    clip: "auto", contain: "none", webkitTextStrokeWidth: "0px", transform: "none", content: "none" };
  const rect = { left: 20, top: 30, right: 200, bottom: 80 };
  const root = { id: "ag-root", dataset: { compositionId: "agenda-slide", sniperLayout: "caption-safe-upper-v1" },
    style: { ...style }, getBoundingClientRect: () => ({ left: 0, top: 0, right: 1920, bottom: 1080 }),
    querySelector: () => null };
  const canvas = () => ({ style: { ...style, overflowX: "hidden", overflowY: "hidden" },
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 1920, bottom: 1080 }),
    clientWidth: 1920, clientHeight: 1080, scrollWidth: 1920, scrollHeight: 1080, scrollLeft: 0, scrollTop: 0 });
  const html = { ...canvas(), parentElement: null }, body = { ...canvas(), parentElement: html };
  root.parentElement = body;
  const row = { dataset: { slot: "1" }, style: { ...style }, parentElement: root };
  const nodes = [["ag-title", null, "title", "TEST"], ["ag-underline", null, "title-accent", ""],
    ["", "ag-chip", "step-1-marker", "1"], ["", "ag-title-row", "step-1-title", "TEST row"]].map(
    ([id, name, role, text]) => ({ id, style: { ...style }, dataset: { sniperProtectedRole: role },
      textContent: text, parentElement: root, classList: { contains: (value) => value === name },
      closest: () => row, contains(node) { return node.parentElement === this; },
      getBoundingClientRect: () => ({ ...rect }), scrollWidth: 180, clientWidth: 180, scrollHeight: 50, clientHeight: 50 }));
  const textNodes = nodes.map((node) => ({ textContent: node.textContent, parentElement: node }));
  root.querySelectorAll = (selector) => selector === ".ag-row" ? [row] : nodes;
  const document = { body, documentElement: html, getElementById: () => root, fonts: { status: "loaded" }, getAnimations: () => [],
    createTreeWalker: () => { let i = 0; return { nextNode: () => textNodes[i++] || null }; },
    createRange: () => ({ selectNodeContents() {}, getClientRects: () => [{ ...rect }] }) };
  const context = { document, NodeFilter: { SHOW_TEXT: 4 }, innerWidth: 1920, innerHeight: 1080,
    devicePixelRatio: 1, getComputedStyle: (node, pseudo) => pseudo ? { content: "none" } : node.style };
  return { root, body, html, nodes, textNodes, context };
}

const inspect = (fixture) => JSON.parse(JSON.stringify(vm.runInNewContext(browserExpression(), fixture.context)));

test("actual DOM-derived sparse four-role inventory, including nonlexical accent", () => {
  const value = inspect(domFixture());
  assert.deepEqual(value.roles.map((row) => row.id), ["step-1-marker", "step-1-title", "title", "title-accent"]);
  assert.deepEqual(value.issues, []);
});

test("missing/mismatched role attribute cannot hide actual DOM text", () => {
  const fixture = domFixture();
  fixture.nodes[0].dataset.sniperProtectedRole = "other";
  assert.throws(() => inspect(fixture), /protected role differs/);
});

test("extra actual lexical text is not covered by caller role declarations", () => {
  const fixture = domFixture();
  fixture.textNodes.push({ textContent: "unprotected label", parentElement: fixture.root });
  assert.throws(() => inspect(fixture), /unprotected actual DOM text/);
});

test("shadow/filter/ellipsis/clipping remain explicit unsupported observations", () => {
  for (const change of [{ textShadow: "rgb(0,0,0) 0px 0px 10px" }, { filter: "blur(2px)" },
    { textOverflow: "ellipsis" }, { overflowX: "hidden" }]) {
    const fixture = domFixture();
    Object.assign(fixture.nodes[0].style, change);
    assert.ok(inspect(fixture).issues.length > 0);
  }
});

test("portrait, missing fonts, foreign layout and unsupported painted DOM fail", () => {
  for (const change of [(f) => { f.context.innerWidth = 1080; },
    (f) => { f.context.document.fonts.status = "loading"; },
    (f) => { f.root.dataset.sniperLayout = "full-canvas"; },
    (f) => { f.root.querySelector = () => ({}); }]) {
    const fixture = domFixture(); change(fixture);
    assert.throws(() => inspect(fixture));
  }
});

test("actual fullcanvas body/html clipping is bounded, not blindly exempted", () => {
  assert.deepEqual(inspect(domFixture()).issues, []);
  for (const change of [(f) => { f.body.clientWidth = 1800; },
    (f) => { f.html.scrollTop = 1; }, (f) => { f.body.scrollWidth = 1921; },
    (f) => { f.html.style.overflowX = "scroll"; }]) {
    const fixture = domFixture(); change(fixture);
    assert.ok(inspect(fixture).issues.includes("unsupported-clipping"));
  }
});

test("outer opacity and unsupported paint effects cannot be ignored", () => {
  const hidden = domFixture(); hidden.body.style.opacity = "0";
  assert.ok(inspect(hidden).roles.every((role) => role.opacity === 0 && role.bounds === null));
  for (const changes of [{ filter: "blur(2px)" }, { boxShadow: "black 0px 0px 3px" },
    { clipPath: "inset(1px)" }]) {
    const fixture = domFixture(); Object.assign(fixture.html.style, changes);
    assert.ok(inspect(fixture).issues.length > 0);
  }
  const transform = domFixture(); transform.body.style.transform = "matrix(1,0,0,1,0,0)";
  transform.context.DOMMatrixReadOnly = class { constructor() { Object.assign(this, { is2D: true, a: 1, b: 0, c: 0, d: 1 }); } };
  assert.ok(inspect(transform).issues.includes("unsupported-outer-transform"));
});

test("unknown wrapper ancestors are not accepted as the native profile", () => {
  const fixture = domFixture(); fixture.root.parentElement = { parentElement: fixture.body };
  assert.throws(() => inspect(fixture), /outer DOM ancestry/);
});

function pipelineFixture() {
  const fixture = domFixture(), [first, second, link] = fixture.nodes;
  fixture.nodes.splice(3, 1);
  fixture.root.id = "npl-root"; fixture.root.dataset.compositionId = "module-pipeline";
  fixture.root.classList = { contains: () => false };
  for (const [node, role, text] of [[first, "node-1", "01TEST one"], [second, "node-2", "02TEST two"], [link, "connector-1", ""]]) {
    node.id = ""; node.dataset.sniperProtectedRole = role; node.textContent = text;
    node.classList = { contains: (name) => name === (node === link ? "npl-native-link" : "npl-node") };
  }
  first.parentElement = { style: { ...first.style }, parentElement: fixture.root };
  second.parentElement = { style: { ...second.style }, parentElement: fixture.root };
  link.parentElement = first.parentElement;
  fixture.textNodes.splice(0, fixture.textNodes.length, ...fixture.nodes.map((node) => ({ textContent: node.textContent, parentElement: node })));
  fixture.root.querySelectorAll = (selector) => {
    if (selector === "#npl-headline > .line") return [];
    if (selector === "#npl-chain > .npl-native-cell > .npl-node") return [first, second];
    if (selector === ".npl-native-link") return [link];
    return fixture.nodes;
  };
  return fixture;
}

const inspectPipeline = (fixture) => JSON.parse(JSON.stringify(vm.runInNewContext(browserExpression(PIPELINE_POLICY), fixture.context)));

test("separate pipeline policy cannot be selected by an agenda request or unknown token", () => {
  const value = { ...request(), profile: PIPELINE_POLICY, composition: "compositions/module-pipeline.html" };
  assert.deepEqual(parseRequest(encoded(value)).value, value);
  for (const patch of [{ profile: POLICY }, { composition: "compositions/agenda-slide.html" }, { profile: "__proto__" }, { profile: {} }]) {
    assert.throws(() => parseRequest(encoded({ ...value, ...patch })));
  }
  assert.throws(() => browserExpression("unknown"));
  assert.throws(() => inspectPipeline(domFixture()));
  assert.throws(() => inspect(pipelineFixture()));
});

test("native pipeline protects every actual node and real connector, not supplied role labels alone", () => {
  const value = inspectPipeline(pipelineFixture());
  assert.deepEqual(value.roles.map((row) => row.id), ["connector-1", "node-1", "node-2"]);
  assert.deepEqual(value.issues, []);
  const wrong = pipelineFixture(); wrong.nodes[2].dataset.sniperProtectedRole = "connector-2";
  assert.throws(() => inspectPipeline(wrong), /protected role differs/);
  const presenter = pipelineFixture(); presenter.root.classList.contains = () => true;
  assert.throws(() => inspectPipeline(presenter), /presenter/);
});

test("empty pseudo-elements cannot hide unmeasured generated paint in either policy", () => {
  for (const [factory, inspectValue] of [[domFixture, inspect], [pipelineFixture, inspectPipeline]]) {
    const fixture = factory(), computed = fixture.context.getComputedStyle;
    fixture.context.getComputedStyle = (node, pseudo) => pseudo ? { content: '""' } : computed(node);
    assert.ok(inspectValue(fixture).issues.includes("unsupported-generated-content"));
  }
});
