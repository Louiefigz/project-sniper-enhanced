/** TEST owner protocol with inert files and explicit capture/builder/startup/runner seams. No real capsule or child. */
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { CutPreviewProcessError } from "../../../app/api/producer/auto-edit/cut-preview-process";
import { captureDependencies, DEPENDENCY_ROLES, TOOL_ROLES, verifyDependencies, type CapsuleTools, type DependencyRoots } from "./_guided-runtime-capsule-dependencies";
import { byteHash, observeFile } from "./_guided-runtime-capsule-io";
import { runTestCapsuleControlSmoke, type CapsuleOwnerInput, type CapsuleOwnerSeams } from "./_guided-runtime-capsule-owner";
import type { CapsuleReceipt } from "./_guided-runtime-capsule";
import type { CapsulePythonStartup } from "./_guided-runtime-capsule-python";

const roots: string[] = [], guard = () => {};
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
function file(root: string, name: string, bytes = "TEST inert bytes"): string {
  const target = path.join(root, name); mkdirSync(path.dirname(target), { recursive: true });
  writeFileSync(target, bytes, { flag: "wx", mode: 0o600 }); return target;
}
function fixture() {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-capsule-owner-UNIT-ONLY-"))); roots.push(root);
  const dependencyRoots = Object.fromEntries(DEPENDENCY_ROLES.map((name) => {
    const directory = path.join(root, name); mkdirSync(directory); file(directory, "package.bin"); return [name, directory];
  })) as DependencyRoots;
  const tools = Object.fromEntries(TOOL_ROLES.map((role) => [role, file(root, `tools/${role}`)])) as CapsuleTools;
  const sourceRoot = path.join(root, "source"); mkdirSync(sourceRoot); const source = file(sourceRoot, "TEST.ts");
  const input: CapsuleOwnerInput = { sourceRoot, ownerDirectory: path.join(root, "owner"), dependencies: { roots: dependencyRoots, tools },
    controls: { dockerSocket: path.join(root, "TEST-not-real-socket"), imageId: "sha256:" + "a".repeat(64), user: "501:20" } };
  return { root, input, source, events: [] as string[] };
}
type Fixture = ReturnType<typeof fixture>;

function fakeBuild(f: Fixture): CapsuleOwnerSeams["build"] {
  return (input, heldGuard = guard) => {
    heldGuard(); f.events.push("build"); const root = path.join(input.destination, "repo"); mkdirSync(root, { recursive: true });
    const source = observeFile(f.source, 1024, heldGuard), copied = file(root, "TEST.ts", readFileSync(f.source, "utf8"));
    const approval = file(root, "scripts/producer/headless/render_image_approval.json", JSON.stringify({ imageId: f.input.controls.imageId }));
    const receipt: CapsuleReceipt = { schemaVersion: 1, kind: "TEST-guided-runtime-capsule",
      scope: "TEST-only-exact-runtime-version-not-current-checkout-or-creator-approval", root,
      source: { root: input.source.root, pipeline: input.source.pipeline, files: [source], totalBytes: source.sizeBytes },
      dependencies: captureDependencies(input.dependencies.roots, input.dependencies.tools, heldGuard),
      files: [observeFile(copied, 1024, heldGuard), observeFile(approval, 1024, heldGuard)], links: [],
      createdAt: new Date().toISOString(), qualification: "not-run", originalDriverModified: false, sourceMutationPermission: false };
    const bytes = JSON.stringify(receipt), receiptPath = file(input.destination, "capsule.json", bytes);
    return { root, receiptPath, receiptSha256: byteHash(Buffer.from(bytes)) };
  };
}

function fakeVerify(f: Fixture): CapsuleOwnerSeams["verify"] {
  return (held, heldGuard = guard) => {
    heldGuard(); f.events.push("verify"); const bytes = readFileSync(held.receiptPath);
    assert.equal(byteHash(bytes), held.receiptSha256);
    const receipt = JSON.parse(bytes.toString()) as CapsuleReceipt;
    verifyDependencies(receipt.dependencies, heldGuard);
    for (const row of receipt.files) assert.deepEqual(observeFile(row.path, Math.max(1, row.sizeBytes), heldGuard), row);
    return receipt;
  };
}

function fakeStartup(f: Fixture): CapsuleOwnerSeams["startup"] {
  return async (input, heldGuard) => {
    heldGuard(); f.events.push(input.cwd === f.input.ownerDirectory ? "startup-initial" : "startup-capsule");
    const config = input.dependencies.files[0];
    return { schemaVersion: 1, kind: "TEST-capsule-python-startup", config, customizers: [], absentZip: "/TEST/absent.zip",
      metadata: { version: "3.14.4", prefix: input.dependencies.roots.venv, execPrefix: input.dependencies.roots.venv,
        basePrefix: input.dependencies.roots.pythonBase, baseExecPrefix: input.dependencies.roots.pythonBase,
        executable: input.dependencies.tools.python, paths: [], sitePackages: [], userSite: false, sitecustomize: null,
        usercustomize: null, isolated: 1, noUserSite: 1, safePath: true, dontWriteBytecode: true } } satisfies CapsulePythonStartup;
  };
}

