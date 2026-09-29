/** Inherited content approval versus new execution evidence (requirement approved-content-production-2026-09-27).
 * The operator approved each clip's exact title words and script before production. The role packet carries that
 * given content and the engine's separate facts about the subject (`packet.given`, unit B1): the title comparison and
 * whether selection, caption text and timing match. A departure is an execution defect: a pass is refused, and a
 * revise or block must cover it with a material issue scoped `approved-content-contradiction`. A critic's proposed
 * change to the given words themselves is a finding scoped `proposed-change`: surfaced for the operator, never
 * withholding execution approval and never a second approval round. Only the operator records a change to approved
 * content; a critic never does. The block's contract is B1's fixture
 * `scripts/producer/tests/fixtures/role-packet-given-contract.json`: `status: "not-supplied"` (or an older packet with
 * no block) binds no approval; `status: "bound"` must come from the batch authority's reader under this revision. */
import { exactKeys, objectValue, sha256, stringValue, type JsonRecord } from "@/lib/producer/contracts/validation";

/** Material issue scopes: execution defects, and departures from the given content (both withhold approval). */
export const ISSUE_SCOPES = ["execution", "approved-content-contradiction"] as const;
/** Finding scopes: ordinary findings, and proposed changes to the given content for the operator. */
export const FINDING_SCOPES = ["execution", "proposed-change"] as const;
/** A missing approved title is "different" (material): the plan's own title never stands in for the given one. */
const TITLE_STATES = ["exact", "normalization-only", "different"];
/** Only the current active or draining batch binds given content (the engine check refuses any other). */
const BINDING_STATUSES: readonly string[] = ["active", "draining"];
/** Read as submitted (`check-final` on an existing record), the approval in force at the recorded submission binds
 * whatever the batch's status now: a closed batch keeps verifying the records submitted while it ran. */
export const AS_SUBMITTED_STATUSES: readonly string[] = ["active", "draining", "closed"];
const FACTS = ["selection", "captionText", "timing"] as const;
/** The only reader a bound block may come from, and the requirement revision it binds under. */
export const GIVEN_ORIGIN = "studio.production.api.read_approval";
export const GIVEN_REVISION = "approved-content-production-2026-09-27";
const BOUND_KEYS = ["status", "readFrom", "requirementRevision", "batchId", "clipId", "authorityStatus", "identity",
  "scriptSha256", "titleSha256", "planChecked", "title", "selection", "captionText", "timing"];
const APPROVED_KEYS = ["batch", "clip", "origin", "identity", "scriptSha256", "title"];
/** The batch authority's approval a record answered: its batch and clip, reader, identities and exact title. */
export interface GivenIdentity {
  batch: string; clip: string; origin: string; identity: string; scriptSha256: string; title: string | null;
}
/** The given identity a record answered, whether the packet compared it with the subject, and what was found. */
export interface ApprovedContent {
  approved: GivenIdentity | null; planChecked: boolean; departures: string[]; contradictions: string[]; proposedChanges: string[];
}
const KEYS = ["approved", "planChecked", "departures", "contradictions", "proposedChanges"];

function listed(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}

function flag(row: JsonRecord, key: string, label: string): boolean {
  if (typeof row[key] !== "boolean") throw new Error(`${label}.${key} must be true or false`);
  return row[key] as boolean;
}

function givenIdentity(row: JsonRecord, label: string): GivenIdentity {
  if (row.origin !== GIVEN_ORIGIN) throw new Error(`${label} approvals are read only through ${GIVEN_ORIGIN}`);
  if (row.title !== null) stringValue(row.title, `${label}.title`, 2000);
  return { batch: stringValue(row.batch, `${label} batch id`, 256), clip: stringValue(row.clip, `${label} clip id`, 256),
    origin: GIVEN_ORIGIN, identity: sha256(row.identity, `${label}.identity`),
    scriptSha256: sha256(row.scriptSha256, `${label}.scriptSha256`), title: row.title as string | null };
}

/** B1's bound block, or null when no approval applies; any other status or shape is refused, never read as agreement.
 * `statuses` are the batch states whose approval binds: the current batch's, unless a record is read as submitted. */
export function boundGiven(given: JsonRecord | null, statuses: readonly string[] = BINDING_STATUSES): JsonRecord | null {
  if (given === null) return null;
  if (given.status === "not-supplied") {
    exactKeys(given, ["status", "meaning"], ["status", "meaning"], "given");
    stringValue(given.meaning, "given.meaning", 2000);
    return null;
  }
  if (given.status !== "bound") throw new Error("given.status must be bound or not-supplied");
  exactKeys(given, BOUND_KEYS, BOUND_KEYS, "given");
  if (given.requirementRevision !== GIVEN_REVISION) throw new Error(`given.requirementRevision must be ${GIVEN_REVISION}`);
  if (!statuses.includes(given.authorityStatus as string)) {
    throw new Error(`given.authorityStatus is ${String(given.authorityStatus)}: only the current active or draining batch `
      + "binds given content; a closed or archived batch's approval admits nothing");
  }
  return given;
}

function identity(given: JsonRecord): GivenIdentity {
  const title = objectValue(given.title, "given.title");
  return givenIdentity({ batch: given.batchId, clip: given.clipId, origin: given.readFrom, identity: given.identity,
    scriptSha256: given.scriptSha256, title: title.given }, "given");
}

