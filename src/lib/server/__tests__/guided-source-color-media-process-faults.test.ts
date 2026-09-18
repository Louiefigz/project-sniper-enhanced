/** Original callback boundaries with exact TEMP-only fault files. No real executable/worker/media is invoked. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { sourceColorMediaFixture, replaceMediaFixtureFile } from "./_guided-source-color-media-process-fixture";

test("original request mutation in first work callback refuses before native dispatch", async t => {
  const f = sourceColorMediaFixture(t);
  f.callbacks.work = () => { f.input.sourceColor.submission.expectedToken += "changed"; };
  await assert.rejects(f.run(), /original|changed/); assert.equal(f.calls.invoke, 0);
});

test("caller cannot replace original remaining callback in first resource callback", async t => {
  const f = sourceColorMediaFixture(t); f.callbacks.resource = () => { f.input.remainingMs = () => 1_500_000; };
  await assert.rejects(f.run(), /original|changed/); assert.equal(f.calls.invoke, 0);
});

test("final resource callback cannot release the actual project after its last assertion", async t => {
  const f = sourceColorMediaFixture(t); let settled = false;
  f.callbacks.settled = () => { settled = true; };
  f.callbacks.resource = () => { if (settled) f.input.lease.release(); };
  await assert.rejects(f.run(), /ENOENT|lease|changed/); assert.equal(f.calls.invoke, 1);
  assert.equal(fs.existsSync(path.join(f.root, "media-process-result.json")), false);
});

for (const name of ["claim", "input", "sidecar", "reservation", "intent", "journal"] as const) test(`settled callback replacement of ${name} cannot publish an activated success`, async t => {
  const f = sourceColorMediaFixture(t); f.callbacks.settled = () => replaceMediaFixtureFile(f, name);
  await assert.rejects(f.run(), /changed/); assert.equal(f.calls.invoke, 1);
  assert.equal(fs.existsSync(path.join(f.root, "media-process-result.json")), false);
});

test("actual original inert tool bytes changed after settled return reject before outcome publication", async t => {
  const f = sourceColorMediaFixture(t); f.callbacks.settled = () => replaceMediaFixtureFile(f, "script", "TEST changed inert bytes\n");
  await assert.rejects(f.run(), /changed/); assert.equal(f.calls.invoke, 1);
});

test("actual original inert tool bytes changed before dispatch refuse without native invocation", async t => {
  const f = sourceColorMediaFixture(t); let changed = false;
  const actual = f.dependencies.tools;
  f.dependencies.tools = () => { const tools = actual(); changed = true; replaceMediaFixtureFile(f, "script", "TEST changed inert bytes\n"); return tools; };
  await assert.rejects(f.run(), /changed/); assert.equal(changed, true); assert.equal(f.calls.invoke, 0);
});

test("actual returned native output cannot mutate in a later original resource callback", async t => {
  const f = sourceColorMediaFixture(t), invoke = f.dependencies.invoke; let returned: { stdout: string; stderr: string } | undefined;
  f.dependencies.invoke = async input => { returned = await invoke(input); return returned; };
  f.callbacks.resource = () => { if (returned) returned.stdout = "TEST substituted after return"; };
  await assert.rejects(f.run(), /returned metadata changed/); assert.equal(f.calls.invoke, 1);
});

test("actual claim reader cannot return equal hash but substituted runtime metadata", async t => {
  const f = sourceColorMediaFixture(t), claim = f.dependencies.claim;
  f.dependencies.claim = () => { const held = claim(); held.claim.runtime.userId = "999:999"; return held; };
  await assert.rejects(f.run(), /original claim|activated claim/); assert.equal(f.calls.invoke, 1);
});

for (const name of ["outcome", "ledger"] as const) test(`final claim callback cannot replace the held ${name}`, async t => {
  const f = sourceColorMediaFixture(t); f.callbacks.claim = () => replaceMediaFixtureFile(f, name);
  await assert.rejects(f.run(), /changed/); assert.equal(f.calls.invoke, 1);
});

test("first settled resource callback cannot erase an original unrecorded nested spawn before ledger capture", async t => {
  const f = sourceColorMediaFixture(t); let original: string | undefined;
  f.callbacks.settled = () => {
    original = fs.readFileSync(path.join(f.root, "owned-process-ledger.media.jsonl"), "utf8");
    const rows = original.trimEnd().split("\n");
    rows.splice(1, 0, JSON.stringify({ event: "intent", pid: null, argv0: "/TEST/unspawned-child", at: 100.5 }));
    replaceMediaFixtureFile(f, "ledger", rows.join("\n") + "\n");
  };
  f.callbacks.resource = () => {
    if (original !== undefined) { const bytes = original; original = undefined; replaceMediaFixtureFile(f, "ledger", bytes); }
  };
  await assert.rejects(f.run(), /changed/); assert.equal(f.calls.invoke, 1);
  assert.equal(fs.existsSync(path.join(f.root, "media-process-result.json")), false);
});

/** Create only a named new TEST entry; never overwrite an existing held artifact or follow a dependency target. */
function premature(f: ReturnType<typeof sourceColorMediaFixture>, name: "ledger" | "result"): void {
  assert(f.root.startsWith(fs.realpathSync(f.staging.root) + path.sep)); assert.equal(fs.realpathSync(f.root), f.root);
  assert(fs.lstatSync(f.root).isDirectory()); assert.equal(fs.lstatSync(f.root).uid, process.getuid!());
  const file = path.join(f.root, name === "ledger" ? "owned-process-ledger.media.jsonl" : "media-process-result.json");
  fs.writeFileSync(file, "TEST unexpected pre-spawn entry; NOT process proof\n", { flag: "wx", mode: 0o600 });
}

for (const name of ["ledger", "result"] as const) test(`readiness callback cannot create premature ${name} before native dispatch`, async t => {
  const f = sourceColorMediaFixture(t), readiness = f.dependencies.readiness;
  f.dependencies.readiness = dir => { premature(f, name); return readiness(dir); };
  await assert.rejects(f.run()); assert.equal(f.calls.invoke, 0);
});

for (const name of ["ledger", "result"] as const) test(`actual invoker pre-spawn remaining callback refuses premature ${name}`, async t => {
  const f = sourceColorMediaFixture(t); let once = true;
  f.callbacks.work = () => { if (once && f.requests.length) { once = false; premature(f, name); } };
  if (name === "result") await assert.rejects(f.run());
  else { const result = await f.run(); assert.equal(result.receipt.status, "failed"); assert.equal(result.stopped, null); }
  assert.equal(f.requests.length, 1); assert.equal(f.calls.invoke, 0);
});