function fakeControls(f: Fixture, cwd: string) {
  const tools = f.input.dependencies.tools;
  const names = { SNIPER_NODE_PATH: tools.node, HYPERFRAMES_BROWSER_PATH: tools.browser,
    HYPERFRAMES_FFMPEG_PATH: tools.ffmpeg, HYPERFRAMES_FFPROBE_PATH: tools.ffprobe, SNIPER_DOCKER_PATH: tools.docker };
  return { scope: "TEST-read-only-control-path-preflight-not-runtime-qualification",
    tools: Object.entries(names).map(([name, value]) => ({ name, configured: value, resolved: value })),
    socket: f.input.controls.dockerSocket, imageId: f.input.controls.imageId,
    imageApprovalSha256: byteHash(readFileSync(path.join(cwd, "scripts/producer/headless/render_image_approval.json"))),
    user: f.input.controls.user, runtimeRepoRoot: cwd, dockerContacted: false, credentialsRead: false };
}

function seams(f: Fixture): CapsuleOwnerSeams {
  return {
    capture: () => { f.events.push("capture"); const bytes = readFileSync(f.source); return [{ path: "TEST.ts", hash: byteHash(bytes), bytes }]; },
    dependencies: (...args) => { f.events.push("dependencies"); return captureDependencies(...args); },
    startup: fakeStartup(f), build: fakeBuild(f), verify: fakeVerify(f),
    invocation: (held) => ({ cwd: held.root, node: f.input.dependencies.tools.node, env: {} } as ReturnType<CapsuleOwnerSeams["invocation"]>),
    run: async (input) => { f.events.push("smoke"); return { stdout: JSON.stringify(fakeControls(f, input.cwd)), stderr: "" }; },
  };
}

function failure(f: Fixture): Record<string, unknown> {
  return JSON.parse(readFileSync(path.join(f.input.ownerDirectory, "failed.json"), "utf8"));
}

test("fresh protocol holds independent refs, fixed inert smoke and final verification with no ambient secrets", async () => {
  const f = fixture(), hooks = seams(f), base = hooks.run;
  hooks.run = async (input) => {
    assert.deepEqual(input.args, ["--import", "tsx", "src/lib/server/__tests__/_guided-body-live-fixture.ts", "--check-controls"]);
    assert.equal(input.command, f.input.dependencies.tools.node); assert.equal(input.trackForShutdown, true);
    assert.equal(input.env.ANTHROPIC_API_KEY, undefined); assert.equal(input.env.NODE_OPTIONS, undefined);
    assert.equal(input.env.DYLD_INSERT_LIBRARIES, undefined); assert.equal(input.env.HOME, undefined);
    assert.ok(input.timeoutMs > 0 && input.timeoutMs <= 30_000); return base(input);
  };
  const result = await runTestCapsuleControlSmoke(f.input, hooks);
  assert.deepEqual(f.events, ["capture", "dependencies", "startup-initial", "build", "verify", "verify", "startup-capsule", "verify", "smoke", "verify", "startup-capsule", "verify"]);
  assert.equal(result.fullRuntimeQualified, false); assert.equal(result.mediaGenerated, false); assert.equal(result.humanApproved, false);
  assert.equal(result.hostOsDylibsClosed, false); assert.equal(result.hostileSameUserRollbackProtected, false);
  assert.ok(result.independentlyHeld.pipeline.sha256); assert.ok(result.independentlyHeld["capsule-raw"].sha256);
  assert.equal(existsSync(path.join(f.input.ownerDirectory, "failed.json")), false);
});

test("new-only, overlap and parent symlink reject without captures or mutation", async () => {
  const f = fixture(); mkdirSync(f.input.ownerDirectory); file(f.input.ownerDirectory, "keep", "TEST retained");
  await assert.rejects(runTestCapsuleControlSmoke(f.input, seams(f)), /EEXIST/u); assert.deepEqual(f.events, []);
  assert.equal(readFileSync(path.join(f.input.ownerDirectory, "keep"), "utf8"), "TEST retained");
  const other = fixture(); other.input.ownerDirectory = path.join(other.input.sourceRoot, "owner");
  await assert.rejects(runTestCapsuleControlSmoke(other.input, seams(other)), /overlaps/u);
  const linked = path.join(other.root, "alias"); symlinkSync(other.input.sourceRoot, linked);
  other.input.ownerDirectory = path.join(linked, "owner");
  await assert.rejects(runTestCapsuleControlSmoke(other.input, seams(other)), /canonical/u);
});

