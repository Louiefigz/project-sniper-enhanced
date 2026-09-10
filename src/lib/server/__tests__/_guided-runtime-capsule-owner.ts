/** TEST-only build + fixed control smoke. No full driver, media, approval, OS/dylib or hostile rollback guarantee. */
import { mkdirSync } from "node:fs";
import path from "node:path";
import { capturePipelineAssets } from "../auto-edit-pipeline-assets";
import { CutPreviewProcessError, runCutPreviewProcess } from "../../../app/api/producer/auto-edit/cut-preview-process";
import { buildTestRuntimeCapsule, capsuleInvocation, verifyTestRuntimeCapsule, type CapsuleReceipt, type HeldCapsule } from "./_guided-runtime-capsule";
import { captureDependencies, type CapsuleTools, type DependencyInventory, type DependencyRoots } from "./_guided-runtime-capsule-dependencies";
import { observeCapsulePythonStartup, type CapsulePythonStartup } from "./_guided-runtime-capsule-python";
import { byteHash, canonicalDirectory, observeFile, writeNewBytes, type CapsuleFile, type CapsuleGuard } from "./_guided-runtime-capsule-io";
import type { PipelineInventoryRow } from "./_guided-runtime-capsule-inventory";

const SCOPE = "TEST-only-capsule-build-control-smoke-not-runtime-media-or-human-qualification";
const LIMIT_MS = 300_000, RECORD_BYTES = 128 * 1024 * 1024;
const DRIVER = "src/lib/server/__tests__/_guided-body-live-fixture.ts";
const APPROVAL = "scripts/producer/headless/render_image_approval.json";
export interface CapsuleOwnerInput {
  ownerDirectory: string; sourceRoot: string; dependencies: { roots: DependencyRoots; tools: CapsuleTools };
  controls: { dockerSocket: string; imageId: string; user: string }; signal?: AbortSignal;
}
/** TEST-controlled seams exist only in this __tests__ module; there is no CLI override or production dispatcher. */
export interface CapsuleOwnerSeams {
  capture: typeof capturePipelineAssets; dependencies: typeof captureDependencies; startup: typeof observeCapsulePythonStartup;
  build: typeof buildTestRuntimeCapsule; verify: typeof verifyTestRuntimeCapsule;
  invocation: typeof capsuleInvocation; run: typeof runCutPreviewProcess;
}
const DEFAULTS: CapsuleOwnerSeams = { capture: capturePipelineAssets, dependencies: captureDependencies,
  startup: observeCapsulePythonStartup, build: buildTestRuntimeCapsule, verify: verifyTestRuntimeCapsule,
  invocation: capsuleInvocation, run: runCutPreviewProcess };
interface OwnerState {
  input: CapsuleOwnerInput; seams: CapsuleOwnerSeams; began: number; expiresAt: number; guard: CapsuleGuard;
  phase: string; failurePhase?: string; costs: Record<string, number>; refs: Record<string, CapsuleFile>;
  pipeline?: PipelineInventoryRow[]; dependencies?: DependencyInventory; startup?: CapsulePythonStartup;
  held?: HeldCapsule; env: NodeJS.ProcessEnv; smoke?: unknown; startupBlocked: boolean;
}

function outside(left: string, right: string): boolean {
  return left !== right && !left.startsWith(right + path.sep) && !right.startsWith(left + path.sep);
}

function createOwner(input: CapsuleOwnerInput, guard: CapsuleGuard): void {
  guard(); const parent = canonicalDirectory(path.dirname(input.ownerDirectory));
  if (path.join(parent, path.basename(input.ownerDirectory)) !== input.ownerDirectory
      || !/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$/u.test(path.basename(input.ownerDirectory))) throw new Error("TEST owner path is not canonical");
  for (const root of [input.sourceRoot, ...Object.values(input.dependencies.roots)]) {
    if (!outside(input.ownerDirectory, canonicalDirectory(root))) throw new Error("TEST owner overlaps a source/dependency root");
  }
  if (!path.isAbsolute(input.controls.dockerSocket) || !/^sha256:[0-9a-f]{64}$/u.test(input.controls.imageId)
      || !/^\d+:\d+$/u.test(input.controls.user)) throw new Error("TEST owner needs explicit nonsecret image/socket/user controls");
  mkdirSync(input.ownerDirectory, { mode: 0o700 }); // Existing/partial attempts never replay or overwrite.
  guard();
}

