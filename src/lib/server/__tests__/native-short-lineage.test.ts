/** TEST-only synthetic projects: logical clip identity and parent binding, never reuse or media proof. */
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { canonicalJson, fileSha256 } from "../auto-edit-hash";
import { assertNativeShortLineage } from "../native-short-lineage";
import { readNativeShortProject, writeNativeShortProject } from "../native-short-project";
import { nativeShortFixture } from "./_native-short-project-fixture";
import { executeNativeShortCommand } from "../../../../scripts/producer/native-short";

function manifest(directory: string) {
  return JSON.parse(readFileSync(path.join(directory, "PROJECT-MANIFEST.json"), "utf8"));
}

test("a root build gets a fresh clip; a verified rebuild inherits it and binds its parent bytes", () => {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-lineage-")));
  try {
    const input = nativeShortFixture(directory);
    const first = writeNativeShortProject(input, path.join(directory, "native-v1"));
    const other = writeNativeShortProject(input, path.join(directory, "other-root"));
    const root = assertNativeShortLineage(first.manifest.lineage);
    assert.equal(root.generation, 0); assert.equal(root.parent, null);
    assert.notEqual(assertNativeShortLineage(other.manifest.lineage).clipId, root.clipId);
    const second = writeNativeShortProject(input, path.join(directory, "native-v2"), {}, { parent: first.directory });
    const child = assertNativeShortLineage(second.manifest.lineage);
    assert.equal(child.clipId, root.clipId); assert.equal(child.generation, 1);
    assert.deepEqual(child.parent, { path: first.directory, projectHash: first.manifest.projectHash, clipId: root.clipId,
      manifestSha256: fileSha256(path.join(first.directory, "PROJECT-MANIFEST.json")), generation: 0 });
    assert.deepEqual(readNativeShortProject(second.directory), input);
    const third = writeNativeShortProject(input, path.join(directory, "native-v3"), {}, { parent: second.directory });
    assert.equal(assertNativeShortLineage(third.manifest.lineage).parent?.path, second.directory);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test("a changed or lineage-free parent cannot be adopted", async () => {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-lineage-")));
  try {
    const input = nativeShortFixture(directory);
    const parent = writeNativeShortProject(input, path.join(directory, "parent"));
    writeFileSync(path.join(parent.directory, input.canvas.sourceFile), "TEST changed staged source");
    assert.throws(() => writeNativeShortProject(input, path.join(directory, "child"), {}, { parent: parent.directory }), /changed/);
    const legacy = writeNativeShortProject(input, path.join(directory, "legacy"));
    const stored = manifest(legacy.directory); delete stored.lineage;
    writeFileSync(path.join(legacy.directory, "PROJECT-MANIFEST.json"), canonicalJson(stored));
    assert.deepEqual(readNativeShortProject(legacy.directory), input);
    assert.throws(() => writeNativeShortProject(input, path.join(directory, "orphan"), {}, { parent: legacy.directory }), /no clip lineage/);
    await assert.rejects(executeNativeShortCommand(["build", "plan.json", "dest", "--parent"]), /Usage/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test("recorded lineage rejects forged, relative, cross-clip and non-successor parents", () => {
  const clipId = "a".repeat(32), parent = { path: "/TEST/native-v1", projectHash: "b".repeat(64),
    manifestSha256: "c".repeat(64), clipId, generation: 0 };
  assert.doesNotThrow(() => assertNativeShortLineage({ schemaVersion: 1, clipId, generation: 1, parent }));
  for (const bad of [{ ...parent, path: "native-v1" }, { ...parent, clipId: "d".repeat(32) }, { ...parent, generation: 1 },
    { ...parent, extra: true }, { ...parent, manifestSha256: "short" }]) {
    assert.throws(() => assertNativeShortLineage({ schemaVersion: 1, clipId, generation: 1, parent: bad }), /lineage/);
  }
  assert.throws(() => assertNativeShortLineage({ schemaVersion: 1, clipId, generation: 1, parent: null }), /generation 0/);
  assert.throws(() => assertNativeShortLineage({ schemaVersion: 1, clipId: "Z", generation: 0, parent: null }), /clip identity/);
});