test("actual built dependency divergence cannot pass through a self-consistent changed receipt", async () => {
  const f = fixture(), hooks = seams(f), original = hooks.build;
  hooks.build = (input, check) => {
    file(f.input.dependencies.roots.venv, "new.bin"); return original(input, check);
  };
  await assert.rejects(runTestCapsuleControlSmoke(f.input, hooks), AggregateError);
  assert.equal(f.events.includes("smoke"), false); assert.equal(failure(f).automaticRetry, false);
});

test("raw independently held pipeline evidence mutation cannot be concealed by an unchanged capsule", async () => {
  const f = fixture(), hooks = seams(f), original = hooks.build;
  hooks.build = (input, check) => {
    const held = original(input, check), retained = path.join(f.input.ownerDirectory, "pipeline.json");
    chmodSync(retained, 0o600); writeFileSync(retained, "[]"); return held;
  };
  await assert.rejects(runTestCapsuleControlSmoke(f.input, hooks), AggregateError);
  assert.equal(f.events.includes("smoke"), false); assert.equal(existsSync(path.join(f.input.ownerDirectory, "result.json")), false);
});

test("smoke failure still gets complete final verification/startup and never retries child", async () => {
  const f = fixture(), hooks = seams(f); let calls = 0;
  hooks.run = async () => { calls++; f.events.push("smoke-failed"); throw new CutPreviewProcessError("TEST controlled nonzero", {
    stdout: "", stderr: "", timedOut: false, groupStopped: true, forcedStop: false }, 1); };
  await assert.rejects(runTestCapsuleControlSmoke(f.input, hooks), AggregateError); assert.equal(calls, 1);
  assert.deepEqual(f.events.slice(-4), ["smoke-failed", "verify", "startup-capsule", "verify"]);
  assert.equal(failure(f).finalVerification, "passed"); assert.equal(failure(f).cleanupInferred, false);
});

test("changed copied file, raw capsule or installed bytes during smoke fail final verification", async () => {
  for (const kind of ["copy", "receipt", "dependency"]) {
    const f = fixture(), hooks = seams(f), original = hooks.run;
    hooks.run = async (input) => {
      const output = await original(input), filePath = kind === "copy" ? path.join(input.cwd, "TEST.ts")
        : kind === "receipt" ? path.join(path.dirname(input.cwd), "capsule.json") : path.join(f.input.dependencies.roots.venv, "package.bin");
      writeFileSync(filePath, "TEST changed"); return output;
    };
    await assert.rejects(runTestCapsuleControlSmoke(f.input, hooks), AggregateError);
    assert.notEqual(failure(f).finalVerification, "passed");
  }
});

test("cold final startup must match initial record, not merely be structurally valid", async () => {
  const f = fixture(), hooks = seams(f), original = hooks.startup; let calls = 0;
  hooks.startup = async (...args) => {
    const actual = await original(...args); return ++calls === 3 ? { ...actual, absentZip: "/TEST/new.zip" } : actual;
  };
  await assert.rejects(runTestCapsuleControlSmoke(f.input, hooks), AggregateError);
  assert.notEqual(failure(f).finalVerification, "passed");
});

test("unrelated installed bytes changed by final startup fail its post-startup full byte check", async () => {
  const f = fixture(), hooks = seams(f), original = hooks.startup; let calls = 0;
  hooks.startup = async (...args) => {
    const actual = await original(...args);
    if (++calls === 3) writeFileSync(path.join(f.input.dependencies.roots.nodeModules, "package.bin"), "TEST unrelated dependency changed");
    return actual;
  };
  await assert.rejects(runTestCapsuleControlSmoke(f.input, hooks), AggregateError);
  assert.notEqual(failure(f).finalVerification, "passed");
});

test("one 300s original deadline charges every phase and refuses late verification work", async (context) => {
  const f = fixture(), hooks = seams(f), original = hooks.startup; let now = 1000;
  context.mock.method(performance, "now", () => now);
  hooks.startup = async (...args) => { assert.equal(args[0].expiresAt, 301000); now += 1000; return original(...args); };
  hooks.run = async (input) => {
    assert.ok(input.timeoutMs <= 301000 - now); now = 301001;
    return { stdout: JSON.stringify(fakeControls(f, input.cwd)), stderr: "" };
  };
  await assert.rejects(runTestCapsuleControlSmoke(f.input, hooks), AggregateError);
  assert.equal(failure(f).deadlineExpired, true); assert.equal(f.events.filter((name) => name === "startup-capsule").length, 1);
});