function environment(input: CapsuleOwnerInput): NodeJS.ProcessEnv {
  const tools = input.dependencies.tools, root = path.join(input.ownerDirectory, "capsule/repo");
  // Deliberately do not inherit process.env: no provider credentials, startup or loader injection variables.
  return { NODE_ENV: "test", PATH: [...new Set([...Object.values(tools).map((file) => path.dirname(file)), "/usr/bin", "/bin"])].join(path.delimiter),
    SNIPER_RUNTIME_REPO_ROOT: root, SNIPER_PYTHON_VENV_ROOT: input.dependencies.roots.venv, SNIPER_NODE_PATH: tools.node,
    HYPERFRAMES_BROWSER_PATH: tools.browser, HYPERFRAMES_FFMPEG_PATH: tools.ffmpeg, HYPERFRAMES_FFPROBE_PATH: tools.ffprobe,
    SNIPER_DOCKER_PATH: tools.docker, SNIPER_DOCKER_SOCKET: input.controls.dockerSocket,
    SNIPER_RENDER_IMAGE_ID: input.controls.imageId, SNIPER_RENDER_UID_GID: input.controls.user,
    TSX_TSCONFIG_PATH: path.join(root, "tsconfig.json"), TSX_DISABLE_CACHE: "1", PYTHONDONTWRITEBYTECODE: "1", PYTHONNOUSERSITE: "1" };
}

function retain(state: OwnerState, name: string, value: unknown): CapsuleFile {
  const bytes = Buffer.from(JSON.stringify(value));
  if (bytes.length > RECORD_BYTES) throw new Error("TEST owner evidence exceeds its byte bound");
  const file = path.join(state.input.ownerDirectory, name + ".json");
  writeNewBytes(file, bytes, state.guard); const held = observeFile(file, Math.max(1, bytes.length), state.guard);
  if (held.sha256 !== byteHash(bytes)) throw new Error("TEST owner evidence changed before hold");
  state.refs[name] = held; return held;
}

function assertRetained(state: OwnerState): void {
  for (const expected of Object.values(state.refs)) {
    const actual = observeFile(expected.path, Math.max(1, expected.sizeBytes), state.guard);
    if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error("TEST independently retained owner evidence changed");
  }
  state.guard();
}

async function phase<T>(state: OwnerState, name: string, action: () => T | Promise<T>): Promise<T> {
  state.phase = name; state.guard(); const began = performance.now();
  try { return await action(); }
  finally { state.costs[name] = performance.now() - began; }
}

async function initialCapture(state: OwnerState): Promise<void> {
  state.pipeline = await phase(state, "fresh-existing-production-capture", () => state.seams.capture(state.input.sourceRoot)
    .map(({ path: file, hash }) => ({ path: file, hash })));
  retain(state, "pipeline", state.pipeline);
  state.dependencies = await phase(state, "fresh-complete-installed-inventory", () => state.seams.dependencies(
    state.input.dependencies.roots, state.input.dependencies.tools, state.guard));
  retain(state, "dependencies", state.dependencies);
  state.startup = await phase(state, "fresh-initial-python-startup", () => startup(state, state.input.ownerDirectory));
  retain(state, "startup", state.startup); state.guard();
}

function startup(state: OwnerState, cwd: string): Promise<CapsulePythonStartup> {
  if (!state.dependencies) throw new Error("TEST owner has no independently captured dependencies");
  return ownedObservation(state, () => state.seams.startup({ dependencies: state.dependencies!, cwd, env: state.env,
    expiresAt: state.expiresAt, signal: state.input.signal }, state.guard));
}

function assertBuilt(state: OwnerState, receipt: CapsuleReceipt): void {
  if (!state.held || state.held.root !== path.join(state.input.ownerDirectory, "capsule/repo")
      || state.held.receiptPath !== path.join(state.input.ownerDirectory, "capsule/capsule.json")
      || receipt.root !== state.held.root || receipt.source.root !== state.input.sourceRoot) throw new Error("TEST built capsule escaped this new owner");
  if (byteHash(Buffer.from(JSON.stringify(receipt.dependencies))) !== state.refs.dependencies.sha256
      || byteHash(Buffer.from(JSON.stringify(receipt.source.pipeline))) !== state.refs.pipeline.sha256) {
    throw new Error("TEST actual capsule differs from independently captured pipeline/dependencies");
  }
  const raw = observeFile(state.held.receiptPath, RECORD_BYTES, state.guard);
  if (raw.sha256 !== state.held.receiptSha256) throw new Error("TEST actual capsule raw receipt hash changed");
  assertRetained(state);
}

