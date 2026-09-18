/** Metadata-only boundary tests. Runtime and process leaves are stubbed; no native or source reads. */
import assert from "node:assert/strict";
import test, { type TestContext } from "node:test";
import childProcess from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { invokeOpeningChild } from "../guided-opening-process";
import { assertSourceColorReadInvocation, holdSourceColorReadInvocation, type SourceColorReadInvocation } from "../guided-source-color-read-transport";
import { assertOpeningCleanupMetadata, openingCleanupStoreDependencies, readCommittedOpeningCleanup } from "../guided-opening-cleanup-store";
import { readFinalSourceColorCleanupForJournal } from "../guided-source-color-cleanup-final-read";
import { assertSourceColorOpeningResultMetadata, readHeldSourceColorOpeningResult } from "../guided-source-color-opening-result";
import { sourceColorOpeningResultFixture } from "./_guided-source-color-opening-result-fixture";
import { cleanupFinalReadFixture } from "./_guided-source-color-cleanup-final-read-fixture";

type ChildInput = Parameters<typeof invokeOpeningChild>[0];
const fake = { kind: "final-cleanup-bound-source-color-read", args: [], environment: {} };

/** Failures can never reach actual runtime/socket admission or a native process. */
function deniedInput(t: TestContext) {
  const calls = { runtime: 0, process: 0, remaining: 0 };
  t.mock.method(childProcess, "spawn", () => { calls.process++; throw new Error("TEST forbidden native frontier"); });
  const held = { get claim() { calls.runtime++; throw new Error("TEST forbidden runtime frontier"); } };
  const input = { held, tools: {}, kind: "read", remainingMs: () => { calls.remaining++; return 1000; } } as unknown as ChildInput;
  return { input, calls };
}

/** Actual runtime reads over inert TEMP files; only the exact socket type and pid-less child are TEST stubs. */
function legacyInput(t: TestContext) {
  const f = deniedInput(t), root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sniper-TEST-read-flags-")));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const dockerPath = path.join(root, "docker"), dockerSocketPath = path.join(root, "socket"), imageApprovalPath = path.join(root, "approval.json");
  const imageId = `sha256:${"a".repeat(64)}`, approval = JSON.stringify({ schemaVersion: 1, imageId });
  fs.writeFileSync(dockerPath, "TEST never executed", { flag: "wx", mode: 0o700 });
  fs.writeFileSync(dockerSocketPath, "TEST not a socket", { flag: "wx", mode: 0o600 });
  fs.writeFileSync(imageApprovalPath, approval, { flag: "wx", mode: 0o600 });
  const stat = fs.lstatSync(dockerSocketPath, { bigint: true }), originalStat = fs.lstatSync;
  t.mock.method(fs, "lstatSync", ((file: fs.PathLike, options?: unknown) => {
    const value = originalStat(file, options as fs.StatOptions);
    if (!value) return value;
    return file === dockerSocketPath ? Object.assign(value, { isSocket: () => true }) : value;
  }) as typeof fs.lstatSync);
  const sha = (bytes: string) => createHash("sha256").update(bytes).digest("hex");
  const runtime = { dockerPath, dockerSocketPath, imageApprovalPath, imageId, userId: "501:20", runtimeRepoRoot: root,
    dockerSha256: sha("TEST never executed"), imageApprovalSha256: sha(approval), dockerSocketDevice: String(stat.dev), dockerSocketInode: String(stat.ino) };
  f.input.held = { claim: { runtime, inputPath: path.join(root, "input"), outputRoot: path.join(root, "output"), inputSha256: "a".repeat(64) },
    claimPath: path.join(root, "claim"), claimSha256: "b".repeat(64), job: { ctx: { pipeline: { snapshotRoot: root } } } } as ChildInput["held"];
  f.input.tools = { script: path.join(root, "read.py"), python: path.join(root, "python") } as ChildInput["tools"];
  const commands: unknown[][] = [];
  t.mock.method(childProcess, "spawn", (...args: unknown[]) => {
    f.calls.process++; commands.push(args);
    const child = Object.assign(new EventEmitter(), { stdout: new PassThrough(), stderr: new PassThrough() });
    queueMicrotask(() => child.emit("close", 0, null)); return child as unknown as childProcess.ChildProcess;
  });
  return { ...f, commands };
}