test("cancelled child has no new startup allowance; unknown cleanup is not hidden by successful final bytes", async () => {
  const f = fixture(), abort = new AbortController(), hooks = seams(f); f.input.signal = abort.signal;
  hooks.run = async (input) => { assert.equal(input.signal, abort.signal); abort.abort(); throw new Error("TEST abort"); };
  await assert.rejects(runTestCapsuleControlSmoke(f.input, hooks), AggregateError);
  assert.equal(f.events.filter((name) => name === "startup-capsule").length, 1);
  const other = fixture(), unknown = seams(other);
  unknown.run = async () => { throw new CutPreviewProcessError("TEST unknown group", {
    stdout: "", stderr: "", timedOut: false, groupStopped: false, forcedStop: true }); };
  await assert.rejects(runTestCapsuleControlSmoke(other.input, unknown), AggregateError);
  assert.equal((failure(other).work as { process: { groupStopped: boolean } }).process.groupStopped, false);
  assert.equal(other.events.filter((name) => name === "startup-capsule").length, 1);
  assert.equal(failure(other).finalVerification, "byte-only-passed");
  assert.equal(failure(other).subsequentStartupBlocked, true);
});

test("forced stop and timeout with outer group absent still forbid another startup", async () => {
  for (const details of [{ forcedStop: true, timedOut: false }, { forcedStop: false, timedOut: true }]) {
    const f = fixture(), hooks = seams(f);
    hooks.run = async () => { throw new CutPreviewProcessError("TEST not normally reaped", { stdout: "", stderr: "", groupStopped: true, ...details }); };
    await assert.rejects(runTestCapsuleControlSmoke(f.input, hooks), AggregateError);
    assert.equal(f.events.filter((name) => name === "startup-capsule").length, 1);
    assert.equal(failure(f).finalVerification, "byte-only-passed");
    assert.equal(existsSync(path.join(f.input.ownerDirectory, "result.json")), false);
  }
});

test("initial and prelaunch startup unknown cleanup never permit subsequent child probes", async () => {
  for (const failAt of [1, 2]) {
    const f = fixture(), hooks = seams(f), original = hooks.startup; let calls = 0;
    hooks.startup = async (...args) => {
      if (++calls === failAt) throw new CutPreviewProcessError("TEST startup group unknown", {
        stdout: "", stderr: "", groupStopped: false, forcedStop: true, timedOut: false });
      return original(...args);
    };
    await assert.rejects(runTestCapsuleControlSmoke(f.input, hooks), AggregateError);
    assert.equal(calls, failAt); assert.equal(f.events.includes("smoke"), false);
    assert.equal(failure(f).finalVerification, "byte-only-passed");
    assert.equal(failure(f).subsequentStartupBlocked, true);
  }
});

test("generic startup/runner rejection cannot manufacture affirmative process cleanup", async () => {
  for (const boundary of ["initial", "prelaunch", "smoke"]) {
    const f = fixture(), hooks = seams(f), original = hooks.startup; let calls = 0;
    hooks.startup = async (...args) => {
      calls++;
      if ((boundary === "initial" && calls === 1) || (boundary === "prelaunch" && calls === 2)) throw new Error("TEST observer threw after spawn");
      return original(...args);
    };
    if (boundary === "smoke") hooks.run = async () => { throw new Error("TEST runner rejected without a cleanup verdict"); };
    await assert.rejects(runTestCapsuleControlSmoke(f.input, hooks), AggregateError);
    assert.equal(calls, boundary === "initial" ? 1 : 2);
    assert.equal(failure(f).subsequentStartupBlocked, true); assert.equal(failure(f).finalVerification, "byte-only-passed");
  }
});

test("source checkout may change after independent copy without claiming it remains current", async () => {
  const f = fixture(), hooks = seams(f), original = hooks.run;
  hooks.run = async (input) => { writeFileSync(f.source, "TEST developer change"); return original(input); };
  const result = await runTestCapsuleControlSmoke(f.input, hooks);
  assert.equal(readFileSync(path.join(result.capsule.root, "TEST.ts"), "utf8"), "TEST inert bytes");
  assert.equal(result.fullRuntimeQualified, false);
});

test("false control output cannot qualify an actual fixed command", async () => {
  const f = fixture(), hooks = seams(f);
  hooks.run = async () => ({ stdout: '{"scope":"TEST-media-qualified"}', stderr: "" });
  await assert.rejects(runTestCapsuleControlSmoke(f.input, hooks), AggregateError);
  assert.equal(failure(f).finalVerification, "passed");
});

test("a child throwing undefined cannot be mistaken for an absent failure", async () => {
  const f = fixture(), hooks = seams(f);
  hooks.run = async () => { throw undefined; };
  await assert.rejects(runTestCapsuleControlSmoke(f.input, hooks), AggregateError);
  assert.equal(existsSync(path.join(f.input.ownerDirectory, "result.json")), false);
});
