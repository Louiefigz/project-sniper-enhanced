import path from "node:path";
import type { ProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import {
  parseCutRepairRenderedCandidateV1,
  type CutRepairRenderedCandidateV1,
} from "@/lib/producer/contracts/cut-repair-rendered-candidate";
import {
  exactKeys,
  objectValue,
  sha256,
} from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { parsePalmierCutRepairDispositionV1 } from
  "@/lib/producer/contracts/palmier-cut-repair-disposition";
import { parseCutRepairRetimeV1 } from
  "@/lib/producer/contracts/cut-repair-retime";

interface MediaProof {
  path: string;
  sha256: string;
}

export interface CutRepairCandidateV2Validation {
  parts: Record<string, string>;
  fragment: MediaProof;
  composite: MediaProof;
  terminal: MediaProof;
  renderedCandidate: CutRepairRenderedCandidateV1;
}

const CANDIDATE_KEYS = [
  "schemaVersion", "kind", "status", "operationHash", "fragmentReceipt",
  "childPictureLock", "childPictureLockHash", "supersessionReceipt",
  "supersessionHash", "palmierDisposition", "captionRevalidation",
  "compositeReceipt", "renderedCandidate", "renderedCandidateHash",
  "invariantProof", "invariantProofHash",
] as const;

const PROOF_KEYS = [
  "schemaVersion", "kind", "operationHash", "fragmentReceiptHash",
  "childPictureLockHash", "supersessionHash", "palmierDispositionHash",
  "captionRevalidationHash", "diagnosticCompositeReceiptHash",
  "renderedCandidateHash", "terminalRenderedPlanProved",
  "terminalCandidateSha256", "totalOutputFramesPreserved",
] as const;

function outputMedia(
  receipt: unknown,
  label: string,
  operationHash: string,
): MediaProof {
  const row = objectValue(receipt, label);
  const output = objectValue(row.output, `${label}.output`);
  if (row.operationHash !== operationHash
      || row.exactOutputDurationPreserved !== true
      || typeof output.path !== "string" || !path.isAbsolute(output.path)) {
    throw new Error(`${label} is not bound to duration-preserving media`);
  }
  return {
    path: output.path,
    sha256: sha256(output.sha256, `${label}.output.sha256`),
  };
}

function parts(
  candidate: Record<string, unknown>,
): Record<string, string> {
  const names = {
    fragment: "fragmentReceipt",
    composite: "compositeReceipt",
    pictureLock: "childPictureLock",
    supersession: "supersessionReceipt",
    caption: "captionRevalidation",
    palmier: "palmierDisposition",
    rendered: "renderedCandidate",
    invariant: "invariantProof",
  } as const;
  return {
    ...Object.fromEntries(Object.entries(names).map(([name, key]) => [
      name,
      canonicalJsonSha256(objectValue(candidate[key], key)),
    ])),
    candidate: canonicalJsonSha256(candidate),
  };
}

function assertPartKinds(candidate: Record<string, unknown>): void {
  const fragment = objectValue(candidate.fragmentReceipt, "fragment receipt");
  parseCutRepairRetimeV1(fragment.retime);
  const composite = objectValue(candidate.compositeReceipt, "composite receipt");
  const supersession = objectValue(
    candidate.supersessionReceipt, "supersession receipt");
  const caption = objectValue(candidate.captionRevalidation, "caption revalidation");
  const palmier = parsePalmierCutRepairDispositionV1(
    candidate.palmierDisposition);
  if (fragment.schemaVersion !== 1 || fragment.kind !== "cut-repair-fragment"
      || fragment.evidencePolicy
        !== "alignment-and-vad-are-bounded-evidence-not-sole-audibility-proof"
      || composite.schemaVersion !== 1 || composite.kind !== "cut-repair-composite"
      || objectValue(candidate.childPictureLock, "child picture lock")
        .schemaVersion !== 1
      || supersession.schemaVersion !== 1
      || supersession.repairOperationHash !== candidate.operationHash
      || caption.schemaVersion !== 1
      || caption.kind !== "caption-repair-revalidation"
      || caption.operationHash !== candidate.operationHash
      || palmier.operationHash !== candidate.operationHash) {
    throw new Error("cut repair V2 candidate contains malformed proof objects");
  }
}

function assertDiagnosticComposite(
  candidate: Record<string, unknown>,
  values: Record<string, string>,
  fragmentSha256: string,
): void {
  const composite = objectValue(candidate.compositeReceipt, "composite receipt");
  const inputs = objectValue(composite.inputs, "composite receipt inputs");
  const oracle = objectValue(
    composite.outsideDirtyOracle, "composite outside-dirty oracle");
  if (composite.fragmentReceiptHash !== values.fragment
      || inputs.fragmentSha256 !== fragmentSha256
      || oracle.pictureMatches !== true || oracle.pcmMatches !== true) {
    throw new Error("diagnostic splice does not prove the authorized dirty window");
  }
}

function assertInvariant(
  candidate: Record<string, unknown>,
  values: Record<string, string>,
  terminalSha256: string,
  invariantProofHash: string,
): void {
  const proof = objectValue(candidate.invariantProof, "cut repair invariant proof");
  exactKeys(proof, PROOF_KEYS, PROOF_KEYS, "cut repair V2 invariant proof");
  const caption = objectValue(candidate.captionRevalidation, "caption revalidation");
  if (proof.schemaVersion !== 2 || proof.kind !== "cut-repair-invariant-proof"
      || proof.operationHash !== candidate.operationHash
      || proof.fragmentReceiptHash !== values.fragment
      || proof.childPictureLockHash !== values.pictureLock
      || proof.supersessionHash !== values.supersession
      || proof.palmierDispositionHash !== values.palmier
      || proof.captionRevalidationHash !== caption.revalidationHash
      || proof.diagnosticCompositeReceiptHash !== values.composite
      || proof.renderedCandidateHash !== values.rendered
      || proof.terminalRenderedPlanProved !== true
      || proof.terminalCandidateSha256 !== terminalSha256
      || proof.totalOutputFramesPreserved !== true
      || candidate.renderedCandidateHash !== values.rendered
      || candidate.invariantProofHash !== values.invariant
      || values.invariant !== invariantProofHash) {
    throw new Error("cut repair V2 invariant does not bind terminal plan media");
  }
}

function assertRevisionSidecars(
  revision: ProjectRevision,
  values: Record<string, string>,
): void {
  const expected = {
    pictureLock: values.pictureLock,
    pictureLockSupersession: values.supersession,
    cutRepairFragmentReceipt: values.fragment,
    cutRepairCompositeReceipt: values.composite,
    cutRepairRenderedCandidate: values.rendered,
    cutRepairInvariantProof: values.invariant,
    cutRepairCandidate: values.candidate,
    captionRepairRevalidation: values.caption,
    palmierCutRepairDisposition: values.palmier,
  };
  if (Object.entries(expected).some(
    ([key, hash]) => revision.authoritativeSidecars[key] !== hash,
  )) {
    throw new Error("cut repair revision does not bind V2 terminal artifacts");
  }
}

/** Validate a V2 candidate whose terminal authority is the exact plan render. */
export function validateCutRepairCandidateV2(
  candidate: Record<string, unknown>,
  actionHash: string,
  revision: ProjectRevision,
  invariantProofHash: string,
): CutRepairCandidateV2Validation {
  exactKeys(candidate, CANDIDATE_KEYS, CANDIDATE_KEYS, "cut repair V2 candidate");
  if (candidate.schemaVersion !== 2
      || candidate.kind !== "cut-repair-candidate"
      || candidate.status !== "candidate-proved"
      || candidate.operationHash !== actionHash) {
    throw new Error("cut repair V2 candidate is not the selected operation");
  }
  assertPartKinds(candidate);
  const values = parts(candidate);
  if (candidate.childPictureLockHash !== values.pictureLock
      || candidate.supersessionHash !== values.supersession) {
    throw new Error("cut repair V2 candidate has substituted lock objects");
  }
  const fragment = outputMedia(
    candidate.fragmentReceipt, "fragment receipt", actionHash);
  const composite = outputMedia(
    candidate.compositeReceipt, "diagnostic composite receipt", actionHash);
  assertDiagnosticComposite(candidate, values, fragment.sha256);
  const renderedCandidate = parseCutRepairRenderedCandidateV1(
    candidate.renderedCandidate);
  const terminal = {
    path: renderedCandidate.candidatePath,
    sha256: renderedCandidate.candidateSha256,
  };
  assertInvariant(
    candidate, values, terminal.sha256, invariantProofHash);
  assertRevisionSidecars(revision, values);
  return {
    parts: values,
    fragment,
    composite,
    terminal,
    renderedCandidate,
  };
}
