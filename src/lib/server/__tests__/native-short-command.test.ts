/** Thin native CLI dispatch/transport; no source probing, model, media or child process. */
import assert from "node:assert/strict";
import { linkSync, mkdtempSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { test, type TestContext } from "node:test";
import { executeNativeShortCommand, nativeShortCommandServices } from "../../../../scripts/producer/native-short";

function fixture(t: TestContext) {
  const directory = realpathSync(mkdtempSync(path.join(tmpdir(), "TEST-native-cli $() ")));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const file = path.join(directory, "visual's.json"), value = { candidateHash: "a".repeat(64), project: {}, assetResolutions: [] };
  const calls: unknown[] = [];
  t.mock.method(nativeShortCommandServices, "buildGuided", async (input: unknown) => {
    calls.push(input); return { status: "TEST-not-a-built-project", publicationApproved: false };
  });
  writeFileSync(file, JSON.stringify(value));
  return { directory, file, value, calls };
}

test("build-guided passes only producer directory and exact parsed visual plan to the leased service", async t => {
  const f = fixture(t);
  await executeNativeShortCommand(["build-guided", f.directory, f.file]);
  assert.deepEqual(f.calls, [{ dir: f.directory, visual: f.value }]);
  assert.match(JSON.stringify(await executeNativeShortCommand(["--help"])), /build-guided/);
});

test("guided command rejects extra arguments and authority overrides before dispatch", async t => {
  const f = fixture(t);
  for (const args of [["build-guided", f.directory], ["build-guided", f.directory, f.file, "--provider=anything"],
    ["build-guided", `${f.directory}\n`, f.file]]) await assert.rejects(executeNativeShortCommand(args));
  for (const key of ["deadlineMs", "provider", "dependencies", "destination", "approval"]) {
    writeFileSync(f.file, JSON.stringify({ ...f.value, [key]: true }));
    await assert.rejects(executeNativeShortCommand(["build-guided", f.directory, f.file]));
  }
  assert.deepEqual(f.calls, []);
});

test("guided command rejects duplicate keys, malformed UTF-8, excessive nesting and large files", async t => {
  const f = fixture(t);
  const invalid = ['{"candidateHash":"a","candidateHash":"b","project":{}}',
    Buffer.from([0xff]), "[".repeat(20) + "0" + "]".repeat(20), " ".repeat(128 * 1024 + 1)];
  for (const bytes of invalid) {
    writeFileSync(f.file, bytes);
    await assert.rejects(executeNativeShortCommand(["build-guided", f.directory, f.file]));
  }
  assert.deepEqual(f.calls, []);
});

test("guided command cannot consume symlinked or hard-linked visual request files", async t => {
  const f = fixture(t), alias = path.join(f.directory, "alias.json"), hardlink = path.join(f.directory, "hard.json");
  symlinkSync(f.file, alias);
  await assert.rejects(executeNativeShortCommand(["build-guided", f.directory, alias]));
  linkSync(f.file, hardlink);
  await assert.rejects(executeNativeShortCommand(["build-guided", f.directory, hardlink]));
  assert.deepEqual(f.calls, []);
});
