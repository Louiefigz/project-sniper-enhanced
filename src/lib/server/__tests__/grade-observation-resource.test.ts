import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test, { type TestContext } from "node:test";
import { acquireGradeObservationResource, gradeObservationResourceDependencies } from "../grade-observation-resource";
import { acquireProjectMutationLease, type ProjectMutationLease } from "../project-mutation-lease";
import { sourceInventory } from "../grade-observation-store";
import { sha } from "@/app/api/producer/studio/import/files";

/** Real lease/filesystem protocol confined to one fresh canonical TEST root. */
function fixture(t: TestContext) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "grade-resource-unit-")));
  const resource = path.join(root, ".sniper-color-resource"), leases: ProjectMutationLease[] = [];
  t.after(() => {
    leases.forEach(lease => lease.release());
    assert.equal(fs.realpathSync(root), root);
    assert.equal(path.dirname(root), fs.realpathSync(os.tmpdir()));
    fs.rmSync(root, { recursive: true, force: true });
  });
  const dependencies = { ...gradeObservationResourceDependencies, workspace: () => root,
    acquire: (directory: string, operation: string) => {
      assert.equal(directory, resource);
      const result = acquireProjectMutationLease(directory, operation);
      if (result.lease) leases.push(result.lease);
      return result;
    } };
  const lock = path.join(resource, ".sniper-project-mutation.lock");
  const owners = () => fs.readdirSync(resource).filter(name => name.startsWith(".sniper-project-mutation.owner-"));
  return { root, resource, lock, owners, leases, dependencies };
}

test("returns the actual global lease and live guard without acquiring a project lease or creating a clock", t => {
  const f = fixture(t), held = acquireGradeObservationResource("TEST existing-project owner", f.dependencies);
  assert.deepEqual(Object.keys(held).sort(), ["assertResource", "lease", "resource"]);
  assert.equal(held.resource, f.resource); assert.equal(held.lease, f.leases[0]);
  held.assertResource();
  assert.deepEqual(fs.readdirSync(f.root), [".sniper-color-resource"]);
  assert.equal(fs.existsSync(path.join(f.resource, "active.json")), false);
  assert.equal(fs.existsSync(f.lock), true); assert.equal(f.owners().length, 1);
  held.lease.release();
  assert.equal(fs.existsSync(f.lock), false); assert.deepEqual(f.owners(), []);
});

test("contention keeps the other exact lease and active bytes untouched", t => {
  const f = fixture(t), first = acquireGradeObservationResource("TEST first owner", f.dependencies);
  const active = path.join(f.resource, "active.json"), bytes = Buffer.from("TEST unresolved ownership");
  fs.writeFileSync(active, bytes, { mode: 0o400, flag: "wx" });
  const original = fs.readFileSync(f.lock), owners = f.owners();
  assert.throws(() => acquireGradeObservationResource("TEST second owner", f.dependencies), /busy/);
  assert.equal(f.leases.length, 1); first.assertResource();
  assert.deepEqual(fs.readFileSync(f.lock), original); assert.deepEqual(f.owners(), owners);
  assert.deepEqual(fs.readFileSync(active), bytes);
});

test("occupied malformed active record rejects and releases only the newly acquired resource lease", t => {
  const f = fixture(t);
  fs.mkdirSync(f.resource, { mode: 0o700 });
  const active = path.join(f.resource, "active.json"), bytes = Buffer.from("{ TEST malformed but retained");
  fs.writeFileSync(active, bytes, { mode: 0o400, flag: "wx" });
  const before = fs.lstatSync(active, { bigint: true });
  assert.throws(() => acquireGradeObservationResource("TEST occupied", f.dependencies), /unverified cleanup/);
  assert.equal(f.leases.length, 1); assert.equal(fs.existsSync(f.lock), false);
  assert.deepEqual(fs.lstatSync(active, { bigint: true }), before);
  assert.deepEqual(f.owners(), []); assert.deepEqual(fs.readFileSync(active), bytes);
});

