/** Inert TEST files only; no renderer, interpreter/model invocation, repository copy, or creator project. */
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { chmodSync, existsSync, linkSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { boundedBytes, byteHash, copyFileHeld, observeFile, writeNewBytes } from "./_guided-runtime-capsule-io";
import { captureDependencies, DEPENDENCY_ROLES, TOOL_ROLES, verifyDependencies, type DependencyRoots, type CapsuleTools } from "./_guided-runtime-capsule-dependencies";
import { buildTestRuntimeCapsule, materializeCapsuleSources, verifyTestRuntimeCapsule, type CapsuleReceipt } from "./_guided-runtime-capsule";

const roots: string[] = [], guard = () => {};
function temporary(): string {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-capsule-UNIT-ONLY-"))); roots.push(root); return root;
}
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });

function inertFile(root: string, relative: string, bytes = "TEST-only inert bytes"): string {
  const file = path.join(root, relative); mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  writeFileSync(file, bytes, { flag: "wx", mode: 0o600 }); return file;
}

function dependencyFixture(root: string) {
  const dependencyRoots = Object.fromEntries(DEPENDENCY_ROLES.map((role) => {
    const directory = path.join(root, role); mkdirSync(directory); inertFile(directory, "all-files.dat", "TEST " + role); return [role, directory];
  })) as DependencyRoots;
  const tools = Object.fromEntries(TOOL_ROLES.map((role) => [role, inertFile(root, `tools/${role}`, "TEST inert " + role)])) as CapsuleTools;
  return { roots: dependencyRoots, tools };
}

function receiptFixture() {
  const temporaryRoot = temporary(), sourceRoot = path.join(temporaryRoot, "original"), capsuleParent = path.join(temporaryRoot, "capsule");
  mkdirSync(sourceRoot); mkdirSync(capsuleParent); const root = path.join(capsuleParent, "repo"); mkdirSync(root);
  const original = inertFile(sourceRoot, "src/driver.ts"), row = observeFile(original, 1024, guard);
  const source = { root: sourceRoot, pipeline: [], files: [row], totalBytes: row.sizeBytes };
  const files = materializeCapsuleSources(source, root, guard), controls = dependencyFixture(temporaryRoot);
  const dependencies = captureDependencies(controls.roots, controls.tools, guard);
  mkdirSync(path.join(root, "templates/motion"), { recursive: true });
  const links = [{ path: path.join(root, "node_modules"), target: controls.roots.nodeModules },
    { path: path.join(root, "templates/motion/node_modules"), target: controls.roots.motionNodeModules }];
  for (const link of links) symlinkSync(link.target, link.path, "dir");
  const receipt: CapsuleReceipt = { schemaVersion: 1, kind: "TEST-guided-runtime-capsule",
    scope: "TEST-only-exact-runtime-version-not-current-checkout-or-creator-approval", root, source, files, dependencies, links,
    createdAt: new Date().toISOString(), qualification: "not-run", originalDriverModified: false, sourceMutationPermission: false };
  const receiptPath = path.join(capsuleParent, "capsule.json"), bytes = Buffer.from(JSON.stringify(receipt));
  writeNewBytes(receiptPath, bytes, guard);
  return { receipt, original, controls, held: { receiptPath, receiptSha256: byteHash(bytes), root } };
}

test("streamed source copies are independent regular bytes; checkout changes do not alter cold verification", () => {
  const fixture = receiptFixture(); writeFileSync(fixture.original, "edited checkout after capture");
  const result = verifyTestRuntimeCapsule(fixture.held);
  assert.equal(result.qualification, "not-run"); assert.equal(result.originalDriverModified, false);
  assert.equal(readFileSync(result.files[0].path, "utf8"), "TEST-only inert bytes");
});

test("changed copied source and changed raw capsule receipt both reject", () => {
  const fixture = receiptFixture(), file = fixture.receipt.files[0].path;
  chmodSync(file, 0o600); writeFileSync(file, "changed");
  assert.throws(() => verifyTestRuntimeCapsule(fixture.held), /changed|differs|projection/u);
  chmodSync(fixture.held.receiptPath, 0o600); writeFileSync(fixture.held.receiptPath, "{}");
  assert.throws(() => verifyTestRuntimeCapsule(fixture.held), /receipt bytes changed/u);
});

test("complete installed-tree bytes include non-framework/unknown package files", () => {
  const root = temporary(), controls = dependencyFixture(root);
  const extra = inertFile(controls.roots.nodeModules, "unanticipated-package/private-payload.bin", "TEST first");
  const held = captureDependencies(controls.roots, controls.tools, guard);
  assert.ok(held.files.some((row) => row.path === extra));
  writeFileSync(extra, "TEST next!");
  assert.throws(() => verifyDependencies(held, guard), /closure changed/u);
});

test("adding an installed file or changing a declared tool invalidates dependency authority", () => {
  const controls = dependencyFixture(temporary()), held = captureDependencies(controls.roots, controls.tools, guard);
  const added = inertFile(controls.roots.venv, "new-package.py");
  assert.throws(() => verifyDependencies(held, guard), /closure changed/u); unlinkSync(added);
  writeFileSync(controls.tools.python, "TEST replaced interpreter bytes");
  assert.throws(() => verifyDependencies(held, guard), /closure changed/u);
});

