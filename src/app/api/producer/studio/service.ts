import { guardProjectMutation, mutationProjectRoot } from "../../_lib/project-mutation";
import { assertStudioPaths, verifyStudioMedia } from "./paths";
import { inspectStudio, startStudio } from "./process";
import { cleanupStartedStudio, ownsStudioProcess, readStudioRecord, studioSessionReady, studioUrl, waitForStudio } from "./session";
import { STUDIO_CAVEAT, StudioError, type StudioInspection, type StudioStatus } from "./model";

export const studioDependencies = {
  inspect: inspectStudio, start: startStudio, record: readStudioRecord,
  ready: studioSessionReady, wait: waitForStudio, cleanup: cleanupStartedStudio,
  owned: ownsStudioProcess,
  paths: assertStudioPaths, media: verifyStudioMedia,
  guard: (dir: string) => guardProjectMutation({ projectRoot: mutationProjectRoot(dir),
    producerDir: dir, operation: "opening the Studio graphics review" }),
};
export type StudioDependencies = typeof studioDependencies;
const STALE_LIVE = "Studio is still serving an older view. Stop that Studio session before refreshing; existing edits were preserved.";
const UNPROVEN_LIVE = "This Studio session is not proven review-only and ready. Stop that Studio session explicitly, then reopen it from Sniper; existing edits were preserved.";

function status(inspection: StudioInspection, url: string | null): StudioStatus {
  const blockers = inspection.blockers;
  return { ok: true, state: blockers.length ? "blocked" : url ? "ready" : "not-open",
    url: blockers.length ? null : url, canOpen: blockers.length === 0,
    pendingEdits: inspection.pendingEdits, blockers, caveat: STUDIO_CAVEAT };
}

export async function getStudioStatus(dir: string, deps = studioDependencies): Promise<StudioStatus> {
  deps.paths(dir);
  const inspection = await deps.inspect(dir);
  const record = deps.record(dir);
  const ready = record && await deps.ready(dir, record);
  if (record && !ready && await deps.owned(dir, record)) inspection.blockers.push(UNPROVEN_LIVE);
  if (ready && !inspection.viewCurrent) inspection.blockers.push(STALE_LIVE);
  return status(inspection, ready && inspection.viewCurrent ? studioUrl(record) : null);
}

async function openLocked(dir: string, deps: StudioDependencies): Promise<StudioStatus> {
  deps.paths(dir);
  const before = await deps.inspect(dir);
  if (before.blockers.length) throw new StudioError(before.blockers.join("; "));
  const previous = deps.record(dir);
  const live = Boolean(previous && await deps.ready(dir, previous));
  if (previous && !live && await deps.owned(dir, previous)) throw new StudioError(UNPROVEN_LIVE);
  if (live && !before.viewCurrent) throw new StudioError(STALE_LIVE);
  const digest = await deps.media(dir, before.viewCurrent);
  const reused = live && before.viewCurrent;
  try {
    if (!reused) await deps.start(dir, before.viewCurrent);
    const record = deps.record(dir);
    if (!record) throw new StudioError("Studio did not publish a server record", 502);
    await deps.wait(dir, record);
    deps.paths(dir);
    const after = await deps.inspect(dir);
    if (after.parent !== before.parent || !after.viewCurrent || after.blockers.length
        || await deps.media(dir, true) !== digest) {
      throw new StudioError("Project inputs changed while Studio opened; retry against the current plan", 409, "STUDIO_STALE_PARENT");
    }
    return { ...status(after, studioUrl(record)), reused };
  } catch (error) {
    if (!reused) await deps.cleanup(dir, previous).catch((cleanupError) => {
      console.error("Studio failed-start cleanup needs attention", cleanupError);
    });
    throw error;
  }
}

/** Projection generation is a project mutation; the lease lasts through readiness. */
export async function openStudio(dir: string, deps = studioDependencies): Promise<StudioStatus | Response> {
  const guarded = deps.guard(dir);
  if (guarded.response) return guarded.response;
  try { return await openLocked(dir, deps); } finally { guarded.lease.release(); }
}
