/** Inert complete TEST trees and fake metadata runner only; no Python, providers or media execute here. */
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { mkdirSync, mkdtempSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import type { runCutPreviewProcess } from "../../../app/api/producer/auto-edit/cut-preview-process";
import { captureDependencies, DEPENDENCY_ROLES, TOOL_ROLES, type CapsuleTools, type DependencyRoots } from "./_guided-runtime-capsule-dependencies";
import { observeCapsulePythonStartup, type CapsulePythonInput } from "./_guided-runtime-capsule-python";

const temporaryRoots: string[] = [], guard = () => {};
afterEach(() => { for (const root of temporaryRoots.splice(0)) rmSync(root, { recursive: true, force: true }); });

function inertFile(root: string, relative: string, bytes = "TEST inert bytes"): string {
  const file = path.join(root, relative); mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, bytes, { flag: "wx", mode: 0o600 }); return file;
}

function fixture() {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-python-startup-UNIT-ONLY-")));
  temporaryRoots.push(root);
  const roots = Object.fromEntries(DEPENDENCY_ROLES.map((role) => {
    const directory = path.join(root, role); mkdirSync(directory); return [role, directory];
  })) as DependencyRoots;
  const tools = Object.fromEntries(TOOL_ROLES.map((role) => [role, inertFile(root, `tools/${role}`)])) as CapsuleTools;
  tools.python = inertFile(roots.pythonBase, "bin/python3.14");
  const stdlib = path.join(roots.pythonBase, "lib/python3.14"), site = path.join(roots.venv, "lib/python3.14/site-packages");
  mkdirSync(path.join(stdlib, "lib-dynload"), { recursive: true }); mkdirSync(site, { recursive: true });
  symlinkSync(roots.pythonBaseSitePackages, path.join(stdlib, "site-packages"));
  mkdirSync(path.join(roots.venv, "bin")); symlinkSync(tools.python, path.join(roots.venv, "bin/python3"));
  const config = inertFile(roots.venv, "pyvenv.cfg", "include-system-site-packages = false\nversion = 3.14.4\n");
  const customizer = inertFile(stdlib, "sitecustomize.py", "# TEST no execution\n"), zip = path.join(roots.pythonBase, "lib/python314.zip");
  const input: CapsulePythonInput = { dependencies: captureDependencies(roots, tools, guard), cwd: root,
    env: { NODE_ENV: "test", PATH: "/usr/bin:/bin", PYTHONDONTWRITEBYTECODE: "1", PYTHONNOUSERSITE: "1" }, expiresAt: performance.now() + 20_000 };
  const metadata = { version: "3.14.4", prefix: roots.venv, execPrefix: roots.venv, basePrefix: roots.pythonBase,
    baseExecPrefix: roots.pythonBase, executable: tools.python, paths: [zip, stdlib, path.join(stdlib, "lib-dynload"), site],
    sitePackages: [site], userSite: false, sitecustomize: customizer, usercustomize: null,
    isolated: 1, noUserSite: 1, safePath: true, dontWriteBytecode: true };
  return { root, roots, tools, input, metadata, config, customizer, zip, site };
}

function runner(metadata: unknown): typeof runCutPreviewProcess {
  return async () => ({ stdout: JSON.stringify(metadata), stderr: "" });
}

test("exact isolated venv metadata is held separately from bundled inactive base site-packages", async () => {
  const f = fixture(); let calls = 0;
  const actual = await observeCapsulePythonStartup(f.input, guard, async (request) => {
    calls++; assert.equal(request.command, path.join(f.roots.venv, "bin/python3"));
    assert.deepEqual(request.args.slice(0, 3), ["-I", "-B", "-c"]);
    assert.equal(request.env, f.input.env); assert.equal(request.cwd, f.input.cwd);
    assert.equal(request.trackForShutdown, true); assert.ok(request.timeoutMs <= 10_000);
    return { stdout: JSON.stringify(f.metadata), stderr: "" };
  });
  assert.equal(calls, 1); assert.deepEqual(actual.metadata, f.metadata);
  assert.equal(actual.customizers[0].path, f.customizer); assert.equal(actual.absentZip, f.zip);
  assert.equal(actual.metadata.paths.includes(f.roots.pythonBaseSitePackages), false);
  assert.deepEqual(await observeCapsulePythonStartup(f.input, guard, runner(f.metadata)), actual);
});

