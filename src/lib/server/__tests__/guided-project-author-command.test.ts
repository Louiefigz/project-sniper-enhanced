import assert from "node:assert/strict";
import path from "node:path";
import { test } from "node:test";
import { writeFileSync } from "node:fs";
import { executeProjectCommand, projectCommandServices } from "../../../../scripts/producer/guided-project";
import { authorFixture } from "./_guided-project-author-fixture";

test("author-cut CLI transports exact request and pre-read original time without provider or acceptance flags", async t => {
  const f = authorFixture(t), file = path.join(f.root, "TEST-author-request.json"), before = Date.now();
  writeFileSync(file, JSON.stringify(f.request)); let calls = 0;
  t.mock.method(projectCommandServices, "authorCut", async (request: unknown, started?: string) => {
    calls++; assert.deepEqual(request, f.request); assert.ok(started);
    assert.ok(Date.parse(started!) >= before && Date.parse(started!) <= Date.now());
    return { scope: "TEST stub; no process, approval, or render" } as never;
  });
  await executeProjectCommand(["author-cut", file]); assert.equal(calls, 1);
  await assert.rejects(executeProjectCommand(["bootstrap", file]), /does not match/); assert.equal(calls, 1);
  const help = JSON.stringify(await executeProjectCommand(["--help"]));
  assert.match(help, /120-minute preparation/); assert.match(help, /explicit output/); assert.match(help, /no automatic human acceptance/);
});

test("author-cut CLI malformed/duplicate/oversized transport and override args never dispatch", async t => {
  const f = authorFixture(t), file = path.join(f.root, "TEST-author-request.json"); let calls = 0;
  t.mock.method(projectCommandServices, "authorCut", async () => { calls++; throw new Error("TEST must not launch"); });
  const original = JSON.stringify(f.request);
  for (const text of ["null", "{}{}", Buffer.from([255]), Buffer.alloc(131073, 32),
    original.replace('"schemaVersion":1', '"schemaVersion":2,"schemaVersion":1'),
    original.replace('"output":{', '"output":null,"\\u006futput":{'),
    JSON.stringify({ ...f.request, approved: true }), JSON.stringify({ ...f.request, model: "paid" })]) {
    writeFileSync(file, text); await assert.rejects(executeProjectCommand(["author-cut", file]));
  }
  writeFileSync(file, original);
  for (const argv of [["author-cut"], ["author-cut", file, "--force"], ["author-cut", file, "--deadline", "1"]]) {
    await assert.rejects(executeProjectCommand(argv));
  }
  assert.equal(calls, 0);
});
