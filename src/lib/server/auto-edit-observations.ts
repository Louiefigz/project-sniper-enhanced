import { randomUUID } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import type { AuditBOutcome } from "@/app/api/producer/auto-edit/chain";
import type { ProducerReview } from "@/app/api/producer/auto-edit/review-contract";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import {
  canonicalJson,
  canonicalJsonSha256,
  fileSha256,
} from "./auto-edit-hash";
import { restoreAutoEditDoctrine } from "./auto-edit-doctrine";

interface ObservationCore {
  schemaVersion: 1;
  observationId: string;
  runId: string;
  doctrineHash: string;
  sourceKind: "critic" | "qc";
  code: string;
  lane: string;
  severity: "major" | "critical";
  evidence: Record<string, unknown>;
}

interface ObservationReceipt extends ObservationCore {
  status: "observed";
  observationHash: string;
}

interface AuditCheck {
  name?: unknown;
  status?: unknown;
  measured?: unknown;
  detail?: unknown;
}

export interface CriticObservationInput {
  ctx: AutoEditCtx;
  artifactPath: string;
  review: ProducerReview;
  namespace: string;
}

export interface AuditObservationInput {
  ctx: AutoEditCtx;
  candidateDir: string;
  round: number;
  attempt: number;
  audit: AuditBOutcome;
}

interface AuditCheckInput {
  ctx: AutoEditCtx;
  check: AuditCheck;
  artifactHash: string;
  namespace: string;
  index: number;
}

function safeId(value: string): string {
  const safe = value.replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 180);
  if (!safe) throw new Error("learning observation id is empty");
  return safe;
}

function observationDir(ctx: AutoEditCtx): string | null {
  if (!ctx.doctrine) return null;
  const lock = restoreAutoEditDoctrine(ctx.doctrine);
  return path.join(ctx.dir, ".sniper-learning", "runs", lock.runId, "observations");
}

function writeObservation(ctx: AutoEditCtx, core: ObservationCore): string | null {
  const dir = observationDir(ctx);
  if (!dir) return null;
  const receipt: ObservationReceipt = {
    ...core, status: "observed", observationHash: canonicalJsonSha256(core),
  };
  const destination = path.join(dir, `${safeId(core.observationId)}.json`);
  if (existsSync(destination)) {
    const existing: unknown = JSON.parse(readFileSync(destination, "utf8"));
    if (canonicalJson(existing) !== canonicalJson(receipt)) {
      throw new Error(`learning observation collision: ${core.observationId}`);
    }
    return destination;
  }
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  const temporary = `${destination}.${randomUUID()}.tmp`;
  try {
    writeFileSync(temporary, `${JSON.stringify(receipt, null, 2)}\n`, {
      flag: "wx", mode: 0o600,
    });
    renameSync(temporary, destination);
  } finally {
    rmSync(temporary, { force: true });
  }
  return destination;
}

function core(
  ctx: AutoEditCtx,
  id: string,
  source: Pick<ObservationCore, "sourceKind" | "code" | "lane" | "severity">,
  evidence: Record<string, unknown>,
): ObservationCore {
  if (!ctx.doctrine) throw new Error("learning observation has no pinned doctrine");
  return {
    schemaVersion: 1,
    observationId: safeId(id),
    runId: ctx.doctrine.runId,
    doctrineHash: ctx.doctrine.doctrineHash,
    ...source,
    evidence,
  };
}

/** Persist material critic facts. No proposal or doctrine mutation is performed. */
export function persistCriticObservations(
  input: CriticObservationInput,
): string[] {
  const { ctx, artifactPath, review, namespace } = input;
  if (!ctx.doctrine || !review.materialIssues.length) return [];
  const artifactHash = fileSha256(artifactPath);
  if (!artifactHash) throw new Error(`critic observation artifact is missing: ${artifactPath}`);
  return review.materialIssues.map((issue, index) => writeObservation(ctx, core(
    ctx,
    `${namespace}-critic-${index + 1}-${issue.code}`,
    {
      sourceKind: "critic",
      code: issue.code,
      lane: issue.lane,
      severity: issue.severity,
    },
    { reviewArtifactHash: artifactHash, evidence: issue.evidence },
  ))).filter((item): item is string => Boolean(item));
}

