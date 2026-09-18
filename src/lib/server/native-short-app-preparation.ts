/** App-only preparation under the same durable project/checkpoint mutation lease. */
import { lstatSync } from "node:fs";
import { NextResponse } from "next/server";
import { guardProjectMutation, type CheckpointVerification } from "@/app/api/_lib/project-mutation";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { storedAutoEditIntent } from "@/app/api/producer/auto-edit/operator-intent-authority";
import { autoEditJobPath } from "./auto-edit-job-persistence";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import { prepareGuidedNativeShortRequest } from "./guided-native-authority";
import { prepareNativeShortRequest } from "./native-short-request";

interface Dependencies {
  guard: typeof guardProjectMutation;
  guided: typeof prepareGuidedNativeShortRequest;
}

function observeJournal(dir: string) {
  try { lstatSync(autoEditJobPath(dir)); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
  return observeHumanCutJob(dir);
}

class NativeCheckpointChanged extends Error {}

function assertJournalCurrent(dir: string, expected: ReturnType<typeof observeJournal>): void {
  if (observeJournal(dir)?.sha256 !== expected?.sha256) {
    throw new NativeCheckpointChanged("Guided checkpoint changed during native Short preparation; prepare again from the current state");
  }
}

/** The body supplies only a directory; all authority/capability fields come from stored state. */
export function prepareNativeShortAppRequest(input: { dir: string; root: string }, overrides: Partial<Dependencies> = {}): Response {
  const { dir, root } = input, deps = { guard: guardProjectMutation, guided: prepareGuidedNativeShortRequest, ...overrides };
  const observed = observeJournal(dir), guided = Boolean(observed?.job.ctx.workflowV2);
  const checkpointVerification: CheckpointVerification | undefined = guided ? {
    workflowVersion: 2, action: "compile-post-cut-proposal", expectedStatus: "treatment_admitted",
    expectedToken: observed!.job.token, expectedJournalHash: observed!.sha256,
  } : undefined;
  const guarded = deps.guard({ projectRoot: root, producerDir: dir, operation: "preparing a native Short brief",
    ...(checkpointVerification ? { checkpointVerification } : {}) });
  if (guarded.response) return guarded.response;
  try {
    const leaseGuard = cutPreviewLeaseGuard(dir, guarded.lease);
    leaseGuard(); assertJournalCurrent(dir, observed);
    const result = guided ? deps.guided(dir) : prepareNativeShortRequest({ producerDir: dir,
      intent: storedAutoEditIntent(dir), repo: process.cwd() });
    leaseGuard(); assertJournalCurrent(dir, observed);
    return NextResponse.json(result);
  } catch (error) {
    if (error instanceof NativeCheckpointChanged) return NextResponse.json({ error: error.message,
      code: "NATIVE_SHORT_CHECKPOINT_CHANGED", retryable: true }, { status: 409 });
    throw error;
  } finally { guarded.lease.release(); }
}
