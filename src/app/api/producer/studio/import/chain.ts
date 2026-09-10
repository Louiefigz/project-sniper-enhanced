import fs from "node:fs";
import path from "node:path";
import { reconcileGraphicIds, type EditPlan } from "@/lib/producer/edit-plan";
import { ImportError, type OriginalSession, type Proposal } from "./model";
import { jsonText, readHead, readProposal, readSession, readText, sha } from "./files";
import { captureStudio } from "./authority";
import { verifyStudioMedia } from "../paths";
import copyFields from "./copy-fields.json";
export { pendingChanges } from "./evidence";

export function planVersion(plan: EditPlan): number {
  const version = plan.planVersion ?? 0;
  if (!Number.isSafeInteger(version) || Number(version) < 0) throw new ImportError("Plan version must be a nonnegative safe integer");
  return Number(version);
}

export function assertStableIds(plan: EditPlan): void {
  if (!plan.graphicsTrack?.length || JSON.stringify(reconcileGraphicIds(plan).plan) !== JSON.stringify(plan)) {
    throw new ImportError("Studio import requires stable graphics/decision IDs. Resolve identity explicitly before starting a new review session");
  }
}

/** The immutable receipt intent is committed iff the exact current after-SHA matches. */
export function chainTip(dir: string, session: OriginalSession, currentHash: string): { tip: Proposal | null; pending: boolean } {
  const head = readHead(dir);
  if (!head) {
    if (currentHash !== session.originalPlanHash) throw new ImportError("Sniper draft changed outside this Studio import session; preserve edits and explicitly create a new review session");
    return { tip: null, pending: false };
  }
  const tip = readProposal(dir, head.proposalId);
  if (tip.digest !== head.digest || tip.previous !== head.previous) throw new ImportError("Studio import head does not bind its receipt");
  let row = tip; const seen = new Set<string>();
  while (row) {
    if (seen.has(row.id) || seen.size >= 100 || row.sessionDigest !== session.digest
        || sha(row.candidateText) !== row.afterHash || jsonText(row.candidate) !== row.candidateText) throw new ImportError("Studio import receipt chain is invalid");
    seen.add(row.id);
    if (!row.previous) {
      if (row.beforeHash !== session.originalPlanHash) throw new ImportError("Studio receipt root does not bind original plan");
      break;
    }
    const previous = readProposal(dir, row.previous);
    if (previous.afterHash !== row.beforeHash || previous.afterVersion !== row.beforeVersion) throw new ImportError("Studio receipt parent binding is invalid");
    row = previous;
  }
  if (currentHash === tip.afterHash) return { tip, pending: false };
  if (currentHash === tip.beforeHash) return { tip, pending: true };
  throw new ImportError("Sniper draft changed outside the Studio receipt chain; no imported edits were overwritten");
}

/** Existing open/status can recognize imports without mutating old view fingerprints. */
export async function hasImportedPlan(dir: string): Promise<boolean> {
  try {
    const session = readSession(dir);
    if (!session) return false;
    const current = sha(readText(path.join(dir, "edit_plan.json")));
    const { tip, pending } = chainTip(dir, session, current);
    if (!tip || pending || readText(path.join(dir, "studio", "studio.manifest.json")) !== session.manifestText) return false;
    return captureStudio(dir, await verifyStudioMedia(dir)).authority === session.authority;
  } catch { return false; }
}

export function assertNoRefit(dir: string): void {
  if (fs.existsSync(path.join(dir, ".sniper-plan-refit.pending.json"))) {
    throw new ImportError("A pending cut-refit transition must be explicitly recovered before importing Studio changes");
  }
}

export function assertCandidate(original: EditPlan, candidate: EditPlan): void {
  assertStableIds(original); assertStableIds(candidate);
  const strip = (plan: EditPlan) => ({ ...plan, planVersion: 0, graphicsTrack: plan.graphicsTrack?.map((entry) => {
    const identity: Record<string, unknown> = { ...entry };
    delete identity.outStart; delete identity.outEnd;
    const fields = (copyFields as Record<string, string[]>)[entry.kind] ?? [];
    identity.spec = Object.fromEntries(Object.entries(entry.spec ?? {}).filter(([key]) => !fields.includes(key)));
    return identity;
  }) });
  if (JSON.stringify(strip(original)) !== JSON.stringify(strip(candidate))) throw new ImportError("Studio candidate changed unsupported plan fields");
}
