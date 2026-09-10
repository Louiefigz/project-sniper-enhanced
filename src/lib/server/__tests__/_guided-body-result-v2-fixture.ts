/** Real source2 approval/admission/activation and phase CAS; stopped/native and AV observations are explicit TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { bodyControllerSourcesFixture as bodyMediaInputAdmissionFixture } from "./_guided-body-controller-sources-fixture";
import { activateFreshGuidedBody } from "../guided-body-activation";
import { commitBodyPhase, readBodyPhase } from "../guided-body-phase";
import { bodyResultReads, readHeldBodyResult } from "../guided-body-result";
import { createOpeningRecord } from "../guided-opening-process-activation";
import { canonicalJsonSha256 as hash } from "../auto-edit-hash";
import { ownedProcessLedgerPath } from "../guided-opening-process-ledger";
import { bodySourceRawResult, bodySourceReadback } from "@/lib/producer/__tests__/_guided-body-result-v2-fixture";
import type { FreshBodyAdmission } from "../guided-body-claim";

function records(context: FreshBodyAdmission) {
  const held = activateFreshGuidedBody(context), a = held.activation, input = held.invocation.input;
  if (input.schemaVersion !== 2) throw new Error("TEST source2 required");
  const opening = JSON.parse(fs.readFileSync(input.references.openingResult.path, "utf8"));
  const raw = { ...bodySourceRawResult(), profile: input.profile, executionId: a.executionId, inputPath: a.inputPath,
    inputSha256: a.inputSha256, executionActivationPath: held.activationPath, executionActivationSha256: held.activationSha256,
    references: input.references, sourceColorReplay: input.sourceColorReplay };
  raw.sourceColorReadback.sourceColorEvidence = opening.sourceColorEvidence;
  const { receiptHash: _unused, ...body } = raw; void _unused;
  const result = createOpeningRecord(path.join(a.outputRoot, "body-result.json"), { ...body, receiptHash: hash(body) });
  const completion = { schemaVersion: 2, kind: "guided-body-media-completion", status: "complete", executionId: a.executionId,
    inputSha256: a.inputSha256, executionActivationSha256: held.activationSha256, receiptPath: result.path,
    receiptSha256: result.sha256, receiptHash: result.value.receiptHash, sourceColorReplay: input.sourceColorReplay,
    sourceColorReadback: raw.sourceColorReadback, bodyApproved: false, deliveryApproved: false };
  const root = path.dirname(held.activationPath), intent = createOpeningRecord(path.join(root, "body-media-process-intent.json"),
    { schemaVersion: 1, kind: "guided-body-process-intent", activationHash: held.activationHash, inputSha256: a.inputSha256,
      executionId: a.executionId, journalHash: held.current.sha256, startedAt: a.createdAt, tools: { TEST: "native selection not performed" } });
  fs.writeFileSync(ownedProcessLedgerPath(root, "media"), "TEST explicit stopped provenance leaf; never a ledger admission\n", { mode: 0o600, flag: "wx" });
  const output = createOpeningRecord(path.join(root, "body-media-process-result.json"), { schemaVersion: 1, kind: "guided-body-process-outcome",
    status: "complete", stdout: JSON.stringify(completion), activationHash: held.activationHash, intentSha256: intent.sha256 });
  commitBodyPhase({ held, current: held.current, phase: "process", references: {
    intent: { path: intent.path, sha256: intent.sha256 }, outcome: { path: output.path, sha256: output.sha256 } }, guard: context.budget.remainingMs });
  const phase = readBodyPhase(context.dir, "process"), stopped = { held: phase.held, intent, output, receipt: output.value,
    current: phase.current, nestedOwnership: "resolved-by-normal-return", ownershipUnresolved: false };
  return { phase, stopped, result, completion, readback: { ...bodySourceReadback(), ...completion,
    kind: "guided-body-media-readback", status: "verified" }, read: () => readHeldBodyResult(phase) };
}

/** Native/OS-only leaf: every result mint still runs actual admission, activation, raw ref and private lifetime checks. */
export async function bodyResultV2Fixture(t: TestContext) {
  const base = await bodyMediaInputAdmissionFixture(t);
  return { base, run: (operation: (f: ReturnType<typeof records>) => Promise<void>) => base.run(async ({ context }) => {
    const f = records(context);
    t.mock.method(bodyResultReads, "stopped", (phase: Parameters<typeof bodyResultReads.stopped>[0]) => {
      assert.equal(phase, f.phase); return f.stopped;
    });
    await operation(f);
  }) };
}

/** Only this fixture's literal body-result file may be replaced, never a source/tool/pipeline target. */
export function replaceBodyResultFile(f: Parameters<Awaited<ReturnType<typeof bodyResultV2Fixture>>["run"]>[0] extends (f: infer F) => unknown ? F : never): void {
  const root = fs.realpathSync(f.phase.held.admission.before.job.ctx.dir), file = f.result.path;
  assert.equal(file, path.join(f.phase.held.admission.execution, "body-media-output", "body-result.json"));
  assert(file.startsWith(path.join(root, "guided-v2-operations") + path.sep));
  assert.equal(fs.realpathSync(file), file); const stat = fs.lstatSync(file);
  assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const temp = path.join(path.dirname(file), `TEST-result-replacement-${randomUUID()}.json`);
  fs.writeFileSync(temp, fs.readFileSync(file), { mode: 0o600, flag: "wx" }); fs.renameSync(temp, file);
}
