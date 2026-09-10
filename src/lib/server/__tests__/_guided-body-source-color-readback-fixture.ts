/** Real pinned admission/activation/process/cleanup/candidate protocol; only readiness, tool selection, runtime and native run are TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import type { TestContext } from "node:test";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { bodyControllerSourcesFixture } from "./_guided-body-controller-sources-fixture";
import { bodyReadbackProtocol, publishBodyTestFile, publishBodyTestLedger, type TestBodyTools } from "./_guided-body-source-color-readback-records";
import { bodyProcessToolLeaves, type BodyChildPurpose } from "../guided-body-process-tools";
import { bodyReadbackReads, qualifyGuidedBodyUnderLease } from "../guided-body-readback";
import { activateFreshGuidedBody } from "../guided-body-activation";
import { OWNED_PROCESS_LEDGER_ENV } from "../guided-opening-process-ledger";
import { observeHumanCutJob } from "../human-cut-acceptance-store";

/** These NEW files are not original pipeline pins. Actual tool-byte verification runs, but no file is executable proof. */
function inertTools(root: string): TestBodyTools {
  const directory = path.join(root, "TEST-body-readback-tools"), venvRoot = path.join(directory, "venv");
  const files = { python: path.join(venvRoot, "bin", "python"), venvConfig: path.join(venvRoot, "pyvenv.cfg"),
    runner: path.join(directory, "process_runner.py"), media: path.join(directory, "guided_body_media.py"),
    cleanup: path.join(directory, "guided_body_cleanup.py"), read: path.join(directory, "guided_body_read.py") };
  for (const [name, file] of Object.entries(files)) publishBodyTestFile(file, `TEST inert ${name}; no execution\n`);
  const rawHash = (file: string) => observeCutPreviewFile(file, 1024).sha256;
  const common = { python: files.python, pythonResolved: fs.realpathSync(files.python), pythonHash: rawHash(files.python),
    venvRoot, venvConfig: files.venvConfig, venvConfigHash: rawHash(files.venvConfig),
    runnerScript: files.runner, runnerScriptHash: rawHash(files.runner) };
  return Object.fromEntries((["media", "cleanup", "read"] as const).map(purpose => [purpose,
    Object.freeze({ ...common, script: files[purpose], scriptHash: rawHash(files[purpose]) })])) as TestBodyTools;
}

type Protocol = ReturnType<typeof bodyReadbackProtocol>;
type Base = Awaited<ReturnType<typeof bodyControllerSourcesFixture>>;

/** Real invoker forms argv/env/timing; this exact native leaf emits no child, only TEST stdout and a parsed ledger. */
function nativeReadLeaf(input: Parameters<typeof bodyProcessToolLeaves.run>[0], protocol: Protocol, tools: TestBodyTools): { stdout: string; stderr: string } {
  const held = protocol.cleanup.held, a = held.activation, root = path.dirname(held.activationPath);
  assert.equal(input.command, tools.read.python); assert.equal(input.purpose, "guided-body");
  assert.deepEqual(input.args.slice(0, 4), [tools.read.runnerScript, tools.read.script, a.inputPath, a.outputRoot]);
  assert(input.timeoutMs > 0 && input.timeoutMs <= 3_300_000);
  const ledger = input.env[OWNED_PROCESS_LEDGER_ENV]; assert.equal(typeof ledger, "string");
  const directory = path.dirname(ledger!), relative = path.relative(path.join(root, "body-readback-attempts"), directory);
  assert.match(relative, /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/u);
  assert.equal(path.basename(ledger!), "owned-process-ledger.read.jsonl");
  assert.equal(fs.realpathSync(directory), directory);
  publishBodyTestLedger(directory, "read", tools.read.script);
  return { stdout: JSON.stringify(protocol.readback), stderr: "TEST native/AV qualification was not performed" };
}

/** Tool/native leaves retain exact fixture identity and reject any unplanned media or cleanup invocation. */
function installLeaves(t: TestContext, base: Base, tools: TestBodyTools) {
  const calls: Array<Parameters<typeof bodyProcessToolLeaves.run>[0]> = [];
  const state: { protocol?: Protocol } = {};
  t.mock.method(bodyProcessToolLeaves, "select", (held: Parameters<typeof bodyProcessToolLeaves.select>[0], purpose: BodyChildPurpose) => {
    assert.equal(held.controlJob.ctx.dir, base.f.request.dir); return tools[purpose];
  });
  t.mock.method(bodyProcessToolLeaves, "runtime", (runtime: Parameters<typeof bodyProcessToolLeaves.runtime>[0]) => {
    assert.deepEqual(runtime, base.f.selected.held.claim.runtime); return { TEST_BODY_RUNTIME: "not admitted" };
  });
  t.mock.method(bodyProcessToolLeaves, "run", async (input: Parameters<typeof bodyProcessToolLeaves.run>[0]) => {
    assert(state.protocol, "TEST only the prepared readback may reach the native leaf");
    calls.push(input); return nativeReadLeaf(input, state.protocol, tools);
  });
  t.mock.method(bodyReadbackReads, "readiness", (dir: string) => {
    assert.equal(dir, base.f.request.dir); return { ...base.f.proposal, ...observeHumanCutJob(dir) };
  });
  return { state, calls };
}

/** No sealed predecessor is modified. Every test gets genuine fresh pins, two predecessor CASes and an actual candidate route. */
export async function bodySourceReadbackFixture(t: TestContext) {
  const base = await bodyControllerSourcesFixture(t), tools = inertTools(base.root), leaves = installLeaves(t, base, tools);
  return { root: base.root, async run<T>(operation: (value: { protocol: Protocol; context: Parameters<Parameters<Base["run"]>[0]>[0]["context"];
    calls: typeof leaves.calls; qualify: () => ReturnType<typeof qualifyGuidedBodyUnderLease> }) => Promise<T>) {
    return base.run(async ({ context }) => {
      const held = activateFreshGuidedBody(context), protocol = bodyReadbackProtocol(context, held, tools);
      leaves.state.protocol = protocol;
      return operation({ protocol, context, calls: leaves.calls, qualify: () => qualifyGuidedBodyUnderLease({
        dir: context.dir, lease: context.lease, remainingMs: context.budget.remainingMs }) });
    });
  } };
}