async function build(state: OwnerState): Promise<void> {
  if (!state.pipeline) throw new Error("TEST owner has no fresh pipeline");
  state.held = await phase(state, "build-independent-capsule", () => state.seams.build({
    destination: path.join(state.input.ownerDirectory, "capsule"), source: { root: state.input.sourceRoot, pipeline: state.pipeline! },
    dependencies: state.input.dependencies }, state.guard));
  retain(state, "capsule-reference", state.held);
  const receipt = await phase(state, "built-capsule-readback", () => state.seams.verify(state.held!, state.guard));
  assertBuilt(state, receipt);
  state.refs["capsule-raw"] = observeFile(state.held.receiptPath, RECORD_BYTES, state.guard);
}

async function verifyCurrent(state: OwnerState, name: string): Promise<CapsuleReceipt> {
  if (!state.held) throw new Error("TEST owner has no separately held capsule; partial build is never adopted");
  return phase(state, name, async () => {
    const receipt = state.seams.verify(state.held!, state.guard); assertBuilt(state, receipt);
    // A forced/unknown prior child cannot authorize another startup, even for final observation.
    if (state.startupBlocked) { assertRetained(state); state.guard(); return receipt; }
    const actual = await startup(state, state.held!.root);
    if (byteHash(Buffer.from(JSON.stringify(actual))) !== state.refs.startup.sha256) throw new Error("TEST Python startup changed since initial capture");
    // Startup executes held import code; recheck all bytes after it, not just the selected startup files.
    const afterStartup = state.seams.verify(state.held!, state.guard); assertBuilt(state, afterStartup);
    assertRetained(state); state.guard(); return afterStartup;
  });
}

function retainProcessUncertainty(state: OwnerState, error: unknown, invocationBoundary = false): void {
  if (!(error instanceof CutPreviewProcessError)) { state.startupBlocked ||= invocationBoundary; return; }
  const details = error.details;
  if (details.groupStopped !== true || details.forcedStop !== false || details.timedOut !== false) state.startupBlocked = true;
}

async function ownedObservation<T>(state: OwnerState, action: () => Promise<T>): Promise<T> {
  try { return await action(); }
  catch (error) { retainProcessUncertainty(state, error, true); throw error; }
}

async function finalVerification(state: OwnerState): Promise<void> {
  if (state.held) {
    await verifyCurrent(state, state.startupBlocked ? "final-byte-only-verification" : "final-complete-verification"); return;
  }
  // A failed initial startup has no capsule to adopt; only independently held installation/evidence bytes exist.
  await phase(state, "final-initial-byte-only-verification", () => {
    if (!state.dependencies) throw new Error("TEST owner has no complete initial dependency observation");
    const actual = state.seams.dependencies(state.input.dependencies.roots, state.input.dependencies.tools, state.guard);
    if (byteHash(Buffer.from(JSON.stringify(actual))) !== state.refs.dependencies.sha256) throw new Error("TEST initial installed bytes changed");
    assertRetained(state); state.guard();
  });
}

function assertInvocation(state: OwnerState, invocation: ReturnType<typeof capsuleInvocation>): void {
  if (invocation.cwd !== state.held!.root || invocation.node !== state.input.dependencies.tools.node) throw new Error("TEST capsule invocation changed identity");
  for (const [key, value] of Object.entries(invocation.env)) {
    if (state.env[key] !== value) throw new Error("TEST controlled environment disagrees with capsule invocation");
  }
  state.guard();
}

function expectedControls(state: OwnerState, receipt: CapsuleReceipt) {
  const tools = state.input.dependencies.tools;
  const names = { SNIPER_NODE_PATH: tools.node, HYPERFRAMES_BROWSER_PATH: tools.browser,
    HYPERFRAMES_FFMPEG_PATH: tools.ffmpeg, HYPERFRAMES_FFPROBE_PATH: tools.ffprobe, SNIPER_DOCKER_PATH: tools.docker };
  const approval = receipt.files.find((row) => row.path === path.join(state.held!.root, APPROVAL));
  if (!approval) throw new Error("TEST copied image approval is absent from source authority");
  return { scope: "TEST-read-only-control-path-preflight-not-runtime-qualification",
    tools: Object.entries(names).map(([name, value]) => ({ name, configured: value, resolved: value })),
    socket: state.input.controls.dockerSocket, imageId: state.input.controls.imageId, imageApprovalSha256: approval.sha256,
    user: state.input.controls.user, runtimeRepoRoot: state.held!.root, dockerContacted: false, credentialsRead: false };
}

