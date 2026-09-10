/** Studio may propose/import a draft; this protocol never approves or renders video. */
export interface StudioImportChange {
  graphicId: string;
  kind: string;
  field: string;
  before: unknown;
  after: unknown;
}
export interface StudioImportProposal {
  ok: true;
  state: "ready" | "blocked" | "unchanged";
  proposalId: string | null;
  expectedPlanHash: string;
  expectedPlanVersion: number;
  changes: StudioImportChange[];
  blockers: string[];
  warnings: string[];
  caveat: string;
}
export interface StudioImportResult {
  ok: true;
  applied: boolean;
  alreadyApplied: boolean;
  planVersion: number;
  planHash: string;
  requiresRender: true;
  studioEditsPreserved: true;
  warnings: string[];
}
export class StudioImportError extends Error {
  constructor(message: string, readonly committed?: boolean) { super(message); }
}
const SHA = /^[a-f0-9]{64}$/;
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;

function row(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid Studio import response");
  return value as Record<string, unknown>;
}
function text(value: unknown, limit = 4000): value is string {
  return typeof value === "string" && value.length <= limit;
}
function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.length <= 200 && value.every((item) => text(item));
}
function version(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}
function change(value: unknown): StudioImportChange {
  const item = row(value);
  if (![item.graphicId, item.kind, item.field].every((entry) => text(entry, 128) && entry.length > 0)
      || !Object.hasOwn(item, "before") || !Object.hasOwn(item, "after")) {
    throw new Error("Invalid Studio change description");
  }
  for (const value of [item.before, item.after]) {
    const serialized = JSON.stringify(value);
    if (serialized === undefined || serialized.length > 64_000) throw new Error("Oversized Studio change description");
  }
  return item as unknown as StudioImportChange;
}

/** Validate authority and blockers before enabling an explicit draft import. */
export function parseStudioImportProposal(value: unknown): StudioImportProposal {
  const item = row(value);
  if (item.ok !== true || !["ready", "blocked", "unchanged"].includes(String(item.state))
      || !text(item.expectedPlanHash) || !SHA.test(item.expectedPlanHash)
      || !version(item.expectedPlanVersion) || !strings(item.blockers) || !strings(item.warnings)
      || !text(item.caveat) || !Array.isArray(item.changes) || item.changes.length > 2000
      || !(item.proposalId === null || (text(item.proposalId) && UUID.test(item.proposalId)))) {
    throw new Error("Invalid Studio import proposal");
  }
  const changes = item.changes.map(change);
  if (item.state === "ready" && (!item.proposalId || item.blockers.length || !changes.length)) {
    throw new Error("Studio proposal is not ready for import");
  }
  if (item.state !== "ready" && item.proposalId !== null) throw new Error("Blocked Studio proposal cannot authorize import");
  return { ...item, changes } as unknown as StudioImportProposal;
}

export function parseStudioImportResult(value: unknown): StudioImportResult {
  const item = row(value);
  if (item.ok !== true || typeof item.applied !== "boolean" || typeof item.alreadyApplied !== "boolean"
      || item.applied === item.alreadyApplied || !version(item.planVersion)
      || !text(item.planHash) || !SHA.test(item.planHash) || item.requiresRender !== true
      || item.studioEditsPreserved !== true || !strings(item.warnings)) {
    throw new Error("Studio did not confirm a preserved draft import requiring render/QC");
  }
  return item as unknown as StudioImportResult;
}

async function request(body: Record<string, unknown>, signal?: AbortSignal): Promise<unknown> {
  signal?.throwIfAborted();
  const response = await fetch("/api/producer/studio/import", {
    method: "POST", cache: "no-store", signal,
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const value: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = value && typeof value === "object" ? value as Record<string, unknown> : {};
    throw new StudioImportError(text(error.error) ? error.error : `Studio import failed (${response.status})`,
      typeof error.committed === "boolean" ? error.committed : undefined);
  }
  return value;
}

/** Preparing may retain private proposal evidence but cannot change the draft. */
export async function prepareStudioImport(dir: string, signal?: AbortSignal): Promise<StudioImportProposal> {
  return parseStudioImportProposal(await request({ dir, action: "prepare" }, signal));
}

interface ApplyInput {
  dir: string;
  proposal: StudioImportProposal;
  signal?: AbortSignal;
  invalidatePreview: () => void;
  reloadDraft: () => Promise<boolean>;
}
export type StudioApplyOutcome = {
  result: StudioImportResult | null;
  error: string | null;
  reloaded: boolean;
};

/** Invalidate before dispatch; even a lost response can follow a committed save. */
export async function applyStudioImport(input: ApplyInput): Promise<StudioApplyOutcome> {
  const proposal = parseStudioImportProposal(input.proposal);
  if (proposal.state !== "ready") throw new Error("Preview supported Studio changes before importing");
  input.signal?.throwIfAborted();
  input.invalidatePreview();
  let result: StudioImportResult | null = null;
  let error: string | null = null;
  try {
    result = parseStudioImportResult(await request({ dir: input.dir, action: "apply",
      proposalId: proposal.proposalId, expectedPlanHash: proposal.expectedPlanHash,
      expectedPlanVersion: proposal.expectedPlanVersion }, input.signal));
  } catch (failure) {
    error = failure instanceof Error ? failure.message : "Studio import outcome is unknown";
  }
  const reloaded = await input.reloadDraft().catch(() => false);
  return { result, error, reloaded };
}