test("dangling active marker rejects without following, removing or replacing its exact link", t => {
  const f = fixture(t);
  fs.mkdirSync(f.resource, { mode: 0o700 });
  const active = path.join(f.resource, "active.json"), missing = path.join(f.root, "TEST-absent-target");
  fs.symlinkSync(missing, active);
  const before = fs.lstatSync(active, { bigint: true });
  assert.equal(fs.existsSync(active), false); assert(before.isSymbolicLink());
  assert.throws(() => acquireGradeObservationResource("TEST dangling marker", f.dependencies), /unverified cleanup/);
  assert.equal(f.leases.length, 1); assert.equal(fs.existsSync(f.lock), false); assert.deepEqual(f.owners(), []);
  assert.deepEqual(fs.lstatSync(active, { bigint: true }), before);
  assert.equal(fs.readlinkSync(active), missing); assert.equal(fs.existsSync(missing), false);
});

test("active directory marker also fences work and preserves its exact identity", t => {
  const f = fixture(t);
  fs.mkdirSync(f.resource, { mode: 0o700 });
  const active = path.join(f.resource, "active.json");
  fs.mkdirSync(active, { mode: 0o700 });
  const before = fs.lstatSync(active, { bigint: true });
  assert.throws(() => acquireGradeObservationResource("TEST directory marker", f.dependencies), /unverified cleanup/);
  assert.equal(fs.existsSync(f.lock), false); assert.deepEqual(f.owners(), []);
  assert.deepEqual(fs.lstatSync(active, { bigint: true }), before); assert.deepEqual(fs.readdirSync(active), []);
});

test("guard construction failure releases the acquired lease and propagates the original error", t => {
  const f = fixture(t), failure = new Error("TEST guard construction failure");
  assert.throws(() => acquireGradeObservationResource("TEST guard fault", { ...f.dependencies,
    guard: (resource, lease) => {
      assert.equal(resource, f.resource); assert.equal(lease, f.leases[0]); throw failure;
    } }), error => error === failure);
  assert.equal(f.leases.length, 1); assert.equal(fs.existsSync(f.lock), false);
  assert.deepEqual(f.owners(), []);
});

test("final live guard failure cannot escape as a valid acquired resource", t => {
  const f = fixture(t), failure = new Error("TEST final guard failure");
  let called = 0;
  assert.throws(() => acquireGradeObservationResource("TEST guard callback", { ...f.dependencies,
    guard: (resource, lease) => {
      const actual = f.dependencies.guard(resource, lease);
      return () => { actual(); called++; throw failure; };
    } }), error => error === failure);
  assert.equal(called, 1); assert.equal(fs.existsSync(f.lock), false); assert.deepEqual(f.owners(), []);
});

test("active inspection EACCES releases the new lease without treating uncertainty as absence", t => {
  const f = fixture(t), failure = Object.assign(new Error("TEST active inspection failure"), { code: "EACCES" });
  const active = path.join(f.resource, "active.json"), bytes = Buffer.from("TEST inspection fault");
  assert.throws(() => acquireGradeObservationResource("TEST inspection", { ...f.dependencies,
    activeExists: file => {
      assert.equal(file, active); fs.writeFileSync(active, bytes, { mode: 0o400, flag: "wx" }); throw failure;
    } }), error => error === failure);
  assert.equal(fs.existsSync(f.lock), false); assert.deepEqual(f.owners(), []);
  assert.deepEqual(fs.readFileSync(active), bytes);
});

test("default no-follow marker inspection propagates EACCES rather than returning absent", t => {
  const f = fixture(t), failure = Object.assign(new Error("TEST unreadable marker"), { code: "EACCES" });
  const mock = t.mock.method(fs, "lstatSync", () => { throw failure; });
  try {
    assert.throws(() => gradeObservationResourceDependencies.activeExists(path.join(f.resource, "active.json")),
      error => error === failure);
  } finally { mock.mock.restore(); }
  assert.equal(f.leases.length, 0); assert.deepEqual(fs.readdirSync(f.root), []);
});

