import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test, { type TestContext } from "node:test";
import { sourceInventory, sourceInventoryUnderGuard } from "../grade-observation-store";
import { sha } from "@/app/api/producer/studio/import/files";

/** Inert code bytes only, confined to a single exact temporary inventory tree. */
function fixture(t: TestContext) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "grade-inventory-unit-")));
  const producer = path.join(root, "scripts/producer"), server = path.join(root, "src/lib/server");
  fs.mkdirSync(producer, { recursive: true }); fs.mkdirSync(server, { recursive: true });
  const names = ["grade-observation-store.ts", "grade-observation-process.ts", "grade-observation-service.ts", "grade-observation-resource.ts"];
  for (const name of names) fs.writeFileSync(path.join(server, name), `TEST inert inventory ${name}`, { flag: "wx" });
  const worker = path.join(producer, "TEST-worker.py"), helper = path.join(producer, "TEST-helper.js");
  fs.writeFileSync(worker, "TEST inert Python", { flag: "wx" });
  fs.writeFileSync(helper, "TEST inert JavaScript", { flag: "wx" });
  fs.writeFileSync(path.join(producer, "TEST-ignored.md"), "Not an implementation module", { flag: "wx" });
  t.after(() => {
    assert.equal(fs.realpathSync(root), root);
    assert.equal(path.dirname(root), fs.realpathSync(os.tmpdir()));
    fs.rmSync(root, { recursive: true, force: true });
  });
  return { root, producer, server, names, worker, helper };
}

test("opening callback and original standalone deadline use identical files and raw hashes", t => {
  const f = fixture(t); let calls = 0;
  const current = sourceInventoryUnderGuard(f.root, () => { calls++; });
  const legacy = sourceInventory(f.root, process.hrtime.bigint() + BigInt(5_000_000_000));
  assert.deepEqual(current, legacy); assert.equal(current.files.length, 6);
  assert.deepEqual(current.files.find(row => row.path === f.worker), { path: f.worker, sha256: sha(fs.readFileSync(f.worker)) });
  assert(calls > current.files.length);
});

test("an expired original callback rejects before any inventory lookup or discovery", t => {
  const f = fixture(t), error = new Error("TEST original caller expired"); let calls = 0;
  assert.throws(() => sourceInventoryUnderGuard(path.join(f.root, "TEST-absent"), () => { calls++; throw error; }), value => value === error);
  assert.equal(calls, 1);
});

test("time consumed by final code hashing remains subject to the same final callback", t => {
  const f = fixture(t); let expected = 0;
  sourceInventoryUnderGuard(f.root, () => { expected++; });
  let calls = 0;
  assert.throws(() => sourceInventoryUnderGuard(f.root, () => {
    calls++; if (calls === expected) throw new Error("TEST original cutoff after final code hash");
  }), /original cutoff after final code hash/);
  assert.equal(calls, expected);
});

test("callbacks are neither retried nor replaced when original ownership or time fails", t => {
  const f = fixture(t), error = new Error("TEST original owner lost"); let calls = 0;
  assert.throws(() => sourceInventoryUnderGuard(f.root, () => { calls++; if (calls === 3) throw error; }), value => value === error);
  assert.equal(calls, 3);
});

test("callback inventory preserves missing required helper rejection", t => {
  const f = fixture(t), target = path.join(f.server, "grade-observation-resource.ts");
  fs.unlinkSync(target);
  assert.throws(() => sourceInventoryUnderGuard(f.root, () => undefined), /ENOENT/);
});

test("callback inventory preserves canonical source ancestry rejection", t => {
  const f = fixture(t), alias = path.join(f.root, "TEST-alias");
  fs.symlinkSync(path.join(f.root, "scripts"), alias, "dir");
  assert.throws(() => sourceInventoryUnderGuard(alias, () => undefined), /ENOENT|unsafe/);
  fs.symlinkSync(f.worker, path.join(f.producer, "TEST-symlink.py"));
  assert.throws(() => sourceInventoryUnderGuard(f.root, () => undefined), /unsafe/);
});

test("the existing standalone expired bigint still fails before inventory IO", t => {
  const f = fixture(t);
  assert.throws(() => sourceInventory(f.root, process.hrtime.bigint() - BigInt(1)), /work budget expired/);
});

test("each new inventory reads current bytes instead of adopting a stale cross-call cache", t => {
  const f = fixture(t), before = sourceInventoryUnderGuard(f.root, () => undefined);
  fs.writeFileSync(f.worker, "TEST changed owned Python bytes");
  const after = sourceInventoryUnderGuard(f.root, () => undefined);
  assert.notEqual(before.files.find(row => row.path === f.worker)?.sha256, after.files.find(row => row.path === f.worker)?.sha256);
});
