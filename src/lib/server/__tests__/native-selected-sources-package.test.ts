/** Explicit real-package tests; set SNIPER_SELECTED_TEST_PROJECT to a prepared test project. */
import assert from "node:assert/strict";
import { constants, copyFileSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, unlinkSync, writeFileSync } from "node:fs";
import path from "node:path";
import os from "node:os";
import { test } from "node:test";
import { canonicalJson, canonicalJsonSha256, fileSha256 } from "../auto-edit-hash";
import { readNativeShortProject } from "../native-short-project";

const donor = process.env.SNIPER_SELECTED_TEST_PROJECT;

function copyProject() {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "selected-package-test-")));
  const manifest = JSON.parse(readFileSync(path.join(donor!, "PROJECT-MANIFEST.json"), "utf8"));
  for (const file of [...manifest.files.map((row: { file: string }) => row.file), "PROJECT-MANIFEST.json"]) {
    mkdirSync(path.dirname(path.join(root, file)), { recursive: true });
    copyFileSync(path.join(donor!, file), path.join(root, file), constants.COPYFILE_EXCL | constants.COPYFILE_FICLONE);
  }
  return { root, manifest, cleanup: () => rmSync(root, { recursive: true, force: true }) };
}

function rehash(f: ReturnType<typeof copyProject>, file: string, content: string) {
  writeFileSync(path.join(f.root, file), content);
  f.manifest.files.find((row: { file: string }) => row.file === file).sha256 = fileSha256(path.join(f.root, file));
  writeFileSync(path.join(f.root, "PROJECT-MANIFEST.json"), canonicalJson(f.manifest));
}

test("real completed package cold-reads and stages no whole-recording media", { skip: !donor }, () => {
  const input = readNativeShortProject(path.resolve(donor!));
  const manifest = JSON.parse(readFileSync(path.join(donor!, "PROJECT-MANIFEST.json"), "utf8"));
  assert.ok(input.preparedSources);
  assert.ok(!manifest.files.some((row: { file: string }) => row.file === input.canvas.sourceFile));
});

test("a rehashed executable offset cannot override the sealed source mapping", { skip: !donor }, () => {
  const f = copyProject();
  try {
    const html = readFileSync(path.join(f.root, "index.html"), "utf8").replace(/data-media-start="[^"]*"/u, 'data-media-start="0"');
    rehash(f, "index.html", html);
    assert.throws(() => readNativeShortProject(f.root), /executable differs/);
  } finally { f.cleanup(); }
});

test("stripping prepared mapping proof cannot make a partial project current", { skip: !donor }, () => {
  const f = copyProject();
  try {
    unlinkSync(path.join(f.root, "PREPARED-SOURCES.json"));
    f.manifest.files = f.manifest.files.filter((row: { file: string }) => row.file !== "PREPARED-SOURCES.json");
    writeFileSync(path.join(f.root, "PROJECT-MANIFEST.json"), canonicalJson(f.manifest));
    assert.throws(() => readNativeShortProject(f.root), /omits or duplicates/);
  } finally { f.cleanup(); }
});

test("rehashed plan and manifest cannot admit a changed package receipt", { skip: !donor }, () => {
  const f = copyProject();
  try {
    const input = JSON.parse(readFileSync(path.join(f.root, "SHORT-PROJECT.json"), "utf8"));
    input.preparedSources.sha256 = "0".repeat(64);
    f.manifest.projectHash = canonicalJsonSha256(input);
    rehash(f, "SHORT-PROJECT.json", canonicalJson(input));
    assert.throws(() => readNativeShortProject(f.root), /binding changed/);
  } finally { f.cleanup(); }
});