test("external or extra runtime path, cwd, global purelib and changed binary/prefix reject", async () => {
  const f = fixture();
  const negatives = [
    { paths: [...f.metadata.paths, "/opt/homebrew/lib/python3.14/site-packages"] },
    { paths: [...f.metadata.paths, f.root] }, { paths: f.metadata.paths.slice(1) },
    { sitePackages: [f.roots.pythonBaseSitePackages] }, { executable: "/usr/bin/python3" },
    { prefix: f.roots.pythonBase }, { baseExecPrefix: f.roots.venv }, { version: "3.14.5" },
  ];
  for (const changed of negatives) {
    await assert.rejects(observeCapsulePythonStartup(f.input, guard, runner({ ...f.metadata, ...changed })), /unknown runtime/u);
  }
});

test("external, missing-held and user customizers are never accepted", async () => {
  const f = fixture();
  await assert.rejects(observeCapsulePythonStartup(f.input, guard, runner({ ...f.metadata, sitecustomize: "/private/tmp/unknown.py" })), /customizer/u);
  await assert.rejects(observeCapsulePythonStartup(f.input, guard, runner({ ...f.metadata, usercustomize: f.customizer })), /metadata/u);
  inertFile(f.site, "sitecustomize.py");
  await assert.rejects(observeCapsulePythonStartup(f.input, guard, async () => { assert.fail("must not spawn"); }), /held inventory/u);
});

test("user site and non-isolated or bytecode-writing startup reject", async () => {
  const f = fixture();
  for (const changed of [{ userSite: true }, { userSite: null }, { isolated: 0 }, { noUserSite: 0 }, { safePath: false }, { dontWriteBytecode: false }]) {
    await assert.rejects(observeCapsulePythonStartup(f.input, guard, runner({ ...f.metadata, ...changed })), /metadata/u);
  }
});

test("changed config, true system site and ambiguous config reject before metadata spawn", async () => {
  for (const config of ["include-system-site-packages = true\nversion = 3.14.4\n",
    "include-system-site-packages = false\ninclude-system-site-packages = true\nversion = 3.14.4\n"]) {
    const f = fixture(); writeFileSync(f.config, config);
    f.input.dependencies = captureDependencies(f.roots, f.tools, guard);
    await assert.rejects(observeCapsulePythonStartup(f.input, guard, async () => { assert.fail("must not spawn"); }), /configuration/u);
  }
  const f = fixture(); writeFileSync(f.config, "version = 3.14.5\n");
  await assert.rejects(observeCapsulePythonStartup(f.input, guard, async () => { assert.fail("must not spawn"); }), /changed/u);
});

test("new or initially held .pth loaders reject before spawn, including executable and path-only files", async () => {
  const f = fixture(); inertFile(f.site, "editable.pth", "import unsafe_loader\n");
  await assert.rejects(observeCapsulePythonStartup(f.input, guard, async () => { assert.fail("must not spawn"); }), /\.pth/u);
  f.input.dependencies = captureDependencies(f.roots, f.tools, guard);
  await assert.rejects(observeCapsulePythonStartup(f.input, guard, async () => { assert.fail("must not spawn"); }), /\.pth/u);
  const other = fixture(); inertFile(other.site, "paths.pth", "/private/tmp/foreign-source\n");
  await assert.rejects(observeCapsulePythonStartup(other.input, guard, async () => { assert.fail("must not spawn"); }), /\.pth/u);
});

test("expected absent stdlib zip cannot appear before or during metadata observation", async () => {
  const f = fixture(); writeFileSync(f.zip, "TEST archive-like bytes");
  await assert.rejects(observeCapsulePythonStartup(f.input, guard, async () => { assert.fail("must not spawn"); }), /stdlib zip/u);
  const later = fixture();
  await assert.rejects(observeCapsulePythonStartup(later.input, guard, async () => {
    writeFileSync(later.zip, "TEST appeared during child"); return { stdout: JSON.stringify(later.metadata), stderr: "" };
  }), /stdlib zip/u);
});

