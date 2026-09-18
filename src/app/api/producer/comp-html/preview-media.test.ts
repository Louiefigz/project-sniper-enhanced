import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import vm from "node:vm";
import { test } from "node:test";
import { createHash } from "node:crypto";
import { NextRequest } from "next/server";
import { MOTION_DIR, readPreviewAsset } from "./preview-assets";
import { addMediaAliases, assertSafeSvg, buildMediaMap, imageType, type MediaMap } from "./preview-media";
import { mediaShim } from "./preview-media-shim";
import { GET } from "./route";

function source(kind: string): string {
  return fs.readFileSync(path.join(MOTION_DIR, "compositions", `${kind}.html`), "utf8");
}

test("exact declared icon selectors retain aliases, extensions, and source byte identity", () => {
  const map = buildMediaMap(source("icon-badge-wide"), "icon-badge-wide", { icon1: "codex", icon2: "codex.svg", icon3: "" });
  assert.deepEqual(Object.keys(map).sort(), ["/icons/codex", "/icons/codex.svg"]);
  assert.deepEqual(map["/icons/codex"], map["/icons/codex.svg"]);
  const bytes = fs.readFileSync(path.join(MOTION_DIR, "icons/codex.svg"));
  assert.equal(map["/icons/codex"].sha, createHash("sha256").update(bytes).digest("hex"));
  assert.deepEqual(Buffer.from(map["/icons/codex"].data.split(",")[1], "base64"), bytes);
  assert.equal(Object.keys(buildMediaMap(source("statement-card"), "statement-card", { text: "assets/private.png", notAnAsset: "../private" })).length, 0);
});

test("audited stroke-draw empty-content fallback embeds only its exact source sample", () => {
  assert.deepEqual(Object.keys(buildMediaMap(source("stroke-draw-badge"), "stroke-draw-badge", {})).sort(), ["/icons/youtube", "/icons/youtube.svg"]);
  assert.throws(() => buildMediaMap(source("stroke-draw-badge").replace('icon: "youtube", label: "Subscribe"', 'icon: "other", label: "Subscribe"'), "stroke-draw-badge", {}), /sample changed/u);
});

test("missing, traversing, encoded, external, whitespace, and unsupported selectors fail explicitly", async () => {
  for (const icon of ["../package.json", "../icons/codex.svg", "%2e%2e/foo.svg", "codex.svg?x", "codex.svg#x", " nested.svg", "/icons/codex.svg", "https://example.test/icon.svg", "missing.svg", "codex.png", "a\\b.svg"]) {
    assert.throws(() => buildMediaMap(source("statement-card"), "statement-card", { iconFile: icon }), /Preview/u, icon);
  }
  for (const image of ["assets/../package.json", "assets/%2e%2e/other.png", "assets/missing.png", "assets/test.svg", "assets/test.mp4", "https://example.test/a.png"]) {
    const query = new URLSearchParams({ kind: "ui-focus-zoom", spec: JSON.stringify({ image }) });
    const response = await GET(new NextRequest(`http://localhost/api/producer/comp-html?${query}`));
    assert.equal(response.status, 422, image);
    if (image.endsWith(".mp4")) assert.match((await response.json()).error, /video.*unsupported/u);
  }
});

test("image signatures and conservative SVG subset reject mislabeled bytes and executable/external XML", () => {
  assert.equal(imageType("a.png", Buffer.from("89504e470d0a1a0a", "hex")), "image/png");
  assert.equal(imageType("a.jpeg", Buffer.from("ffd8ff", "hex")), "image/jpeg");
  assert.equal(imageType("a.webp", Buffer.from("RIFFxxxxWEBP")), "image/webp");
  assert.throws(() => imageType("a.png", Buffer.from("not png")), /real PNG/u);
  assert.throws(() => imageType("a.svg", Buffer.from("<svg/>")), /media SVG/u);
  assert.doesNotThrow(() => assertSafeSvg(Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="a"/></defs><path fill="url(#a)" d="M0 0"/></svg>')));
  for (const unsafe of ['<!DOCTYPE svg><svg/>', '<svg><script/></svg>', '<svg onload="alert(1)"/>', '<svg><foreignObject/></svg>', '<svg><image href="https://example.test"/></svg>', '<svg><use href="https://example.test/a.svg#x"/></svg>', '<svg><use href=bad/></svg>', '<svg style="fill:red"/>', '<svg xml:base="https://example.test"/>', '<svg><path fill="url(data:text/html,x)"/></svg>', '<svg><use href="&#104;ttps://example.test"/></svg>']) {
    assert.throws(() => assertSafeSvg(Buffer.from(unsafe)), /Preview icon/u, unsafe);
  }
});

test("per-file/combined byte caps and alias collisions fail closed without replacing mapped data", () => {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sniper-media-size-")));
  try {
    fs.writeFileSync(path.join(root, "large.png"), Buffer.alloc(4 * 1024 * 1024 + 1));
    assert.throws(() => readPreviewAsset(root, "large.png"), /4 MiB/u);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
  const map: MediaMap = Object.create(null) as MediaMap;
  const first = { data: "fixture", sha: "first", bytes: 4 * 1024 * 1024 };
  addMediaAliases(map, ["/icons/a.svg", "/icons/a"], first);
  assert.throws(() => addMediaAliases(map, ["/icons/a.svg"], { ...first, sha: "different" }), /collision/u);
  assert.equal(map["/icons/a.svg"], first);
  addMediaAliases(map, ["/icons/b.svg"], { ...first, sha: "second" });
  assert.throws(() => addMediaAliases(map, ["/icons/c.svg"], { ...first, sha: "third", bytes: 1 }), /8 MiB/u);
  assert.equal(map["/icons/c.svg"], undefined);
});

test("frame adapter resolves only exact image/SVG-XHR reads and preserves sync flags and unrelated APIs", () => {
  const map = buildMediaMap(source("stroke-draw-badge"), "stroke-draw-badge", { icon: "youtube.svg" });
  class FakeImage { value = ""; get src() { return this.value; } set src(value: string) { this.value = value; } }
  class FakeXhr { args: unknown[] = []; open(...args: unknown[]) { this.args = args; } }
  const script = mediaShim(map).replace(/^<script[^>]*>|<\/script>$/gu, "");
  vm.runInNewContext(script, { HTMLImageElement: FakeImage, XMLHttpRequest: FakeXhr });
  const image = new FakeImage(); image.src = "/icons/youtube.svg";
  assert.equal(image.value, map["/icons/youtube.svg"].data);
  const xhr = new FakeXhr(); xhr.open("GET", "/icons/youtube.svg", false);
  assert.deepEqual(xhr.args, ["GET", map["/icons/youtube.svg"].data, false]);
  assert.throws(() => xhr.open("POST", "/icons/youtube.svg", false), /read-only/u);
  assert.throws(() => { image.src = "/icons/unmapped.svg"; }, /not embedded/u);
  assert.throws(() => xhr.open("GET", "/assets/unmapped.png", false), /not embedded/u);
  xhr.open("GET", "https://example.test/unrelated", true);
  assert.deepEqual(xhr.args, ["GET", "https://example.test/unrelated", true]);
  image.src = "data:image/png;base64,fixture";
  assert.equal(image.value, "data:image/png;base64,fixture");
});
