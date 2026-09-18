import type { EditPlan } from "@/lib/producer/edit-plan";

export const IMPORT_CAVEAT = "Apply saves graphics timing and supported copy to a Sniper draft only. Studio files and the existing final remain unchanged. Render updated video in Sniper for full QC.";
export interface ImportChange { graphicId: string; kind: string; field: string; before: unknown; after: unknown }
export interface ImportPrepared {
  ok: true; state: "ready" | "blocked" | "unchanged"; proposalId: string | null;
  expectedPlanHash: string; expectedPlanVersion: number; changes: ImportChange[];
  blockers: string[]; warnings: string[]; caveat: string;
}
export interface ImportApplied {
  ok: true; applied: boolean; alreadyApplied: boolean; planVersion: number; planHash: string;
  requiresRender: true; studioEditsPreserved: true; warnings: string[];
}
export interface Capture {
  planText: string; planHash: string; authority: string; snapshot: string; baseHash: string;
  manifestText: string; files: Record<string, string>; textFiles: Record<string, string>;
}
export interface OriginalSession {
  schema: 1; dir: string; originalPlan: EditPlan; originalPlanText: string; originalPlanHash: string;
  authority: string; manifestText: string; host: string; instances: Record<string, string>; digest: string;
}
export interface Proposal {
  schema: 1; id: string; sessionDigest: string; previous: string | null;
  beforeHash: string; beforeVersion: number; afterHash: string; afterVersion: number;
  candidate: EditPlan; candidateText: string; capture: Capture; changes: ImportChange[];
  warnings: string[]; digest: string;
}
export interface ImportHead { proposalId: string; digest: string; previous: string | null }
export interface ApplyInput { proposalId: string; expectedPlanHash: string; expectedPlanVersion: number }
export interface DiffResult { candidate: EditPlan; blockers: string[]; warnings: string[] }
export class ImportError extends Error {
  committed = false;
  constructor(message: string, readonly status = 409, readonly code = "STUDIO_IMPORT_BLOCKED") { super(message); }
}
