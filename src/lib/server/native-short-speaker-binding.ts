/** The plan's binding to sealed shared evidence (P2-08), as the coordinator ruled it (X228, X229).
 * - Shape: `sharedEvidence` is exactly `{path, sha256, contentSha256, version}`.
 * - Currency (the engine's `context.py --evidence-check`) is judged only where a plan is admitted: `measure`,
 *   `build-draft`, `build` and the project writer. A stale binding refuses there by name (`stale-evidence`); a reader
 *   only reports it (`nativeSharedEvidenceStatus`), so a reseal or another clip's script change never makes a built
 *   project or a final unreadable.
 * - Agreement with the review (`shared-evidence-unbound`): a plan whose prebuild review packet bound a record, or which
 *   carries picture decisions, must bind evidence, and the record its review packet bound. A review-pending plan
 *   without decisions may omit the binding (X229); whether a plan that "shows people" must bind is the owner's M-073
 *   decision. Split from native-short-speaker-evidence.ts for the 300-line rule. */
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { exactKeys, objectValue, sha256, stringValue, type JsonRecord } from "@/lib/producer/contracts/validation";
import { NativeCheckError } from "./native-check-error";
import { readRolePacket } from "./native-review-packet";
import { evidenceCheck } from "./native-review-shared-evidence";
import type { NativeShortProjectInput } from "./native-short-project";

const BINDING_KEYS = ["path", "sha256", "contentSha256", "version"];
/** A plan's binding of one sealed shared-evidence record (the fields the engine check reports). */
export interface NativeSharedEvidenceBinding { path: string; sha256: string; contentSha256: string; version: number }
/** What a reader reports about a binding; never a refusal. */
export type NativeSharedEvidenceStatus = { status: "current"; path: string; version: number }
  | { status: "stale-evidence"; path: string; version: number; reason: string };

/** The plan's binding with every field checked, or undefined when the plan binds none. */
export function nativeSharedEvidenceBinding(input: NativeShortProjectInput): NativeSharedEvidenceBinding | undefined {
  if (input.sharedEvidence === undefined) return undefined;
  const row = objectValue(input.sharedEvidence, "sharedEvidence");
  exactKeys(row, BINDING_KEYS, BINDING_KEYS, "sharedEvidence");
  if (!Number.isSafeInteger(row.version) || (row.version as number) < 1) throw new Error("sharedEvidence.version must be a record version");
  return { path: stringValue(row.path, "sharedEvidence.path", 4096), sha256: sha256(row.sha256, "sharedEvidence.sha256"),
    contentSha256: sha256(row.contentSha256, "sharedEvidence.contentSha256"), version: row.version as number };
}

/** The engine check's verdict on a binding. Only a refusal the check itself reports (a plain Error) is staleness; a
 * process or parse failure is rethrown, never read as stale. */
function currency(binding: NativeSharedEvidenceBinding): NativeSharedEvidenceStatus {
  let report: JsonRecord;
  try {
    report = evidenceCheck.run(binding.path);
  } catch (error) {
    if (!(error instanceof Error) || error.constructor !== Error || "code" in error) throw error;
    return { status: "stale-evidence", path: binding.path, version: binding.version, reason: error.message };
  }
  const same = report.status === "shared-evidence-current" && report.path === binding.path && report.sha256 === binding.sha256
    && report.contentSha256 === binding.contentSha256 && report.version === binding.version;
  return same ? { status: "current", path: binding.path, version: binding.version } : { status: "stale-evidence",
    path: binding.path, version: binding.version, reason: `the current sealed record is ${String(report.path)} v${String(report.version)}` };
}

/** Admission only: refuse a stale binding by name, with the next action. */
export function assertCurrentSharedEvidence(binding: NativeSharedEvidenceBinding): void {
  const verdict = currency(binding);
  if (verdict.status === "current") return;
  throw new NativeCheckError("stale-evidence", `shared evidence v${binding.version} (${binding.path}) is no longer current: `
    + `${verdict.reason}. Rebind the plan's sharedEvidence to the current sealed record and obtain a fresh plan review; `
    + "projects already built from this binding stay readable");
}

/** Admission of the binding as a whole (X228, X229): agreement with the review, then currency when bound. */
export function assertSharedEvidenceAdmitted(input: NativeShortProjectInput): void {
  assertSharedEvidenceBound(input);
  const binding = nativeSharedEvidenceBinding(input);
  if (binding) assertCurrentSharedEvidence(binding);
}

/** Readers: the binding's currency as a status (null without a binding); a stale binding is reported, never refused. */
export function nativeSharedEvidenceStatus(input: NativeShortProjectInput): NativeSharedEvidenceStatus | null {
  const binding = nativeSharedEvidenceBinding(input);
  return binding ? currency(binding) : null;
}

/** The record the plan's prebuild review packet bound (null: no review, a schema-1 review, or none bound). The review
 * receipt and its packet are read at their recorded sha256s; whether the review is current is the review's own rule. */
export function reviewedSharedEvidence(input: NativeShortProjectInput): { path: string; sha256: string } | null {
  if (!input.prebuildReview) return null;
  const receipt = readCutPreviewObject(input.prebuildReview.path);
  if (receipt.sha256 !== input.prebuildReview.sha256) throw new Error("Native prebuild review receipt changed");
  if (receipt.value.schemaVersion !== 2) return null;
  const bound = objectValue(objectValue(receipt.value.submission, "prebuild review submission").rolePacket, "prebuild review rolePacket");
  const packet = readRolePacket(stringValue(bound.path, "rolePacket.path", 4096), "plan-critic");
  if (packet.sha256 !== bound.sha256) throw new Error("The prebuild review's role packet changed since the review");
  if (!packet.sharedEvidence) return null;
  return { path: stringValue(packet.sharedEvidence.path, "packet sharedEvidence.path", 4096),
    sha256: sha256(packet.sharedEvidence.sha256, "packet sharedEvidence.sha256") };
}

/** X229: refuse `shared-evidence-unbound` when the review packet bound a record or the plan carries picture decisions
 * and the plan binds none, or when the plan binds another record than its review packet. */
export function assertSharedEvidenceBound(input: NativeShortProjectInput): void {
  const binding = nativeSharedEvidenceBinding(input), reviewed = reviewedSharedEvidence(input);
  const name = (row: { path: string; sha256: string }) => `${row.path} (${row.sha256.slice(0, 12)})`;
  if (!binding && reviewed) {
    throw new NativeCheckError("shared-evidence-unbound", `plan binds no shared evidence, but its prebuild review packet bound `
      + `${name(reviewed)}, whose sealed speaker facts P2-08 must check: set the plan's sharedEvidence to that record and `
      + "obtain a fresh plan review");
  }
  if (!binding && input.speakerPictureDecisions !== undefined) {
    throw new NativeCheckError("shared-evidence-unbound", "plan carries speakerPictureDecisions but binds no shared evidence: "
      + "bind the sealed record they answer (sharedEvidence), or remove the decisions");
  }
  if (binding && reviewed && (binding.path !== reviewed.path || binding.sha256 !== reviewed.sha256)) {
    throw new NativeCheckError("shared-evidence-unbound", `plan binds ${name(binding)}, but its prebuild review packet bound `
      + `${name(reviewed)}: bind the record the critic reviewed, or obtain a fresh plan review against the plan's record`);
  }
}
