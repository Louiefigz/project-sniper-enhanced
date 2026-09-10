import path from "node:path";
import type { ProjectRevision } from
  "@/lib/producer/contracts/project-revision";
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

export interface CutRepairCandidateV1Validation {
  candidate: Record<string, unknown>;
  parts: Record<string, string>;
  fragment: MediaProof;
  composite: MediaProof;
  terminal: MediaProof;
  version: 1;
}

const CANDIDATE_KEYS = [
  "schemaVersion", "kind", "status", "operationHash", "fragmentReceipt",
  "childPictureLock", "childPictureLockHash", "supersessionReceipt",
  "supersessionHash", "palmierDisposition", "captionRevalidation",
  "compositeReceipt", "invariantProof", "invariantProofHash",
] as const;

const PROOF_KEYS = [
  "schemaVersion", "kind", "operationHash", "fragmentReceiptHash",
  "childPictureLockHash", "supersessionHash", "palmierDispositionHash",
  "captionRevalidationHash", "terminalCompositeProved",
  "terminalCompositeReceiptHash", "totalOutputFramesPreserved",
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

function parts(candidate: Record<string, unknown>): Record<string, string> {
  const values = {
    fragment: canonicalJsonSha256(
      objectValue(candidate.fragmentReceipt, "fragment receipt")),
    composite: canonicalJsonSha256(
      objectValue(candidate.compositeReceipt, "composite receipt")),
    pictureLock: canonicalJsonSha256(
      objectValue(candidate.childPictureLock, "child picture lock")),
    supersession: canonicalJsonSha256(
      objectValue(candidate.supersessionReceipt, "supersession receipt")),
    caption: canonicalJsonSha256(
      objectValue(candidate.captionRevalidation, "caption revalidation")),
    palmier: canonicalJsonSha256(
      objectValue(candidate.palmierDisposition, "Palmier disposition")),
    invariant: canonicalJsonSha256(
      objectValue(candidate.invariantProof, "invariant proof")),
    candidate: canonicalJsonSha256(candidate),
  };
  if (candidate.childPictureLockHash !== values.pictureLock
      || candidate.supersessionHash !== values.supersession) {
    throw new Error("cut repair candidate has substituted lock objects");
  }
  return values;
}

function assertKinds(candidate: Record<string, unknown>): void {
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
    throw new Error("cut repair candidate contains malformed proof objects");
  }
}

function assertInvariant(
  candidate: Record<string, unknown>,
  values: Record<string, string>,
  invariantProofHash: string,
): void {
  const proof = objectValue(candidate.invariantProof, "cut repair invariant proof");
  const caption = objectValue(candidate.captionRevalidation, "caption revalidation");
  exactKeys(proof, PROOF_KEYS, PROOF_KEYS, "cut repair invariant proof");
  if (proof.schemaVersion !== 1 || proof.kind !== "cut-repair-invariant-proof"
      || proof.operationHash !== candidate.operationHash
      || proof.fragmentReceiptHash !== values.fragment
      || proof.childPictureLockHash !== values.pictureLock
      || proof.supersessionHash !== values.supersession
      || proof.palmierDispositionHash !== values.palmier
      || proof.captionRevalidationHash !== caption.revalidationHash
      || proof.terminalCompositeReceiptHash !== values.composite
      || proof.terminalCompositeProved !== true
      || proof.totalOutputFramesPreserved !== true
      || candidate.invariantProofHash !== values.invariant
      || values.invariant !== invariantProofHash) {
    throw new Error("cut repair invariant proof does not bind its actual objects");
  }
}

function assertComposite(
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
    throw new Error("cut repair composite does not bind preserved decoded media");
  }
}

function assertRevision(
  revision: ProjectRevision,
  values: Record<string, string>,
): void {
  const expected = {
    pictureLock: values.pictureLock,
    pictureLockSupersession: values.supersession,
    cutRepairFragmentReceipt: values.fragment,
    cutRepairCompositeReceipt: values.composite,
    cutRepairInvariantProof: values.invariant,
    cutRepairCandidate: values.candidate,
    captionRepairRevalidation: values.caption,
    palmierCutRepairDisposition: values.palmier,
  };
  if (Object.entries(expected).some(
    ([key, hash]) => revision.authoritativeSidecars[key] !== hash,
  )) {
    throw new Error("cut repair revision sidecars do not bind proved artifacts");
  }
}

/** Validate the legacy diagnostic-composite terminal candidate. */
export function validateCutRepairCandidateV1(
  candidate: Record<string, unknown>,
  actionHash: string,
  revision: ProjectRevision,
  invariantProofHash: string,
): CutRepairCandidateV1Validation {
  exactKeys(candidate, CANDIDATE_KEYS, CANDIDATE_KEYS, "cut repair candidate");
  if (candidate.schemaVersion !== 1
      || candidate.kind !== "cut-repair-candidate"
      || candidate.status !== "candidate-proved"
      || candidate.operationHash !== actionHash) {
    throw new Error("cut repair candidate is not a proved selected operation");
  }
  assertKinds(candidate);
  const values = parts(candidate);
  assertInvariant(candidate, values, invariantProofHash);
  const fragment = outputMedia(
    candidate.fragmentReceipt, "fragment receipt", actionHash);
  const composite = outputMedia(
    candidate.compositeReceipt, "composite receipt", actionHash);
  assertComposite(candidate, values, fragment.sha256);
  assertRevision(revision, values);
  return {
    candidate, parts: values, fragment, composite,
    terminal: composite, version: 1,
  };
}
