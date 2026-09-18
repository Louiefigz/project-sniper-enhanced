import path from "node:path";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { exactKeys, objectValue, sha256, uuid } from "@/lib/producer/contracts/validation";
import { bodyTimestamp } from "@/lib/producer/contracts/guided-body-activation-v1";
import { parseBodyFileReference, type BodyFileReference } from "@/lib/producer/contracts/guided-body-media-v1";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import { canonicalJsonSha256 as hash } from "./auto-edit-hash";
import { readGuidedObject, writeGuidedObject } from "./guided-cut-v2-store";
import { createOpeningRecord, assertOpeningRecord } from "./guided-opening-process-activation";
import { readHistoricalBodyActivation } from "./guided-body-activation";
import { commitGuidedJob } from "./guided-cut-v2";
import type { BodyActivation, BodyExecutionControl } from "./guided-body-process-tools";

export type BodyPhase = "process" | "cleanup" | "candidate";
const PHASES = {
  process: { pointer: "bodyProcessOutcomeHash", prior: "bodyActivationHash", refs: ["intent", "outcome"] },
  cleanup: { pointer: "bodyCleanupHash", prior: "bodyProcessOutcomeHash", refs: ["start", "output"] },
  candidate: { pointer: "bodyCandidateHash", prior: "bodyCleanupHash", refs: ["start", "output", "receipt", "result"] },
} as const;
export interface BodyPhaseFact {
  schemaVersion: 1; kind: string; scope: "owned-private-body-phase-not-approval"; phase: BodyPhase;
  requestId: string; executionId: string; activationHash: string; beforeJournalHash: string;
  clockHash: string; generationStartedAt: string; createdAt: string; references: Record<string, BodyFileReference>;
}
type Journal = ReturnType<typeof observeHumanCutJob>;

export function parseBodyPhaseFact(value: unknown, phase: BodyPhase): BodyPhaseFact {
  const row = objectValue(value, "body phase"), keys = ["schemaVersion", "kind", "scope", "phase", "requestId", "executionId",
    "activationHash", "beforeJournalHash", "clockHash", "generationStartedAt", "createdAt", "references"];
  exactKeys(row, keys, keys, "body phase");
  if (row.schemaVersion !== 1 || row.kind !== `guided-body-${phase}-fact` || row.phase !== phase
      || row.scope !== "owned-private-body-phase-not-approval") throw new Error("Body phase fact role changed");
  uuid(row.requestId, "requestId"); uuid(row.executionId, "executionId");
  for (const key of ["activationHash", "beforeJournalHash", "clockHash"]) sha256(row[key], key);
  if (bodyTimestamp(row.createdAt) < bodyTimestamp(row.generationStartedAt)) throw new Error("Body phase predates original request");
  const refs = objectValue(row.references, "body phase references"), names = [...PHASES[phase].refs];
  exactKeys(refs, names, names, "body phase references"); Object.values(refs).forEach(parseBodyFileReference);
  return row as unknown as BodyPhaseFact;
}

/** Every phase permits one pointer/timestamp change, never an arbitrary descendant of approval. */
export function bodyPhaseJournal(before: Journal, fact: BodyPhaseFact, factHash: string) {
  const policy = PHASES[fact.phase], job = before.job, pointer = job.guidedHandoffV2;
  if (fact.beforeJournalHash !== before.sha256 || job.status !== "treatment_admitted" || !pointer?.[policy.prior]
      || pointer[policy.pointer] || pointer.bodyActivationHash !== fact.activationHash || job.updatedAt > fact.createdAt) {
    throw new Error("Body phase has no exact current predecessor");
  }
  return { ...job, updatedAt: fact.createdAt, guidedHandoffV2: { ...pointer, [policy.pointer]: factHash } };
}

