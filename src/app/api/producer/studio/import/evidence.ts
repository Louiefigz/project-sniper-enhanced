import { createHash } from "node:crypto";
import type { EditPlan } from "@/lib/producer/edit-plan";
import { ImportError, type ImportChange, type OriginalSession, type Proposal } from "./model";

export const sha = (value: string | Buffer): string => createHash("sha256").update(value).digest("hex");
export const jsonText = (value: unknown): string => `${JSON.stringify(value, null, 1)}\n`;

/** Operator-visible changes always compare the exact before plan to candidate. */
export function pendingChanges(before: EditPlan, after: EditPlan): ImportChange[] {
  const rows: ImportChange[] = [];
  for (let index = 0; index < (before.graphicsTrack?.length ?? 0); index += 1) {
    const old = before.graphicsTrack![index]; const next = after.graphicsTrack![index];
    const fields: [string, unknown, unknown][] = [["outStart", old.outStart, next.outStart], ["outEnd", old.outEnd, next.outEnd]];
    const keys = new Set([...Object.keys(old.spec ?? {}), ...Object.keys(next.spec ?? {})]);
    for (const key of keys) fields.push([`spec.${key}`, old.spec?.[key], next.spec?.[key]]);
    for (const [field, previous, value] of fields) {
      if (JSON.stringify(previous) !== JSON.stringify(value)) rows.push({ graphicId: old.id!, kind: old.kind,
        field, before: previous ?? null, after: value ?? null });
    }
  }
  return rows;
}

/** Digests are integrity checks, not authentication; redundant evidence must agree. */
export function assertOriginalBindings(session: OriginalSession): void {
  if (typeof session.originalPlanText !== "string" || sha(session.originalPlanText) !== session.originalPlanHash
      || JSON.stringify(JSON.parse(session.originalPlanText)) !== JSON.stringify(session.originalPlan)) {
    throw new ImportError("Studio original plan object, exact text and hash do not agree");
  }
  const manifest = JSON.parse(session.manifestText) as {
    files: Record<string, string>; entries: { file: string; kind: string; planId: string }[] };
  const track = session.originalPlan.graphicsTrack ?? [];
  if (manifest.files?.["index.html"] !== sha(session.host) || !Array.isArray(manifest.entries)
      || manifest.entries.length !== track.length) throw new ImportError("Studio original host does not bind its generation manifest");
  const names = manifest.entries.map((entry) => entry.file).sort();
  if (new Set(names).size !== names.length || JSON.stringify(names) !== JSON.stringify(Object.keys(session.instances).sort())) {
    throw new ImportError("Studio original instance set does not bind its generation manifest");
  }
  for (const [index, entry] of manifest.entries.entries()) {
    if (entry.kind !== track[index].kind || entry.planId !== track[index].id
        || manifest.files[entry.file] !== sha(session.instances[entry.file])) {
      throw new ImportError("Studio original instance or graphic identity does not bind its generation manifest");
    }
  }
}

/** Validate first-use proposals as strictly as already-linked receipts. */
export function assertProposalBindings(proposal: Proposal): void {
  const before = JSON.parse(proposal.capture.planText) as EditPlan;
  const version = before.planVersion ?? 0;
  if (sha(proposal.capture.planText) !== proposal.beforeHash || proposal.capture.planHash !== proposal.beforeHash
      || version !== proposal.beforeVersion || !Number.isSafeInteger(proposal.beforeVersion) || proposal.beforeVersion < 0
      || proposal.afterVersion !== proposal.beforeVersion + 1 || !Number.isSafeInteger(proposal.afterVersion)
      || proposal.candidate.planVersion !== proposal.afterVersion || jsonText(proposal.candidate) !== proposal.candidateText
      || sha(proposal.candidateText) !== proposal.afterHash) throw new ImportError("Studio proposal before/candidate/after bindings are inconsistent");
  if (!proposal.changes.length || JSON.stringify(pendingChanges(before, proposal.candidate)) !== JSON.stringify(proposal.changes)) {
    throw new ImportError("Studio proposal changes do not describe its exact before/candidate plans");
  }
}