async function smoke(state: OwnerState): Promise<void> {
  const receipt = await verifyCurrent(state, "prelaunch-complete-verification");
  const invocation = state.seams.invocation(state.held!, state.guard); assertInvocation(state, invocation);
  await phase(state, "fixed-check-controls-smoke", async () => {
    const timeoutMs = Math.floor(Math.min(30_000, state.expiresAt - performance.now())); state.guard();
    if (timeoutMs < 1) throw new Error("TEST smoke has no original time remaining");
    const output = await ownedObservation(state, () => state.seams.run({ command: invocation.node, cwd: invocation.cwd, env: state.env,
      args: ["--import", "tsx", DRIVER, "--check-controls"], timeoutMs, signal: state.input.signal, trackForShutdown: true }));
    state.guard();
    if (output.stderr || Buffer.byteLength(output.stdout) > 64 * 1024) throw new Error("TEST control smoke has unsupported output");
    const actual = JSON.parse(output.stdout);
    if (JSON.stringify(actual) !== JSON.stringify(expectedControls(state, receipt))) throw new Error("TEST control smoke did not return the exact held controls");
    state.smoke = actual; retain(state, "check-controls-output", output);
  });
}

function failureDetails(error: unknown) {
  return { error: String(error).slice(0, 2000), process: error instanceof CutPreviewProcessError
    ? { timedOut: error.details.timedOut, groupStopped: error.details.groupStopped, forcedStop: error.details.forcedStop,
      exitCode: error.exitCode ?? null } : null };
}

function fail(state: OwnerState, work: unknown, verification: unknown): never {
  const failures: unknown[] = [work, verification].filter((error) => error !== undefined);
  const bytes = Buffer.from(JSON.stringify({ scope: SCOPE, phase: state.failurePhase ?? state.phase, verificationPhase: state.phase, work: failureDetails(work),
    finalVerification: verification === undefined ? (state.startupBlocked || !state.held ? "byte-only-passed" : "passed") : failureDetails(verification),
    subsequentStartupBlocked: state.startupBlocked, costs: state.costs,
    elapsedMs: performance.now() - state.began, deadlineExpired: performance.now() >= state.expiresAt,
    partialArtifactsRetained: true, automaticRetry: false, cleanupInferred: false, mediaGenerated: false }));
  // Tiny diagnostic retention is not renewed verification/work credit. It never replaces existing evidence.
  try { writeNewBytes(path.join(state.input.ownerDirectory, "failed.json"), bytes, () => {}); }
  catch (error) { failures.push(error); }
  throw new AggregateError(failures, "TEST capsule owner failed; partial evidence retained, no retry or inferred cleanup");
}

/** One 300s original clock. Captures fresh inputs itself; no caller-supplied prior receipt/project or media mode. */
export async function runTestCapsuleControlSmoke(input: CapsuleOwnerInput, overrides: Partial<CapsuleOwnerSeams> = {}) {
  const began = performance.now(), expiresAt = began + LIMIT_MS;
  input = { ...input, dependencies: { roots: { ...input.dependencies.roots }, tools: { ...input.dependencies.tools } }, controls: { ...input.controls } };
  const guard = () => { if (input.signal?.aborted || performance.now() >= expiresAt) throw new Error("TEST capsule owner original deadline expired or cancelled"); };
  const state: OwnerState = { input, seams: { ...DEFAULTS, ...overrides }, began, expiresAt, guard,
    phase: "new-only-owner", refs: {}, costs: {}, env: environment(input), startupBlocked: false };
  createOwner(input, guard);
  retain(state, "started", { scope: SCOPE, startedAt: new Date().toISOString(), originalBudgetMs: LIMIT_MS, mediaGenerated: false, automaticRetry: false });
  let work: unknown, verification: unknown;
  try { await initialCapture(state); await build(state); await smoke(state); }
  catch (error) { state.failurePhase = state.phase; retainProcessUncertainty(state, error); work = error ?? new Error("TEST work threw no error value"); }
  try { await finalVerification(state); }
  catch (error) { retainProcessUncertainty(state, error); verification = error ?? new Error("TEST final verification threw no error value"); }
  if (work !== undefined || verification !== undefined) return fail(state, work, verification);
  const result = { scope: SCOPE, state: "TEST-capsule-controls-smoke-passed", capsule: state.held!, independentlyHeld: { ...state.refs },
    costs: state.costs, elapsedMs: performance.now() - began, fullRuntimeQualified: false, mediaGenerated: false, humanApproved: false,
    hostOsDylibsClosed: false, hostileSameUserRollbackProtected: false };
  try { const evidence = retain(state, "result", result); assertRetained(state); guard(); return { ...result, evidence }; }
  catch (error) { return fail(state, error, undefined); }
}
