/** Actual TEMP launch records, parsed journal and lease. Proposal/native admission remain explicit TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import childProcess from "node:child_process";
import { randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { guidedFixture } from "@/lib/producer/__tests__/_guided-cut-fixture";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { autoEditJobPath } from "../auto-edit-job-persistence";
import { acquireProjectMutationLease } from "../project-mutation-lease";
import { createOpeningLaunchRecord, openingLaunchDirectory, readOpeningLaunchIntent,
  readOpeningLaunchActivation } from "../guided-opening-launch-store";
import { captureOpeningAttemptStart } from "../opening-deadline";
import { captureProcessIdentity } from "../process-liveness";
import { holdOpeningControllerLifecycle } from "../guided-opening-controller-lifecycle";
import type { OpeningExecutionInput } from "../guided-opening-execution";
import { GUIDED_SOURCE_COLOR_TS_FILES } from "../guided-source-color-staging";
import type { GuidedSourceColorV1 } from "@/lib/producer/contracts/guided-source-color-v1";

interface LaunchOptions {
  sourceColor?: GuidedSourceColorV1; origin?: { clockHash: string; startedAt: string }; requestId?: string; token?: string;
}

/** Same explicit TEST OS identity as the real TEMP lease; no controller or worker is started. */
export function launchOpeningControllerFixture(dir: string, before: string, options: LaunchOptions = {}) {
  const hash = "a".repeat(64), at = options.origin?.startedAt ?? new Date().toISOString();
  const origin = options.origin ?? { clockHash: hash, startedAt: at }, version = options.sourceColor ? 2 : 1;
  const names = ["guided-opening-launch-store.ts", "guided-opening-launcher.ts", "guided-opening-controller.ts",
    "guided-opening-execution.ts", "opening-handoff-clock.ts"].map(name => `src/lib/server/${name}`);
  if (options.sourceColor) names.push(...GUIDED_SOURCE_COLOR_TS_FILES);
  const intent = { schemaVersion: version, kind: "guided-opening-launch-intent", dir, launchId: randomUUID(), origin,
    submission: { schemaVersion: version, operation: "prepare-guided-opening", idempotencyKey: options.requestId ?? randomUUID(),
      expectedToken: options.token ?? "guided-job", expectedJournalHash: before, proposalReadinessHash: hash,
      treatmentDraftRevisionHash: hash, ...(options.sourceColor ? { sourceColor: options.sourceColor } : {}) }, receivedAt: at,
    controllerFiles: [...new Set(names)].map(name => ({ path: name, sha256: hash })) };
  const root = openingLaunchDirectory(dir, before, true); createOpeningLaunchRecord(root, "intent.json", intent);
  const held = readOpeningLaunchIntent(dir, before)!;
  const captured = captureOpeningAttemptStart({ wall: () => Date.parse(at), monotonic: () => 0 }), budget = captured.start(origin);
  const activationHash = createOpeningLaunchRecord(root, "activation.json", { schemaVersion: 1, kind: "guided-opening-controller-activation",
    intentHash: held.hash, owner: captureProcessIdentity(process.pid), handoff: { receivedAt: at, admission: budget.admission, observation: budget.observe() } });
  const active = readOpeningLaunchActivation(held)!;
  createOpeningLaunchRecord(root, "released.json", { schemaVersion: 1, intentHash: held.hash, activationHash });
  createOpeningLaunchRecord(root, "controller-started.json", { schemaVersion: 1, intentHash: held.hash,
    activationHash, owner: active.activation.owner, startedAt: at });
  return { held, active };
}

/** Optional original release behavior tests uncertainty without acquiring or deleting any real workspace lock. */
export function mockOpeningControllerIdentity(t: TestContext): void {
  t.mock.method(childProcess, "spawnSync", ((command: string) => {
    if (!["/usr/sbin/sysctl", "/bin/ps"].includes(command)) throw new Error("TEST forbids native subprocesses");
    return { status: 0, stdout: command.endsWith("sysctl") ? "{ sec = 42, usec = 0 }" : "TEST original process start", stderr: "" };
  }) as typeof childProcess.spawnSync);
}

/** Original actual TEMP lock protocol; only operating-system identity discovery is an explicit TEST leaf. */
export function openingControllerLifecycleFixture(t: TestContext, releaseMode: "actual" | "noop" | "throw" = "actual") {
  mockOpeningControllerIdentity(t);
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "opening-controller-lifecycle-")));
  const owned: { release?: () => void } = {};
  t.after(() => { owned.release?.(); fs.rmSync(root, { recursive: true, force: true }); });
  const base = guidedFixture(root), dir = base.ctx.dir; fs.chmodSync(dir, 0o700);
  const before = observeHumanCutJob(dir), records = launchOpeningControllerFixture(dir, before.sha256);
  const acquired = acquireProjectMutationLease(root, "TEST original controller lifecycle"); assert(acquired.lease);
  const lease = acquired.lease, release = lease.release; owned.release = release; let releases = 0;
  lease.release = () => { releases++; if (releaseMode === "throw") throw new Error("TEST release uncertainty"); if (releaseMode === "actual") release(); };
  const guard = cutPreviewLeaseGuard(dir, lease), owner = { launch: records.held, activation: records.active, lease };
  const lifecycle = holdOpeningControllerLifecycle(owner), executionId = randomUUID();
  const directory = path.join(dir, "guided-v2-operations", records.held.intent.submission.idempotencyKey, "executions", executionId);
  const input = { proposal: { ...before, clock: { hash: records.held.intent.origin.clockHash }, generationStartedAt: records.held.intent.origin.startedAt },
    operation: { executionId, execution: directory, record: { submission: records.held.intent.submission } },
    invocation: { inputPath: path.join(directory, "media-input/input.json"), inputSha256: "b".repeat(64),
      input: { executionId, executionInputHash: "c".repeat(64) } }, lease, remainingMs: () => 1000,
    budgetAdmissionHash: "d".repeat(64) } as unknown as OpeningExecutionInput;
  return { root, dir, before, records, owner, lease, lifecycle, input, guard, releases: () => releases };
}

/** Replace only the exact original TEST journal, never any tool, source or dynamically selected dependency. */
export function replaceLifecycleJournal(f: ReturnType<typeof openingControllerLifecycleFixture>): void {
  const file = autoEditJobPath(f.dir); assert(file.startsWith(fs.realpathSync(f.root) + path.sep));
  assert.equal(fs.realpathSync(file), file); assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const temporary = path.join(path.dirname(file), `TEST-lifecycle-${randomUUID()}.json`);
  fs.writeFileSync(temporary, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}