/** Separately bind only actual held return records. Caller still owes stop/cleanup/media and final clock guards. */
export function commitBodyPhase(input: { held: BodyActivation; current: Journal; phase: BodyPhase;
  references: Record<string, BodyFileReference>; guard: () => void }) {
  const { held, current, phase, references, guard } = input, a = held.activation, dir = held.admission.before.job.ctx.dir;
  guard();
  const fact = parseBodyPhaseFact({ schemaVersion: 1, kind: `guided-body-${phase}-fact`, scope: "owned-private-body-phase-not-approval", phase,
    requestId: a.requestId, executionId: a.executionId, activationHash: held.activationHash, beforeJournalHash: current.sha256,
    clockHash: a.clockHash, generationStartedAt: a.generationStartedAt, createdAt: new Date().toISOString(), references }, phase);
  const factHash = hash(fact);
  const record = createOpeningRecord(path.join(path.dirname(held.activationPath), `body-${phase}-${factHash}.json`), { ...fact });
  if (writeGuidedObject(dir, fact) !== factHash) throw new Error("Body phase CAS bytes differ from actual held bytes");
  saveHumanCutJobSnapshot(dir, current);
  const commitGuard = () => {
    guard(); assertOpeningRecord(record); assertBodyPhaseReferences(fact, held);
    if (new Date().toISOString() < fact.createdAt) throw new Error("Body clock rolled back before phase commit");
    guard();
  };
  commitGuidedJob({ beforeHash: current.sha256, guard: commitGuard, job: bodyPhaseJournal(current, fact, factHash) });
  return { fact, factHash, current: observeHumanCutJob(dir) };
}

export function assertBodyPhaseReferences(fact: BodyPhaseFact, held: BodyExecutionControl): void {
  const root = path.dirname(held.activationPath);
  for (const reference of Object.values(fact.references)) {
    const relative = path.relative(root, reference.path);
    if (relative.startsWith("..") || path.isAbsolute(relative) || readCutPreviewObject(reference.path).sha256 !== reference.sha256) {
      throw new Error("Body phase reference is changed or outside its owned execution");
    }
  }
}

export function retainedBodyJournal(dir: string, expected: string): Journal {
  const raw = readCutPreviewObject(path.join(dir, "human-cut-job-snapshots", `${sha256(expected, "body journal hash")}.json`));
  const current = { ...raw, job: parseAutoEditJobRecord(raw.value) };
  if (raw.sha256 !== expected || current.job.ctx.dir !== dir) throw new Error("Body phase snapshot is changed or transplanted");
  return current;
}

function fromJournal(dir: string, phase: BodyPhase, current: Journal): { fact: BodyPhaseFact; factHash: string; current: Journal; held: BodyActivation } {
  const factHash = current.job.guidedHandoffV2?.[PHASES[phase].pointer];
  if (!factHash) throw new Error("No durable body phase fact exists");
  const fact = parseBodyPhaseFact(readGuidedObject(dir, factHash), phase), before = retainedBodyJournal(dir, fact.beforeJournalHash);
  if (hash(current.job) !== hash(bodyPhaseJournal(before, fact, factHash))) throw new Error("Body phase journal has unknown changes");
  const held = phase === "process" ? readHistoricalBodyActivation(dir, before.sha256)
    : fromJournal(dir, phase === "cleanup" ? "process" : "cleanup", before).held;
  if (fact.activationHash !== held.activationHash || fact.executionId !== held.activation.executionId
      || fact.requestId !== held.activation.requestId || fact.clockHash !== held.activation.clockHash
      || fact.generationStartedAt !== held.activation.generationStartedAt) throw new Error("Body phase moved to another invocation");
  const file = path.join(path.dirname(held.activationPath), `body-${phase}-${factHash}.json`);
  if (readCutPreviewObject(file).sha256 !== factHash) throw new Error("Body private phase fact changed");
  assertBodyPhaseReferences(fact, held); retainedBodyJournal(dir, before.sha256);
  return { fact, factHash, current, held };
}

export function readBodyPhase(dir: string, phase: BodyPhase) {
  const current = observeHumanCutJob(dir), result = fromJournal(dir, phase, current);
  if (observeHumanCutJob(dir).sha256 !== current.sha256) throw new Error("Body phase changed during readback");
  return result;
}

/** Known later phases may inspect only the actual retained predecessor, never synthesize current authority. */
export function readHistoricalBodyPhase(dir: string, phase: BodyPhase, journalHash: string) {
  const current = retainedBodyJournal(dir, journalHash), result = fromJournal(dir, phase, current);
  retainedBodyJournal(dir, journalHash); return result;
}
