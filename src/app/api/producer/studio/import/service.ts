import path from "node:path";
import { randomUUID } from "node:crypto";
import { guardProjectMutation, mutationProjectRoot } from "../../../_lib/project-mutation";
import { savePlanTransaction } from "../../save-plan/transaction";
import { clearTemplateUsageApproval } from "@/lib/server/template-usage-approval";
import type { EditPlan } from "@/lib/producer/edit-plan";
import { IMPORT_CAVEAT, ImportError, type ApplyInput, type Capture, type ImportApplied, type ImportPrepared,
  type OriginalSession, type Proposal } from "./model";
import { createProposal, createSession, jsonText, readProposal, readSession, readText, seal, sha, writeHead } from "./files";
import { assertCaptureCurrent, stableCapture } from "./authority";
import { inspectDiff, reconstructOriginal } from "./bridge";
import { assertCandidate, assertNoRefit, assertStableIds, chainTip, pendingChanges, planVersion } from "./chain";

export const importDependencies = {
  capture: stableCapture, recheck: assertCaptureCurrent, baseline: reconstructOriginal, diff: inspectDiff,
  save: savePlanTransaction, invalidate: clearTemplateUsageApproval,
  guard: (dir: string) => guardProjectMutation({ projectRoot: mutationProjectRoot(dir), producerDir: dir,
    operation: "reviewing/applying Studio draft changes" }),
};
export type ImportDependencies = typeof importDependencies;

async function sessionFor(dir: string, capture: Capture, deps: ImportDependencies): Promise<OriginalSession> {
  const found = readSession(dir);
  if (found) return found;
  const originalPlan = JSON.parse(capture.planText) as EditPlan;
  assertStableIds(originalPlan); planVersion(originalPlan);
  const baseline = await deps.baseline(dir);
  deps.recheck(dir, capture);
  const session = seal({ schema: 1 as const, dir, originalPlan, originalPlanText: capture.planText,
    originalPlanHash: capture.planHash, authority: capture.authority, manifestText: capture.manifestText, ...baseline });
  createSession(dir, session);
  return session;
}

function assertParents(session: OriginalSession, capture: Capture): void {
  if (session.authority !== capture.authority || session.manifestText !== capture.manifestText) {
    throw new ImportError("Original Studio source, manifest, project or base authority changed; preserve edits and start an explicitly new review session");
  }
}

function prepared(proposal: Proposal): ImportPrepared {
  return { ok: true, state: "ready", proposalId: proposal.id, expectedPlanHash: proposal.beforeHash,
    expectedPlanVersion: proposal.beforeVersion, changes: proposal.changes, blockers: [], warnings: proposal.warnings, caveat: IMPORT_CAVEAT };
}

async function prepareLocked(dir: string, deps: ImportDependencies): Promise<ImportPrepared> {
  assertNoRefit(dir);
  const capture = await deps.capture(dir);
  const session = await sessionFor(dir, capture, deps);
  assertParents(session, capture);
  const { tip, pending } = chainTip(dir, session, capture.planHash);
  if (pending && tip?.capture.snapshot === capture.snapshot) return prepared(tip);
  const before = JSON.parse(capture.planText) as EditPlan;
  const base = { ok: true as const, proposalId: null, expectedPlanHash: capture.planHash,
    expectedPlanVersion: planVersion(before), changes: [], blockers: [], warnings: [], caveat: IMPORT_CAVEAT };
  const result = await deps.diff(dir, session, capture);
  deps.recheck(dir, capture);
  if (result.blockers.length) return { ...base, state: "blocked", blockers: result.blockers, warnings: result.warnings };
  assertCandidate(JSON.parse(session.originalPlanText), result.candidate);
  assertCandidate(before, result.candidate);
  const candidate = { ...result.candidate, planVersion: planVersion(before) + 1 };
  if (!Number.isSafeInteger(candidate.planVersion)) throw new ImportError("Plan version exhausted its safe integer range");
  const changes = pendingChanges(before, candidate);
  if (!changes.length) return { ...base, state: "unchanged", warnings: result.warnings };
  const candidateText = jsonText(candidate);
  const previous = pending ? tip?.previous ?? null : tip?.id ?? null;
  const proposal = seal({ schema: 1 as const, id: randomUUID(), sessionDigest: session.digest, previous,
    beforeHash: capture.planHash, beforeVersion: planVersion(before), afterHash: sha(candidateText),
    afterVersion: candidate.planVersion, candidate, candidateText, capture, changes, warnings: result.warnings });
  createProposal(dir, proposal);
  return prepared(proposal);
}