test("late .pth and config mutation cannot return a successful held startup record", async () => {
  const f = fixture();
  await assert.rejects(observeCapsulePythonStartup(f.input, guard, async () => {
    inertFile(f.site, "late.pth"); return { stdout: JSON.stringify(f.metadata), stderr: "" };
  }), /\.pth/u);
  const later = fixture();
  await assert.rejects(observeCapsulePythonStartup(later.input, guard, async () => {
    writeFileSync(later.config, "version = 3.14.5\n"); return { stdout: JSON.stringify(later.metadata), stderr: "" };
  }), /changed/u);
});

test("customizer bytes and exact base-site link remain held, not just metadata paths", async () => {
  const f = fixture(); writeFileSync(f.customizer, "# TEST changed\n");
  await assert.rejects(observeCapsulePythonStartup(f.input, guard, async () => { assert.fail("must not spawn"); }), /changed/u);
  const other = fixture(); other.input.dependencies.roots.pythonBaseSitePackages = other.roots.nodeModules;
  await assert.rejects(observeCapsulePythonStartup(other.input, guard, async () => { assert.fail("must not spawn"); }), /layout/u);
});

test("new customizer bytecode and user customizers reject before startup execution", async () => {
  const f = fixture(); inertFile(f.site, "__pycache__/sitecustomize.cpython-314.pyc");
  await assert.rejects(observeCapsulePythonStartup(f.input, guard, async () => { assert.fail("must not spawn"); }), /held inventory/u);
  const other = fixture(); inertFile(other.site, "usercustomize.py");
  other.input.dependencies = captureDependencies(other.roots, other.tools, guard);
  await assert.rejects(observeCapsulePythonStartup(other.input, guard, async () => { assert.fail("must not spawn"); }), /user customizer/u);
});

test("one original deadline includes prechecks and metadata without resetting remaining credit", async () => {
  const f = fixture(); f.input.expiresAt = performance.now() + 1700;
  await observeCapsulePythonStartup(f.input, guard, async (request) => {
    assert.ok(request.timeoutMs > 0 && request.timeoutMs <= 1700);
    assert.ok(request.timeoutMs <= Math.ceil(f.input.expiresAt - performance.now()));
    return { stdout: JSON.stringify(f.metadata), stderr: "" };
  });
  f.input.expiresAt = performance.now() - 1;
  await assert.rejects(observeCapsulePythonStartup(f.input, guard, async () => { assert.fail("must not spawn"); }), /original deadline/u);
  const later = fixture();
  await assert.rejects(observeCapsulePythonStartup(later.input, guard, async () => {
    later.input.expiresAt = performance.now() - 1; return { stdout: JSON.stringify(later.metadata), stderr: "" };
  }), /original deadline/u);
});

test("cancellation is forwarded and cancelled or unknown cleanup never admits startup", async () => {
  const f = fixture(), abort = new AbortController(); f.input.signal = abort.signal;
  await assert.rejects(observeCapsulePythonStartup(f.input, guard, async (request) => {
    assert.equal(request.signal, abort.signal); abort.abort(); return { stdout: JSON.stringify(f.metadata), stderr: "" };
  }), /cancelled/u);
  const other = fixture(), unknown = new Error("TEST group absence unknown"); let calls = 0;
  await assert.rejects(observeCapsulePythonStartup(other.input, guard, async () => { calls++; throw unknown; }), (error) => error === unknown);
  assert.equal(calls, 1);
});

test("bounded metadata rejects extra rows, malformed objects, oversized output and diagnostics", async () => {
  const f = fixture();
  for (const stdout of ["null", "[]", "{}", JSON.stringify(f.metadata) + "\n{}", "x".repeat(32769)]) {
    await assert.rejects(observeCapsulePythonStartup(f.input, guard, async () => ({ stdout, stderr: "" })));
  }
  await assert.rejects(observeCapsulePythonStartup(f.input, guard, async () => ({ stdout: JSON.stringify(f.metadata), stderr: "TEST diagnostic" })), /diagnostics/u);
});