function factDeparture(key: (typeof FACTS)[number], fact: JsonRecord): string | null {
  if (flag(fact, "matches", `given.${key}`)) return null;
  const row = objectValue(fact.details, `given.${key}.details`);
  if (key === "selection") {
    return `selection: kept words differ from the given script (${listed(row.missingWords)} missing, ${listed(row.extraWords)} `
      + `extra, ${listed(row.repeatedWords)} repeated${row.otherOrder === true ? ", other order" : ""}`
      + `${row.sourceMatches === false || row.transcriptMatches === false ? ", other source or transcript" : ""})`;
  }
  return key === "captionText" ? `caption text: ${listed(row.mismatchedOccurrences)} occurrence(s) carry other words`
    : `timing: ${listed(row.frameMismatches)} frame and ${listed(row.segmentMismatches)} segment mismatch(es)`;
}

/** Departures the packet's given facts report; a malformed block is refused, never read as agreement. */
export function givenDepartures(given: JsonRecord): { planChecked: boolean; departures: string[] } {
  const title = objectValue(given.title, "given.title");
  if (!flag(given, "planChecked", "given")) return { planChecked: false, departures: [] };
  if (!TITLE_STATES.includes(title.status as string)) throw new Error("given.title.status is not a known state");
  const material = flag(title, "material", "given.title");
  if (material !== (title.status === "different")) throw new Error("given.title.material is true exactly for a different title");
  const departures = material ? [`title: the subject shows ${JSON.stringify(title.planned)}, `
    + `given ${JSON.stringify(title.given)} (${String(title.status)})`] : [];
  for (const key of FACTS) {
    const found = factDeparture(key, objectValue(given[key], `given.${key}`));
    if (found) departures.push(found);
  }
  return { planChecked: true, departures };
}

/** Codes by scope; a proposed change is never material and a contradiction is never a mere finding. */
export function scopedCodes(observations: JsonRecord): { contradictions: string[]; proposedChanges: string[] } {
  const material = observations.materialIssues as JsonRecord[], findings = observations.findings as JsonRecord[];
  const check = (rows: JsonRecord[], allowed: readonly string[], label: string) => rows.forEach((row, index) => {
    if (row.scope !== undefined && !allowed.includes(row.scope as string)) {
      throw new Error(`${label}[${index}].scope must be ${allowed.join(" or ")}: a departure from the given content is a `
        + "material approved-content-contradiction; a proposed change to the given words is a proposed-change finding "
        + "for the operator and never withholds execution approval");
    }
  });
  check(material, ISSUE_SCOPES, "materialIssues");
  check(findings, FINDING_SCOPES, "findings");
  const codes = (rows: JsonRecord[], scope: string) => rows.filter(row => row.scope === scope).map(row => String(row.code));
  return { contradictions: codes(material, "approved-content-contradiction"), proposedChanges: codes(findings, "proposed-change") };
}

function refuseUncovered(verdict: string, block: Pick<ApprovedContent, "departures" | "contradictions">): void {
  if (!block.departures.length) return;
  if (verdict === "pass") {
    throw new Error(`A pass cannot be recorded while the subject departs from the operator's given content `
      + `(${block.departures.join("; ")}): the given title and script must be rendered exactly. Record each departure as `
      + "a material issue scoped approved-content-contradiction with its smallest repair. A problem inside the given "
      + "words themselves is a proposed-change finding for the operator, never a critic's change");
  }
  if (!block.contradictions.length) {
    throw new Error(`The subject departs from the given content (${block.departures.join("; ")}); cover it with a material `
      + "issue scoped approved-content-contradiction");
  }
}

/** The record block for a submission; refuses a pass (or an uncovered revise) that departs from the given content. */
export function approvedContentBlock(packetGiven: JsonRecord | null, observations: JsonRecord, verdict: string,
  statuses?: readonly string[]): ApprovedContent {
  const given = boundGiven(packetGiven, statuses);
  const facts = given ? givenDepartures(given) : { planChecked: false, departures: [] };
  const block = { approved: given ? identity(given) : null, ...facts, ...scopedCodes(observations) };
  refuseUncovered(verdict, block);
  return block;
}

function strings(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.length > 64) throw new Error(`${label} must be a bounded array`);
  return value.map((item, index) => stringValue(item, `${label}[${index}]`, 2000));
}

/** Reader: the block's shape, and never a pass (or an uncovered revise) beside a recorded departure. */
export function readApprovedContent(value: unknown, verdict: string): ApprovedContent {
  const row = objectValue(value, "approvedContent");
  exactKeys(row, KEYS, KEYS, "approvedContent");
  let approved: GivenIdentity | null = null;
  if (row.approved !== null) {
    const item = objectValue(row.approved, "approvedContent.approved");
    exactKeys(item, APPROVED_KEYS, APPROVED_KEYS, "approvedContent.approved");
    approved = givenIdentity(item, "approvedContent.approved");
  }
  if (typeof row.planChecked !== "boolean") throw new Error("approvedContent.planChecked must be true or false");
  const block = { approved, planChecked: row.planChecked, departures: strings(row.departures, "approvedContent.departures"),
    contradictions: strings(row.contradictions, "approvedContent.contradictions"),
    proposedChanges: strings(row.proposedChanges, "approvedContent.proposedChanges") };
  refuseUncovered(verdict, block);
  return block;
}