test("unsafe private resource fails before acquiring any lease", t => {
  const f = fixture(t);
  fs.mkdirSync(f.resource, { mode: 0o755 }); fs.chmodSync(f.resource, 0o755);
  assert.throws(() => acquireGradeObservationResource("TEST unsafe root", f.dependencies), /Unsafe private/);
  assert.equal(f.leases.length, 0); assert.equal(fs.existsSync(f.lock), false);
});

test("workspace resolution failure never acquires or releases a resource", t => {
  const f = fixture(t), failure = new Error("TEST missing workspace");
  assert.throws(() => acquireGradeObservationResource("TEST resolution", { ...f.dependencies,
    workspace: () => { throw failure; } }), error => error === failure);
  assert.equal(f.leases.length, 0); assert.deepEqual(fs.readdirSync(f.root), []);
});

test("underlying acquisition exception is not retried and no foreign release is attempted", t => {
  const f = fixture(t), failure = new Error("TEST acquisition exception"); let calls = 0;
  assert.throws(() => acquireGradeObservationResource("TEST acquire fault", { ...f.dependencies,
    acquire: () => { calls++; throw failure; } }), error => error === failure);
  assert.equal(calls, 1); assert.equal(f.leases.length, 0); assert.deepEqual(fs.readdirSync(f.resource), []);
});

test("retained live guard rejects a later replacement lease instead of adopting its identity", t => {
  const f = fixture(t), first = acquireGradeObservationResource("TEST original", f.dependencies);
  first.lease.release();
  const second = acquireGradeObservationResource("TEST replacement", f.dependencies);
  assert.throws(first.assertResource, /replaced/); second.assertResource();
  first.lease.release(); second.assertResource();
});

test("cleanup remains caller-owned after success; releasing a lease does not delete active evidence", t => {
  const f = fixture(t), held = acquireGradeObservationResource("TEST retained work", f.dependencies);
  const active = path.join(f.resource, "active.json"), bytes = Buffer.from("TEST no cleanup claim");
  fs.writeFileSync(active, bytes, { mode: 0o400, flag: "wx" });
  held.assertResource(); held.lease.release();
  assert.deepEqual(fs.readFileSync(active), bytes);
  assert.throws(() => acquireGradeObservationResource("TEST no recovery", f.dependencies), /unverified cleanup/);
  assert.equal(fs.existsSync(f.lock), false);
});

test("release failure retains both errors without claiming cleanup or swallowing the original failure", t => {
  const f = fixture(t), primary = new Error("TEST validation"), release = new Error("TEST release uncertain");
  let releases = 0;
  assert.throws(() => acquireGradeObservationResource("TEST error retention", { ...f.dependencies,
    acquire: (resource, operation) => {
      const actual = f.dependencies.acquire(resource, operation); assert(actual.lease);
      return { lease: { release: () => { releases++; throw release; } } };
    }, guard: () => { throw primary; } }), error => {
    assert(error instanceof AggregateError); assert.deepEqual(error.errors, [primary, release]); return true;
  });
  assert.equal(releases, 1); assert.equal(fs.existsSync(f.lock), true);
});

test("current source inventory explicitly holds the extracted shared helper bytes", t => {
  const f = fixture(t), producer = path.join(f.root, "scripts/producer"), server = path.join(f.root, "src/lib/server");
  fs.mkdirSync(producer, { recursive: true }); fs.mkdirSync(server, { recursive: true });
  const names = ["grade-observation-store.ts", "grade-observation-process.ts", "grade-observation-service.ts", "grade-observation-resource.ts"];
  names.forEach(name => fs.writeFileSync(path.join(server, name), `TEST inert inventory member ${name}`, { flag: "wx" }));
  const held = sourceInventory(f.root, process.hrtime.bigint() + BigInt(5_000_000_000));
  const helper = path.join(server, "grade-observation-resource.ts");
  assert.equal(held.files.length, 4);
  assert.deepEqual(held.files.find(row => row.path === helper), { path: helper, sha256: sha(fs.readFileSync(helper)) });
  fs.unlinkSync(helper);
  assert.throws(() => sourceInventory(f.root, process.hrtime.bigint() + BigInt(5_000_000_000)), /ENOENT/);
});
