import assert from "node:assert/strict";
import { test } from "node:test";
import path from "node:path";
import { writeFileSync, symlinkSync, linkSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { executeProjectCommand, projectCommandServices } from "../../../../scripts/producer/guided-project";
import { bootstrapFixture } from "./_guided-project-bootstrap-fixture";

test("CLI dispatches the exact request only and status reuses the strong read-only path", async (t) => {
  const f = bootstrapFixture(t), file = path.join(f.root, "TEST request.json"), seen: unknown[] = [];
  writeFileSync(file, JSON.stringify(f.request));
  t.mock.method(projectCommandServices, "bootstrap", async (request: unknown) => { seen.push(request); return { state: "TEST" } as never; });
  t.mock.method(projectCommandServices, "canonicalDir", (dir: string) => { seen.push(dir); return dir; });
  t.mock.method(projectCommandServices, "status", (dir: string) => { seen.push(dir); return { state: "TEST read" } as never; });
  await executeProjectCommand(["bootstrap", file]); assert.deepEqual(seen, [f.request]);
  await executeProjectCommand(["status", f.root]); assert.deepEqual(seen, [f.request, f.root, f.root]);
});

test("CLI rejects malformed/duplicate/nonfinite/oversized/unsafe request before service or project reads", async (t) => {
  const f = bootstrapFixture(t), file = path.join(f.root, "TEST.json"); let calls = 0;
  for (const name of ["bootstrap", "status", "canonicalDir"] as const) {
    t.mock.method(projectCommandServices, name, () => { calls++; throw new Error("TEST forbidden"); });
  }
  const text = JSON.stringify(f.request);
  for (const raw of ["", "null", "{}\n{}", Buffer.from([255]), Buffer.alloc(131073, 32),
    text.replace('"schemaVersion":1', '"schemaVersion":2,"schemaVersion":1'),
    text.replace('"intent":{', '"intent":null,"\\u0069ntent":{'), '{"number":1e400}', "[".repeat(17) + "0" + "]".repeat(17)]) {
    writeFileSync(file, raw); await assert.rejects(executeProjectCommand(["bootstrap", file]));
  }
  writeFileSync(file, text);
  const linked = path.join(f.root, "TEST-link"), hard = path.join(f.root, "TEST-hard"), fifo = path.join(f.root, "TEST-fifo");
  symlinkSync(file, linked); linkSync(file, hard);
  assert.equal(spawnSync("mkfifo", [fifo], { timeout: 2000 }).status, 0);
  for (const input of [file, linked, hard, fifo, f.root]) await assert.rejects(executeProjectCommand(["bootstrap", input]));
  assert.equal(calls, 0);
});

test("CLI help/grammar never author intent, add attestations, select providers, resume or create a project", async (t) => {
  const f = bootstrapFixture(t); let calls = 0;
  for (const name of ["bootstrap", "status", "canonicalDir"] as const) {
    t.mock.method(projectCommandServices, name, () => { calls++; throw new Error("TEST forbidden"); });
  }
  const help = await executeProjectCommand(["--help"]);
  assert.match(JSON.stringify(help), /two independent|two.*critics/);
  assert.match(JSON.stringify(help), /No human watched\/listened/);
  for (const argv of [[], ["bootstrap"], ["resume", f.root], ["bootstrap", f.root, "--force"],
    ["status", f.root, "extra"], ["status", "bad\npath"]]) await assert.rejects(executeProjectCommand(argv));
  assert.equal(calls, 0);
});

test("actual command help starts with no UI server or provider and malformed invocation exits nonzero", () => {
  const script = "scripts/producer/guided-project.ts";
  const help = spawnSync(process.execPath, ["--import", "tsx", script, "--help"], { encoding: "utf8", timeout: 10000 });
  assert.equal(help.status, 0, help.stderr); assert.match(help.stdout, /new-only/);
  const bad = spawnSync(process.execPath, ["--import", "tsx", script, "resume"], { encoding: "utf8", timeout: 10000 });
  assert.equal(bad.status, 1); assert.equal(JSON.parse(bad.stderr).ok, false);
});