function applied(proposal: Proposal, replay: boolean): ImportApplied {
  return { ok: true, applied: !replay, alreadyApplied: replay, planVersion: proposal.afterVersion,
    planHash: proposal.afterHash, requiresRender: true, studioEditsPreserved: true, warnings: proposal.warnings };
}

function checkRequest(input: ApplyInput, proposal: Proposal): void {
  if (input.expectedPlanHash !== proposal.beforeHash || input.expectedPlanVersion !== proposal.beforeVersion) {
    throw new ImportError("The requested Studio proposal does not match the reviewed plan binding");
  }
}

async function applyLocked(dir: string, input: ApplyInput, deps: ImportDependencies): Promise<ImportApplied> {
  assertNoRefit(dir);
  const proposal = readProposal(dir, input.proposalId); checkRequest(input, proposal);
  const session = readSession(dir);
  if (!session || session.digest !== proposal.sessionDigest) throw new ImportError("Studio proposal has no matching original session");
  const capture = await deps.capture(dir); assertParents(session, capture);
  const { tip, pending } = chainTip(dir, session, capture.planHash);
  if (tip?.id === proposal.id && !pending) {
    try { deps.invalidate(dir); }
    catch (error) {
      const failure = new ImportError((error as Error).message, 502, "STUDIO_IMPORT_FINALIZATION_FAILED");
      failure.committed = true; throw failure;
    }
    return applied(proposal, true);
  }
  // A fresh reviewed proposal can supersede an unsaved intent only while
  // the exact before-SHA proves that intent never committed. Keep its file.
  const parent = pending ? tip?.previous ?? null : tip?.id ?? null;
  if (capture.planHash !== proposal.beforeHash || parent !== proposal.previous) {
    throw new ImportError("Studio proposal is stale; prepare the pending changes again");
  }
  if (capture.snapshot !== proposal.capture.snapshot) throw new ImportError("Studio changed since this proposal was reviewed; prepare changes again");
  const result = await deps.diff(dir, session, capture);
  if (result.blockers.length) throw new ImportError(result.blockers.join("; "));
  assertCandidate(JSON.parse(session.originalPlanText), result.candidate);
  assertCandidate(JSON.parse(capture.planText), result.candidate);
  if (jsonText({ ...result.candidate, planVersion: proposal.afterVersion }) !== proposal.candidateText) throw new ImportError("Studio candidate changed since review");
  deps.recheck(dir, capture); assertNoRefit(dir);
  writeHead(dir, proposal);
  try {
    await deps.save({ filePath: path.join(dir, "edit_plan.json"),
      plan: { ...proposal.candidate, planVersion: proposal.beforeVersion }, timebase: "full-plan" });
    if (sha(readText(path.join(dir, "edit_plan.json"))) !== proposal.afterHash) throw new ImportError("Saved draft does not match the intended Studio candidate");
    deps.invalidate(dir);
    return applied(proposal, false);
  } catch (error) {
    const failure = error instanceof ImportError ? error : new ImportError((error as Error).message, 502, "STUDIO_IMPORT_SAVE_FAILED");
    failure.committed = sha(readText(path.join(dir, "edit_plan.json"))) === proposal.afterHash;
    throw failure;
  }
}

export async function prepareImport(dir: string, deps = importDependencies): Promise<ImportPrepared | Response> {
  const guarded = deps.guard(dir); if (guarded.response) return guarded.response;
  try { return await prepareLocked(dir, deps); } finally { guarded.lease.release(); }
}

export async function applyImport(dir: string, input: ApplyInput, deps = importDependencies): Promise<ImportApplied | Response> {
  const guarded = deps.guard(dir); if (guarded.response) return guarded.response;
  try { return await applyLocked(dir, input, deps); } finally { guarded.lease.release(); }
}
