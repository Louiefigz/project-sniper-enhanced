/** Explicit TEST decision and native reply over actual TEMP selection/approval records; no human or media qualification. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { GUIDED_OPENING_APPROVAL_ATTESTATIONS, parseGuidedOpeningApprovalSubmission } from "@/lib/producer/contracts/guided-opening-approval-v1";
import { readSelectedOpeningMedia } from "../guided-opening-selection";
import { approveSourceColorOpeningUnderLease, sourceColorApprovalDependencies } from "../guided-source-color-approval";
import { sourceColorReadbackDependencies, verifyCleanedSourceColorOpeningMediaUnderLease } from "../guided-source-color-readback";
import { sourceColorSelectionFixture, type SourceColorSelectionFixture } from "./_guided-source-color-selection-fixture";

/** Both actions are new actual protocol operations; the TEST decision is never attributed to the user. */
export async function sourceColorApprovalFixture(t: TestContext, original?: SourceColorSelectionFixture) {
  const f = original ?? await sourceColorSelectionFixture(t), selection = f.select(), selected = readSelectedOpeningMedia(f.input.dir);
  assert.equal(selected.selectionHash, selection.selectionHash);
  const submission = parseGuidedOpeningApprovalSubmission({ schemaVersion: 1, operation: "approve-guided-opening", idempotencyKey: randomUUID(),
    expectedToken: selected.observed.job.token, expectedJournalHash: selected.observed.sha256, selectionHash: selected.selectionHash,
    coreMediaSha256: selected.rows.core.mediaSha256, reviewMediaSha256: selected.rows.review.mediaSha256,
    attestation: Object.fromEntries(GUIDED_OPENING_APPROVAL_ATTESTATIONS.map(name => [name, true])) });
  const end = performance.now() + 30_000, callbacks = { remaining: () => {}, beforeVerify: () => {}, afterVerify: () => {} };
  const calls = { remaining: 0, verifier: 0, native: 0 };
  const input = { dir: f.input.dir, selected, submission, lease: f.projectLease,
    remainingMs: () => { calls.remaining++; callbacks.remaining(); return Math.max(0, Math.floor(end - performance.now())); } };
  t.mock.method(sourceColorApprovalDependencies, "verify", async (request: Parameters<typeof sourceColorApprovalDependencies.verify>[0]) => {
    calls.verifier++; callbacks.beforeVerify();
    const verified = await verifyCleanedSourceColorOpeningMediaUnderLease(request, {
      readiness: () => undefined as unknown as ReturnType<typeof sourceColorReadbackDependencies.readiness>, tools: () => f.media.tools.read,
      invoke: async invocation => {
        invocation.remainingMs(); invocation.beforeSpawn?.(); calls.native++;
        const reply = { stdout: JSON.stringify(f.verified.result), stderr: "TEST approval native read stub, not real listening or replay" };
        invocation.afterSettled?.({ ...reply, timedOut: false, groupStopped: true, forcedStop: false }); return reply;
      },
    });
    callbacks.afterVerify(); return verified;
  });
  const files = { core: selected.rows.core.path, review: selected.rows.review.path, archive: f.recorded.fact.archive.path };
  return { ...f, input, selected, callbacks, calls, files, approve: () => approveSourceColorOpeningUnderLease(input) };
}
export type SourceColorApprovalFixture = Awaited<ReturnType<typeof sourceColorApprovalFixture>>;

/** Exact original TEMP targets only; this cannot follow an implementation inventory to a real source/tool. */
export function replaceApprovalFixtureFile(f: SourceColorApprovalFixture, role: keyof SourceColorApprovalFixture["files"]): void {
  const file = f.files[role], root = fs.realpathSync(f.staging.root);
  assert(file.startsWith(root + path.sep)); assert.equal(fs.realpathSync(file), file);
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const temporary = path.join(path.dirname(file), `TEST-approval-${randomUUID()}.json`);
  fs.writeFileSync(temporary, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}