test("installed links stay exact and cannot escape to mutable source or arbitrary directories", () => {
  const root = temporary(), controls = dependencyFixture(root), linked = path.join(controls.roots.nodeModules, "allowed-link");
  symlinkSync("all-files.dat", linked); const held = captureDependencies(controls.roots, controls.tools, guard);
  assert.equal(held.links[0].resolved, path.join(controls.roots.nodeModules, "all-files.dat"));
  unlinkSync(linked); symlinkSync(inertFile(root, "unheld/foreign.dat"), linked);
  assert.throws(() => verifyDependencies(held, guard), /escapes/u);
});

test("base Python's external site-packages is a complete explicitly held tree, not an ignored link", () => {
  const controls = dependencyFixture(temporary());
  const linked = path.join(controls.roots.pythonBase, "site-packages");
  symlinkSync(controls.roots.pythonBaseSitePackages, linked, "dir");
  const held = captureDependencies(controls.roots, controls.tools, guard);
  assert.equal(held.links.find((row) => row.path === linked)?.resolved, controls.roots.pythonBaseSitePackages);
  const basePackage = path.join(controls.roots.pythonBaseSitePackages, "all-files.dat");
  assert.ok(held.files.some((row) => row.path === basePackage));
  writeFileSync(basePackage, "TEST changed unselected-base-package");
  assert.throws(() => verifyDependencies(held, guard), /closure changed/u);
});

test("source leaf symlinks, parent symlinks and hardlinks cannot enter copied authority", () => {
  const root = temporary(), real = inertFile(root, "real/source.ts"), leaf = path.join(root, "leaf"), parent = path.join(root, "alias");
  symlinkSync(real, leaf); symlinkSync(path.dirname(real), parent, "dir");
  assert.throws(() => observeFile(leaf, 1024, guard), /regular file|link/u);
  assert.throws(() => observeFile(path.join(parent, "source.ts"), 1024, guard), /parent/u);
  const hard = path.join(root, "hard"); linkSync(real, hard);
  assert.throws(() => observeFile(hard, 1024, guard), /regular file|link/u);
});

test("source size/hash races reject and leave partial new copy retained", () => {
  const root = temporary(), file = inertFile(root, "source", "TEST initial"), expected = observeFile(file, 1024, guard);
  writeFileSync(file, "TEST changed"); const target = path.join(root, "retained-partial");
  assert.throws(() => copyFileHeld(expected, target, guard), /differs/u); assert.equal(existsSync(target), true);
  assert.throws(() => copyFileHeld(expected, target, guard), /EEXIST/u);
});

test("chunk and terminal deadline guards abort without treating elapsed time as a completed copy", () => {
  const root = temporary(), file = inertFile(root, "large", "x".repeat(2 * 1024 * 1024)); let visits = 0;
  assert.throws(() => boundedBytes(file, 3 * 1024 * 1024, () => { if (++visits === 3) throw new Error("TEST expired"); }), /TEST expired/u);
  assert.equal(visits, 3);
  assert.throws(() => writeNewBytes(path.join(root, "never-created"), Buffer.from("x"), () => { throw new Error("TEST parent expired"); }), /parent expired/u);
  assert.equal(existsSync(path.join(root, "never-created")), false);
});

test("extra capsule files, missing dependency links and redirected links fail cold verification", () => {
  const fixture = receiptFixture(), extra = inertFile(fixture.held.root, "unexpected.ts");
  assert.throws(() => verifyTestRuntimeCapsule(fixture.held), /extra/u); unlinkSync(extra);
  const link = fixture.receipt.links[0]; unlinkSync(link.path);
  assert.throws(() => verifyTestRuntimeCapsule(fixture.held), /ENOENT/u);
  symlinkSync(fixture.controls.roots.motionNodeModules, link.path, "dir");
  assert.throws(() => verifyTestRuntimeCapsule(fixture.held), /link changed/u);
});

test("new-only builder rejects existing destination before source/dependency capture", () => {
  const root = temporary(), controls = dependencyFixture(root), sourceRoot = path.join(root, "original"); mkdirSync(sourceRoot);
  const destination = path.join(root, "already-created"); mkdirSync(destination); const marker = inertFile(destination, "keep", "TEST retained");
  assert.throws(() => buildTestRuntimeCapsule({ destination, source: { root: sourceRoot, pipeline: [] }, dependencies: controls }), /EEXIST/u);
  assert.equal(readFileSync(marker, "utf8"), "TEST retained");
});

test("dependency controls reject overlapping roots and unknown roles", () => {
  const controls = dependencyFixture(temporary());
  assert.throws(() => captureDependencies({ ...controls.roots, venv: controls.roots.nodeModules }, controls.tools, guard), /overlap/u);
  assert.throws(() => captureDependencies({ ...controls.roots, extra: controls.roots.nodeModules } as DependencyRoots, controls.tools, guard), /role set/u);
});