function readAuditChecks(audit: AuditBOutcome): AuditCheck[] {
  const machine = audit.event.machine;
  if (typeof machine !== "string" || !existsSync(machine)) return [];
  try {
    const value = JSON.parse(readFileSync(machine, "utf8")) as { checks?: unknown };
    return Array.isArray(value.checks) ? value.checks as AuditCheck[] : [];
  } catch {
    return [];
  }
}

function normalizedCode(value: unknown, fallback: string): string {
  const raw = typeof value === "string" && value ? value : fallback;
  return `QC_${raw.toUpperCase().replace(/[^A-Z0-9]+/g, "_")}`.slice(0, 64);
}

function persistAuditCheck(input: AuditCheckInput): string | null {
  const { ctx, check, artifactHash, namespace, index } = input;
  const status = check.status;
  if (status !== "warn" && status !== "fail") return null;
  const code = normalizedCode(check.name, `CHECK_${index + 1}`);
  return writeObservation(ctx, core(ctx, `${namespace}-qc-${index + 1}-${code}`, {
    sourceKind: "qc",
    code,
    lane: "deterministic-qc",
    severity: status === "fail" ? "critical" : "major",
  }, {
    qcArtifactHash: artifactHash,
    status,
    measurement: { measured: check.measured ?? null, detail: check.detail ?? null },
  }));
}

/** Persist every deterministic QC warning/failure, bound to this run lock. */
export function persistAuditObservations(
  ctx: AutoEditCtx,
  artifactPath: string,
  audit: AuditBOutcome,
  namespace: string,
): string[] {
  if (!ctx.doctrine) return [];
  const artifactHash = fileSha256(artifactPath);
  if (!artifactHash) throw new Error(`QC observation artifact is missing: ${artifactPath}`);
  const checks = readAuditChecks(audit);
  const rows = checks
    .map((check, index) => persistAuditCheck({
      ctx, check, artifactHash, namespace, index,
    }))
    .filter((item): item is string => Boolean(item));
  if (!audit.failure || checks.some((check) => check.status === "fail")) return rows;
  const destination = writeObservation(ctx, core(ctx, `${namespace}-qc-contract-failure`, {
    sourceKind: "qc",
    code: "QC_AUDIT_CONTRACT_FAILURE",
    lane: "deterministic-qc",
    severity: "critical",
  }, {
    qcArtifactHash: artifactHash,
    status: "fail",
    measurement: { failure: audit.failure, event: audit.event },
  }));
  return destination ? [...rows, destination] : rows;
}

/** Persist warn/fail checks from Palmier's native Audit B without adapting its schema. */
export function persistNativeAuditObservations(
  ctx: AutoEditCtx,
  artifactPath: string,
  namespace: string,
): string[] {
  if (!ctx.doctrine || !existsSync(artifactPath)) return [];
  const artifactHash = fileSha256(artifactPath);
  if (!artifactHash) throw new Error(`QC observation artifact is missing: ${artifactPath}`);
  const value = JSON.parse(readFileSync(artifactPath, "utf8")) as { checks?: unknown };
  const checks = Array.isArray(value.checks) ? value.checks as AuditCheck[] : [];
  return checks.map((check, index) => persistAuditCheck({
    ctx, check, artifactHash, namespace, index,
  })).filter((item): item is string => Boolean(item));
}

function writeAuditArtifact(input: AuditObservationInput): string {
  const destination = path.join(input.candidateDir, "audit-outcome.json");
  const temporary = `${destination}.${randomUUID()}.tmp`;
  try {
    writeFileSync(temporary, `${JSON.stringify({
      schemaVersion: 1,
      stage: "deterministic-qc",
      round: input.round,
      audit: input.audit,
    }, null, 2)}\n`, { flag: "wx", mode: 0o600 });
    renameSync(temporary, destination);
  } finally {
    rmSync(temporary, { force: true });
  }
  return destination;
}

export function persistAutoEditAuditOutcome(input: AuditObservationInput): string[] {
  const artifact = writeAuditArtifact(input);
  return persistAuditObservations(
    input.ctx, artifact, input.audit, `audit-a${input.attempt}-r${input.round}`,
  );
}