for (const [name, value] of [["fake", fake], ["copy", { ...fake }], ["null", null], ["false", false]] as const) {
  test(`explicit ${name} invocation cannot reach runtime or remaining callbacks`, t => {
    const f = deniedInput(t); f.input.sourceColorRead = value as unknown as SourceColorReadInvocation;
    assert.throws(() => invokeOpeningChild(f.input), /actual original final-bound invocation/);
    assert.deepEqual(f.calls, { runtime: 0, process: 0, remaining: 0 });
    assert.throws(() => assertSourceColorReadInvocation(value as unknown as SourceColorReadInvocation, f.input.held),
      /actual original final-bound invocation/);
  });
}

for (const patch of [{ kind: "media" }, { kind: "cleanup" }, { extraArgs: [] }, { cleanupAttemptId: "TEST" }] as const) {
  test(`explicit invocation rejects role or argument override ${JSON.stringify(patch)}`, t => {
    const f = deniedInput(t); Object.assign(f.input, patch, { sourceColorRead: fake });
    assert.throws(() => invokeOpeningChild(f.input), /cannot override its exact role or arguments/);
    assert.deepEqual(f.calls, { runtime: 0, process: 0, remaining: 0 });
  });
}

for (const flag of ["--source-color-input", "--source-color-input-sha256", "--source-color-reservation-archive",
  "--source-color-reservation-archive-sha256", "--source-color-input=/TEST/not-read"]) {
  test(`raw ${flag} cannot bypass the private transport`, t => {
    const f = deniedInput(t); f.input.extraArgs = [flag, "TEST"];
    assert.throws(() => invokeOpeningChild(f.input), /require the actual final-bound invocation/);
    assert.deepEqual(f.calls, { runtime: 0, process: 0, remaining: 0 });
  });
}

for (const present of [false, true]) {
  test(`the original remaining callback cannot introduce raw flags or change captured arguments, original present=${present}`, async t => {
    const f = legacyInput(t), args = ["--receipt", "/TEST/original"], expected = present ? [...args] : [];
    if (present) f.input.extraArgs = args;
    f.input.remainingMs = () => {
      f.calls.remaining++; args.push("--source-color-input", "/TEST/injected");
      f.input.extraArgs = ["--source-color-input", "/TEST/replaced"]; return 1000;
    };
    await invokeOpeningChild(f.input);
    assert.equal(f.calls.process, 1);
    assert.deepEqual((f.commands[0][1] as string[]).slice(9, -2), expected);
  });
}

test("separately genuine final cleanup and result cannot be joined across different original held claims", async t => {
  const f = await cleanupFinalReadFixture(t), resultFixture = sourceColorOpeningResultFixture(t);
  t.mock.method(openingCleanupStoreDependencies, "final", (input: Parameters<typeof readFinalSourceColorCleanupForJournal>[0]) =>
    readFinalSourceColorCleanupForJournal(input, f.readDependencies));
  const cleanup = readCommittedOpeningCleanup(f.readInput.dir);
  const selected = readHeldSourceColorOpeningResult(resultFixture.context);
  assert.doesNotThrow(() => assertOpeningCleanupMetadata(cleanup));
  assert.doesNotThrow(() => assertSourceColorOpeningResultMetadata(selected, resultFixture.held));
  assert.notEqual(cleanup.held, resultFixture.held);
  assert.throws(() => holdSourceColorReadInvocation({ cleanup, selected }), /original|held|metadata/i);
  assert.doesNotThrow(() => assertOpeningCleanupMetadata(cleanup));
  assert.doesNotThrow(() => assertSourceColorOpeningResultMetadata(selected, resultFixture.held));
});
