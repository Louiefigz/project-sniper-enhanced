import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { test } from "node:test";
import ts from "typescript";
import { hasGuidedBootstrap } from "../guided-project-bootstrap-contract";
import { AuthoredPreparationDeadlineError } from "../guided-project-preparation-deadline";

const SOURCE = readFileSync("src/app/api/producer/auto-edit/worker.ts", "utf8");
const AST = ts.createSourceFile("worker.ts", SOURCE, ts.ScriptTarget.Latest, true);

/** Execute exact selected worker functions with only TEST callbacks, never worker main imports. */
function functions(names: string[], dependencies: Record<string, unknown>): Record<string, (...args: unknown[]) => unknown> {
  const declarations = AST.statements.filter(node => ts.isFunctionDeclaration(node) && names.includes(node.name?.text ?? ""));
  assert.equal(declarations.length, names.length);
  const source = declarations.map(node => node.getText(AST)).join("\n") + `\nglobalThis.TEST = {${names.join(",")}};`;
  const context = { ...dependencies, TEST: {} };
  runInNewContext(ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context);
  return context.TEST;
}

test("actual worker claims parent ownership before clock and keeps lease/settlement inside it", async () => {
  const events: string[] = [], current = { ctx: { dir: "TEST" }, token: "TEST", attempts: 1 };
  const execute = (run: () => Promise<void>) => run();
  const worker = functions(["runWorker", "runClaimedWorker"], {
    claimJob: async () => { events.push("claim"); return current; },
    withAuthoredPreparationDeadline: async (job: unknown, expire: () => void, run: () => Promise<void>) => {
      assert.equal(job, current); events.push("clock"); expire(); await run(); events.push("clock-cleared");
    },
    withStageTimingContext: (_context: unknown, run: () => Promise<void>) => execute(run),
    timedStage: (_dir: string, _stage: string, run: () => Promise<void>) => execute(run),
    withWorkerMutationLease: async (_job: unknown, run: (lease: unknown) => Promise<void>) => {
      events.push("lease-wait"); await run({ TEST: true }); events.push("lease-settled");
    },
    runBootstrapWorker: async (_job: unknown, _lease: unknown, run: () => Promise<void>) => {
      events.push("bootstrap"); await run(); events.push("bootstrap-settled");
    },
    runOwnedWorker: async () => { events.push("owned-work"); },
  });
  await worker.runWorker("TEST-path", "TEST", (job: unknown) => { assert.equal(job, current); events.push("expiry-callback"); });
  assert.deepEqual(events, ["claim", "clock", "expiry-callback", "lease-wait", "bootstrap", "owned-work", "bootstrap-settled", "lease-settled", "clock-cleared"]);
});

test("actual handoff fallback refuses authored cuts while legacy self-adoption is unchanged", async () => {
  let adopted = 0;
  const current = { ctx: { authoredCut: { TEST: true } }, token: "TEST", status: "running" };
  const worker = functions(["claimJob"], { readAutoEditJob: () => current, delay: async () => {},
    process: { pid: 123 }, durableProcessGroupAlive: () => false, hasGuidedBootstrap,
    markAutoEditWorker: () => { adopted++; return current; } });
  await assert.rejects(Promise.resolve(worker.claimJob("TEST", "TEST")), /exact parent ownership handoff/);
  assert.equal(adopted, 0);
  delete (current.ctx as { authoredCut?: unknown }).authoredCut;
  assert.equal(await worker.claimJob("TEST", "TEST"), current); assert.equal(adopted, 1);
});

test("actual main expiry records deadline and unknown cleanup before existing SIGTERM shutdown", async () => {
  const events: string[] = [], payloads: Record<string, unknown>[] = [];
  const current = { ctx: { dir: "TEST", authoredCut: { TEST: true } }, token: "TEST", status: "running", phase: "authoring", checkpoint: "queued" };
  const worker = functions(["main", "markPreparationExpired", "markInterrupted"], {
    process: { argv: ["TEST-node", "TEST-worker", "TEST-path", "TEST"], pid: 123, once: () => {} },
    console: { error: () => {} }, TRACKED_TREE_GRACE_MS: 4000, AUTHORED_PREPARATION_LIMIT_MS: 7_200_000,
    runWorker: async (_path: unknown, _token: unknown, expire: (job: unknown) => void) => { expire(current); },
    readAutoEditJob: () => current, hasGuidedBootstrap, boundAutoEditLog: () => {},
    authoredPreparationRemainingMs: () => { throw new AuthoredPreparationDeadlineError("expired"); },
    retainBootstrapFailure: (_dir: string, message: string, cleanup: unknown) => {
      events.push(message.includes("PREPARATION") ? "deadline-unknown" : "signal-unknown");
      assert.equal(JSON.stringify(cleanup), '{"verified":false,"forcedStop":true}');
    },
    appendAutoEditJobEvent: (_path: string, _token: string, payload: Record<string, unknown>) => { payloads.push(payload); },
    interruptAutoEditJob: () => events.push("interrupt-job"), interruptProducerRun: () => events.push("interrupt-run"),
    terminateTrackedProcessTrees: () => events.push("stop-tracked"),
    setTimeout: (callback: () => void, delay: number) => {
      assert.equal(typeof callback, "function"); assert.equal(delay, 4250); events.push("existing-shutdown-timer");
    },
    terminateOwnProcessGroup: () => assert.fail("TEST must never execute shutdown"),
  });
  await worker.main();
  assert.deepEqual(events, ["deadline-unknown", "signal-unknown", "interrupt-job", "interrupt-run", "stop-tracked", "existing-shutdown-timer"]);
  assert.equal(payloads[0].event, "authored_preparation_deadline"); assert.equal(payloads[0].retryable, false);
  assert.match(String(payloads[0].message), /PREPARATION expired/); assert.equal(payloads[1].signal, "SIGTERM");
});

test("retention publication failures still reach existing shutdown with no cleanup success claim", () => {
  const events: string[] = [];
  const worker = functions(["markPreparationExpired"], {
    authoredPreparationRemainingMs: () => { throw new AuthoredPreparationDeadlineError("clock-invalid"); },
    retainBootstrapFailure: () => { events.push("retain-failed"); throw new Error("TEST publication failure"); },
    console: { error: () => events.push("explicit-unknown") }, AUTHORED_PREPARATION_LIMIT_MS: 7_200_000,
    appendAutoEditJobEvent: (_path: string, _token: string, payload: Record<string, unknown>) => {
      events.push("deadline-event"); assert.equal(payload.cleanup, "unknown");
    },
  });
  worker.markPreparationExpired("TEST", "TEST", { ctx: { dir: "TEST" } });
  events.push("owner-can-request-stop");
  assert.deepEqual(events, ["retain-failed", "explicit-unknown", "deadline-event", "owner-can-request-stop"]);
});
