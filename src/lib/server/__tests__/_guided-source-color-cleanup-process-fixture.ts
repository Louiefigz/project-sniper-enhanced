/** TEMP raw holds and ledger rows; native child/tool/journal admission are explicit TEST stubs. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { holdSourceColorCleanupReservation } from "../guided-source-color-cleanup-hold";
import { sourceColorRecoveryFixture } from "./_guided-source-color-resource-recovery-fixture";
import { sourceColorCleanupProcessDependencies, type SourceColorCleanupProcessInput } from "../guided-source-color-cleanup-process";
import { ownedProcessLedgerPath } from "../guided-opening-process-ledger";
import { parseCurrentOpeningCleanupResult, type OpeningCleanupResultV2 } from "../../producer/contracts/guided-opening-cleanup-v2";

function completion(input: SourceColorCleanupProcessInput): OpeningCleanupResultV2 {
  const { held, reservation } = input, stages = ["cleanup-claim-and-controls", "source-color-reservation-read",
    "cleanup-controls-after", "reconcile-source-color-batch", "source-color-reservation-after"];
  return parseCurrentOpeningCleanupResult({ schemaVersion: 2, kind: "guided-opening-cleanup-result", claimPath: held.claimPath,
    claimSha256: held.claimSha256, inputSha256: held.claim.inputSha256, outputRoot: held.claim.outputRoot, executionId: held.claim.executionId,
    cleanupVerified: true, graphics: [], elapsedMs: 4000, stages: stages.map(stage => ({ stage, status: "complete",
      elapsedMs: stage === "reconcile-source-color-batch" ? 3020 : 20 })), budgetScope: "separate-protected-cleanup-not-render-allowance",
    processGroupStopped: "requires-owned-server-observation", openingApproved: false,
    sourceColor: { reservation: reservation.reference.reservation, sourceColorHash: reservation.reference.sourceColorHash,
      batch: { schemaVersion: 1, kind: "grade-batch-cleanup-result", scope: "reserved-name-cleanup-not-process-settlement-work-or-approval",
        cleanupVerified: true, elapsedMs: 3010, stableAbsenceMs: 3000, passes: 14,
        jobs: reservation.containerNames.map(containerName => ({ containerName, inspections: 28, removalAttempts: 14,
          successfulRemovalResponses: 0, lastObservation: "absent", canonicalAbsenceProved: true })) } } }) as OpeningCleanupResultV2;
}

/** Write only one exact fixture-owned ledger; never follow paths read from dependencies. */
function ledgerRows(directory: string, script: string, incomplete = false): void {
  assert.equal(fs.realpathSync(directory), directory); assert.equal(fs.lstatSync(directory).uid, process.getuid!());
  const events = incomplete ? ["worker-started"] : ["worker-started", "worker-finished"];
  const rows = events.map((event, index) => JSON.stringify({ event, pid: process.pid, argv0: script, at: 1000 + index }));
  fs.writeFileSync(ownedProcessLedgerPath(directory, "cleanup"), rows.join("\n") + "\n", { flag: "wx", mode: 0o600 });
}

export function sourceColorCleanupProcessFixture(t: TestContext, f = sourceColorRecoveryFixture(t)) {
  const held = f.input.held, attemptId = randomUUID();
  const directory = path.join(path.dirname(held.claimPath), "cleanup-attempts", attemptId);
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  const reservation = holdSourceColorCleanupReservation({ held, reference: f.actual.sourceColor,
    resourceDir: f.staging.resource.resource, guard: f.input.projectGuard, remainingMs: f.input.remainingMs });
  const input: SourceColorCleanupProcessInput = { held, reservation, attemptId, guard: () => {}, remainingMs: () => 300_000 };
  const tools = { script: path.join(f.staging.root, "TEST-cleanup.py"), scriptHash: "a".repeat(64),
    runnerScript: path.join(f.staging.root, "TEST-runner.py"), runnerScriptHash: "b".repeat(64),
    python: "/TEST/python", pythonResolved: "/TEST/python", pythonHash: "c".repeat(64),
    venvRoot: "/TEST", venvConfig: "/TEST/pyvenv.cfg", venvConfigHash: "d".repeat(64) };
  const result = completion(input), calls: Parameters<typeof sourceColorCleanupProcessDependencies.invoke>[0][] = [];
  const events = { stoppedReads: 0, toolReads: 0, toolsChecked: 0, incomplete: false, afterInvoke: () => {} };
  const dependencies = { ...sourceColorCleanupProcessDependencies, tools: () => { events.toolReads++; return tools; },
    stopped: () => { events.stoppedReads++; return structuredClone(f.actual); },
    toolsUnchanged: () => { events.toolsChecked++; }, invoke: async (request: (typeof calls)[number]) => {
      calls.push(request); request.remainingMs(); ledgerRows(directory, tools.script, events.incomplete); events.afterInvoke();
      return { stdout: JSON.stringify(result), stderr: "TEST code-only cleanup output" };
    } };
  return { ...f, input, directory, tools, result, calls, events, dependencies };
}
