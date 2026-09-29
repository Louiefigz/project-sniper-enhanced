/** Reveal probe project (P2-03, M-068): a synthetic plan JSON; the vendored catalog is read, never changed. */
import assert from "node:assert/strict";
import fs, { mkdirSync, mkdtempSync, readdirSync, readFileSync, realpathSync, rmSync, writeFileSync, existsSync, symlinkSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { VISUAL_SOURCE_POLICY } from "@/lib/producer/visual-source-policy";
import { canonicalJson, fileSha256 } from "../auto-edit-hash";
import { buildNativeCanvas, centeredNativeCaptionView } from "../native-short-composition";
import type { NativeShortProjectInput } from "../native-short-project";
import type { NativeAssetBinding } from "../native-short-strategy";
import { writeNativeRevealProbeProject } from "../native-reveal-probe-project";

const ID = "sn-numbers-q1";
const FILE = "compositions/numbers-q1.html";
const POLICY = VISUAL_SOURCE_POLICY.integrated["count-up"];
/** The authored mount: exact timing, variable values and host style, as the probe must keep them. */
const MOUNT = `<div class="clip" id="${ID}" data-composition-id="${ID}" data-composition-src="${FILE}" `
  + `data-variable-values='{"laterAt":0.8}' data-start="0.4" data-duration="1.2" data-track-index="3" `
  + `style="position:absolute;inset:0;width:1080px;height:1920px"></div>`;
const CSS = `<style>#${ID}{z-index:4}</style>`;
/** Hidden by CSS; `laterAt` reveals it (0.8 s, local frame 20 at 25 fps). */
const LATER = `<div data-hf-id="hf-later" class="stat later" data-hf-reveal="laterAt">Later</div>`;
const HIDE = `#${ID} .later{opacity:0}@font-face{font-family:Brand;src:url('../assets/Brand.woff2')}`;
const SHORTS_ONLY = /^Error: reveal probe supports native Shorts only$/u;

/** A catalog adaptation in the toolkit shape (variables on <html>, content in <template>); TEST bytes only. */
function composition(style: string, body = LATER): string {
  const variables = JSON.stringify([{ id: "laterAt", type: "number", label: "laterAt", default: 0.6 }]).replaceAll('"', "&quot;");
  return `<!doctype html><html lang="en" data-composition-id="${ID}" data-composition-variables="${variables}">`
    + `<head><meta charset="UTF-8"><title>TEST</title></head><body><template><style>${style}</style>`
    + `<div data-hf-id="hf-numbers" id="${ID}" data-composition-id="${ID}" data-width="1080" data-height="1920" data-duration="1.2">`
    + `${body}</div><script src="../assets/gsap.min.js"></script></template></body></html>`;
}

interface Fixture { directory: string; plan: NativeShortProjectInput; file: string }

/** A TEST file bound as a plan asset. */
function asset(directory: string, name: string, file: string, role: NativeAssetBinding["role"]): NativeAssetBinding {
  const source = path.join(directory, name);
  writeFileSync(source, `TEST-only synthetic bytes ${name}`);
  return { path: source, sha256: fileSha256(source)!, file, role };
}

/** A canvas `buildNativeCanvas` accepts (footage, captions), bound TEST assets and one catalog mount. */
function fixture(style = HIDE, body = LATER): Fixture {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-reveal-project-")));
  const source = asset(directory, "source.mp4", "", "source");
  source.file = `assets/${source.sha256}.mp4`;
  const assets = [source, asset(directory, "gsap.min.js", "assets/gsap.min.js", "runtime"),
    asset(directory, "Inter-Bold.ttf", "assets/Inter-Bold.ttf", "runtime"),
    asset(directory, "Inter-Regular.ttf", "assets/Inter-Regular.ttf", "runtime"), asset(directory, "Brand.woff2", "assets/Brand.woff2", "image")];
  const adapted = path.join(directory, "numbers-q1.html");
  writeFileSync(adapted, composition(style, body));
  const plan = { schemaVersion: 1, assets,
    catalogFiles: [{ file: FILE, path: adapted, sha256: fileSha256(adapted)!, catalogId: "count-up", sourceSha256: POLICY.upstreamSha256 }],
    extension: { markup: MOUNT, css: CSS, motion: "" },
    canvas: { title: "TEST reveal probe plan", frameRate: "25/1", totalFrames: 50, background: "#0b0e12",
      sourceSize: { w: 1920, h: 1080 }, sourceFile: source.file, cuts: [{ start: 0, end: 2, speed: 1 }],
      segments: [{ startFrame: 0, endFrameExclusive: 50 }],
      occurrences: [[0, 0, 0, 0, 20, "Test", 0], [1, 0, 1, 20, 45, "words.", 0]], captionGroups: [[0], [1]],
      pictureViews: [{ startFrame: 0, endFrame: 50, crop: [500, 0, 607.5, 1080], box: [0, 0, 1080, 1920] }],
      captionViews: [centeredNativeCaptionView({ startFrame: 0, endFrame: 50, top: 1000 })], text: [], shapes: [], motion: [] },
  } as unknown as NativeShortProjectInput;
  return { directory, plan, file: path.join(directory, "plan.json") };
}

/** Save the plan and write its probe project into `<directory>/probe`. */
function write(value: Fixture) {
  writeFileSync(value.file, JSON.stringify(value.plan));
  return writeNativeRevealProbeProject(value.file, path.join(value.directory, "probe"));
}

function withFixture(run: (value: Fixture) => void, style = HIDE, body = LATER): void {
  const value = fixture(style, body);
  try { run(value); } finally { rmSync(value.directory, { recursive: true, force: true }); }
}

/** `change` makes the plan refused with `message`, and no probe folder is created. */
function refused(value: Fixture, change: () => void, message: RegExp): void {
  const saved = structuredClone(value.plan);
  change();
  assert.throws(() => write(value), message);
  assert.equal(existsSync(path.join(value.directory, "probe")), false);
  value.plan = saved;
}

test("keeps catalog mount markup exactly", () => withFixture((value) => {
  const manifest = write(value), probe = path.join(value.directory, "probe");
  const html = readFileSync(path.join(probe, "index.html"), "utf8");
  assert.ok(html.includes(`<div id="native-canvas" data-hf-id="hf-native-canvas" data-composition-id="native-canvas" data-width="1080" data-height="1920" data-fps="25" data-duration="2">\n${MOUNT}</div>`));
  assert.ok(html.includes(`</style>${CSS}</head>`));
  assert.equal(readFileSync(path.join(probe, FILE), "utf8"), readFileSync(value.plan.catalogFiles![0].path, "utf8"));
  assert.deepEqual(manifest, { schemaVersion: 1, source: { plan: value.file, sha256: fileSha256(value.file) }, rate: 25, totalFrames: 50,
    mounts: [{ id: ID, compositionId: ID, file: FILE, start: 0.4, duration: 1.2, variables: { laterAt: 0.8 }, first: 10, endExclusive: 40 }],
    declarations: [{ mountId: ID, file: FILE, hfId: "hf-later", cue: "laterAt", cueSeconds: 0.8, cueLocalFrame: 20 }] });
  assert.equal(readFileSync(path.join(probe, "REVEAL-PROBE.json"), "utf8"), canonicalJson(manifest));
  assert.equal(readFileSync(path.join(probe, "SHORT-PROJECT.json"), "utf8"), '{"canvas":{"frameRate":"25/1","totalFrames":50},"schemaVersion":1}');
}));

test("omits footage and captions", () => withFixture((value) => {
  const built = buildNativeCanvas(value.plan.canvas);
  assert.ok(built.includes("<video") && built.includes('id="caption-0-0"'));  // the plan itself has both
  write(value);
  const probe = path.join(value.directory, "probe"), html = readFileSync(path.join(probe, "index.html"), "utf8");
  for (const absent of ["<video", "<audio", "caption-", "native-title-card", value.plan.canvas.sourceFile]) {
    assert.ok(!html.includes(absent), absent);
  }
  assert.match(html, /<script>const tl=gsap\.timeline\(\{paused:true\}\);\ntl\.to\(\{\}, \{duration:2\}, 0\);/u);
  assert.deepEqual(readdirSync(path.join(probe, "assets")).sort(), ["Brand.woff2", "Inter-Bold.ttf", "gsap.min.js"]);
  assert.deepEqual(readdirSync(probe).sort(), ["REVEAL-PROBE.json", "SHORT-PROJECT.json", "assets", "compositions", "index.html"]);
}));

test("the probe root is the build's own skeleton", () => withFixture((value) => {
  value.plan.extension!.css = "";
  write(value);
  const probe = readFileSync(path.join(value.directory, "probe/index.html"), "utf8").split("\n");
  const built = buildNativeCanvas(value.plan.canvas).split("\n");
  assert.equal(probe[0], built[0].replace("TEST reveal probe plan", "Native reveal probe"));
  assert.deepEqual([probe[1], probe[2], probe[3], probe.at(-2)], [built[1], built[2], built[3], built.at(-2)]);
}));

test("refuses an existing destination", () => withFixture((value) => {
  mkdirSync(path.join(value.directory, "probe"));
  assert.throws(() => write(value), /EEXIST/u);
  assert.deepEqual(readdirSync(path.join(value.directory, "probe")), []);
  value.plan.assets = value.plan.assets.filter(row => row.file !== "assets/gsap.min.js");
  writeFileSync(value.file, JSON.stringify(value.plan));
  assert.throws(() => writeNativeRevealProbeProject(value.file, path.join(value.directory, "other")), /pinned GSAP/u);
  assert.equal(existsSync(path.join(value.directory, "other")), false);
}));

test("stages catalog files through nativeCatalogFiles", () => withFixture((value) => {
  const upstream = path.join(process.cwd(), POLICY.upstreamPath), row = value.plan.catalogFiles![0];
  refused(value, () => { value.plan.catalogFiles![0].sha256 = "0".repeat(64); }, /Catalog implementation is missing, changed or retired/u);
  refused(value, () => { value.plan.catalogFiles![0].sourceSha256 = "0".repeat(64); }, /Catalog upstream source changed/u);
  refused(value, () => { value.plan.extension!.markup = MOUNT + MOUNT.replaceAll(FILE, "compositions/other.html").replace(`id="${ID}"`, 'id="sn-other"'); },
    /not a staged catalog file/u);
  refused(value, () => { value.plan.extension!.markup = MOUNT.replace('data-start="0.4"', 'data-start="1.6"'); }, /no exact frame range inside the Short/u);
  refused(value, () => { value.plan.catalogFiles = []; value.plan.extension!.markup = ""; }, /at least one catalog mount/u);
  refused(value, () => { writeFileSync(row.path, composition(`#${ID} .later{opacity:1}`)); }, /Catalog implementation is missing, changed or retired/u);
  assert.equal(fileSha256(upstream), POLICY.upstreamSha256);  // read for its identity, never changed
}));

test("refuses a mount whose snapped range is empty", () => withFixture((value) => {
  refused(value, () => { value.plan.extension!.markup = MOUNT.replace('data-duration="1.2"', 'data-duration="0.01"'); },
    /Catalog mount sn-numbers-q1 has no exact frame range inside the Short/u);
}, HIDE, "<div>Plain</div>"));

test("a plan JSON passes the build's own rules, refused with the build's text (X128 m2)", () => withFixture((value) => {
  const gsap = value.plan.assets[1];
  refused(value, () => { value.plan.extension!.markup += "<script>alert(1)</script>"; }, /unsupported script, audio or frame element/u);
  refused(value, () => { value.plan.extension!.markup += '<div id="dup"></div><div id="dup"></div>'; }, /duplicates a shared element identity/u);
  refused(value, () => { value.plan.extension!.markup += '<img src="https://example.com/x.png">'; }, /must use staged local assets/u);
  const extra = path.join(value.directory, "extra.html");
  writeFileSync(extra, composition(HIDE, "<div>Extra</div>"));
  refused(value, () => { value.plan.catalogFiles!.push({ file: "compositions/extra.html", path: extra, sha256: fileSha256(extra)!,
    catalogId: "count-up", sourceSha256: POLICY.upstreamSha256 }); }, /must be mounted in the authored scene/u);
  const link = path.join(value.directory, "gsap-link.js");
  symlinkSync(gsap.path, link);  // a link to the TEST gsap bytes only
  refused(value, () => { value.plan.assets[1] = { ...gsap, path: link }; }, /not canonical: assets\/gsap\.min\.js$/u);
  refused(value, () => { value.plan.assets[1] = { ...gsap, path: path.relative(process.cwd(), gsap.path) }; },
    /not canonical: assets\/gsap\.min\.js$/u);
  refused(value, () => { value.plan.assets[1] = { ...gsap, path: value.directory }; }, /not canonical: assets\/gsap\.min\.js$/u);
  refused(value, () => { value.plan.canvas.background = "red"; }, /Native color must be exact hex or transparent/u);
}));

test("refuses an unsafe font file name with the build's text", () => withFixture((value) => {
  const odd = asset(value.directory, "odd.ttf", "assets/My Font$&.ttf", "image");
  refused(value, () => { value.plan.assets.push(odd); }, /not canonical: assets\/My Font\$&\.ttf$/u);
}, `${HIDE}@font-face{font-family:Odd;src:url('../assets/My Font$&.ttf')}`));

test("an asset path outside assets/ is never staged", () => withFixture((value) => {
  value.plan.assets.push(asset(value.directory, "escape.ttf", "assets/../escape.ttf", "image"));
  write(value);
  assert.deepEqual(readdirSync(path.join(value.directory, "probe", "assets")).sort(), ["Brand.woff2", "Inter-Bold.ttf", "gsap.min.js"]);
  assert.equal(existsSync(path.join(value.directory, "probe", "escape.ttf")), false);
}, `${HIDE}@font-face{font-family:Out;src:url('../assets/../escape.ttf')}`));

test("an asset that changes while staging is refused", (t) => withFixture((value) => {
  const copy = fs.copyFileSync;
  t.mock.method(fs, "copyFileSync", (from: string, to: string, mode: number) => {
    copy(from, to, mode);
    fs.appendFileSync(to, "TEST changed after the copy");
  });
  assert.throws(() => write(value), /Reveal probe asset changed while staging: assets\/gsap\.min\.js/u);
}));

test("refuses a Long project, a LONG-PROJECT.json and a Long canvas (P2:1157)", () => withFixture((value) => {
  const long = path.join(value.directory, "long");
  mkdirSync(long);
  writeFileSync(path.join(long, "LONG-PROJECT.json"), JSON.stringify(value.plan));
  assert.throws(() => writeNativeRevealProbeProject(long, path.join(value.directory, "probe")), SHORTS_ONLY);
  const named = path.join(value.directory, "LONG-PROJECT.json");
  writeFileSync(named, JSON.stringify(value.plan));
  assert.throws(() => writeNativeRevealProbeProject(named, path.join(value.directory, "probe")), SHORTS_ONLY);
  refused(value, () => { Object.assign(value.plan.canvas, { width: 1920, height: 1080 }); }, SHORTS_ONLY);
}));

test("refuses extension.motion by name until the plan rules on root motion (X128 m3)", () => withFixture((value) => {
  refused(value, () => { value.plan.extension!.motion = `tl.set("#${ID}",{opacity:1},0);`; }, /reveal probe refuses extension\.motion/u);
}));

test("the static rule accepts the two X72 runtime cases, so the probe carries their declarations", () => {
  const cases = [`#${ID} .later{opacity:0;animation:pop .5s linear 0s both}@keyframes pop{from{opacity:1}to{opacity:0}}`,
    `#${ID} .later{opacity:0}#${ID} .stat{all:unset}`];
  for (const style of cases) {
    withFixture((value) => {
      assert.deepEqual(write(value).declarations.map(row => [row.hfId, row.cueLocalFrame]), [["hf-later", 20]]);
      assert.ok(readFileSync(path.join(value.directory, "probe", FILE), "utf8").includes(style));
    }, style);
  }
});
