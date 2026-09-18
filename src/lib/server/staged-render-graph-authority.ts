import path from "node:path";
import {
  exactKeys,
  objectValue,
  sha256,
} from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { readAuthorityJsonSync } from "./producer-authority-files";
import {
  assertAuthorityFileSync,
  canonicalProducerDirectorySync,
  observeRenderGraphGenerationSync,
} from "./render-graph-generation-authority";

const CANDIDATE_KEYS = [
  "schemaVersion", "kind", "candidatePath", "candidateSha256",
  "graphHash", "receiptHash", "previousGraphHash", "previousReceiptHash",
] as const;

export interface StagedRenderGraphExpectation {
  producerDir: string;
  candidatePath: string;
  expectedCandidateHash: string;
}

export interface StagedRenderGraphAuthority {
  graphHash: string;
  receiptHash: string;
  candidatePointerHash: string;
  candidateMediaHash: string;
  previousGraphHash: string | null;
  previousReceiptHash: string | null;
}

function nullableHash(value: unknown, label: string): string | null {
  return value === null ? null : sha256(value, label);
}

function canonicalCandidate(
  producer: string,
  candidatePath: string,
): string {
  if (!path.isAbsolute(candidatePath)) {
    throw new Error("render graph candidate path is not absolute");
  }
  const candidate = path.resolve(candidatePath);
  assertAuthorityFileSync(candidate, producer, "render graph candidate");
  return candidate;
}

function candidatePointerPath(
  producer: string,
  candidate: string,
): string {
  const key = canonicalJsonSha256({
    kind: "current-render-candidate-path",
    path: candidate,
  });
  return path.join(
    producer, ".render-graph-v1", "candidates", `${key}.json`);
}

/** Reopen a staged candidate pointer, generation, and still-private media. */
export function observeStagedRenderGraphAuthoritySync(
  input: StagedRenderGraphExpectation,
): StagedRenderGraphAuthority {
  const producer = canonicalProducerDirectorySync(input.producerDir);
  const candidate = canonicalCandidate(producer, input.candidatePath);
  const root = path.join(producer, ".render-graph-v1");
  const pointerPath = candidatePointerPath(producer, candidate);
  assertAuthorityFileSync(
    pointerPath, root, "staged render graph pointer");
  const value = objectValue(
    readAuthorityJsonSync(pointerPath), "staged render graph pointer");
  exactKeys(
    value, CANDIDATE_KEYS, CANDIDATE_KEYS, "staged render graph pointer");
  if (value.schemaVersion !== 1
      || value.kind !== "current-render-graph-candidate"
      || value.candidatePath !== candidate) {
    throw new Error("staged render graph pointer is malformed");
  }
  const candidateHash = sha256(
    value.candidateSha256, "staged candidate hash");
  const expectedHash = sha256(
    input.expectedCandidateHash, "expected staged candidate hash");
  if (candidateHash !== expectedHash) {
    throw new Error("staged render graph pointer binds foreign media");
  }
  const graphHash = sha256(value.graphHash, "staged graph hash");
  const receiptHash = sha256(value.receiptHash, "staged receipt hash");
  const previousGraphHash = nullableHash(
    value.previousGraphHash, "previous staged graph hash");
  const previousReceiptHash = nullableHash(
    value.previousReceiptHash, "previous staged receipt hash");
  if ((previousGraphHash === null) !== (previousReceiptHash === null)) {
    throw new Error("staged render graph parent is malformed");
  }
  observeRenderGraphGenerationSync({
    producerDir: producer,
    graphHash,
    receiptHash,
    expectedMediaPath: candidate,
    expectedMediaHash: candidateHash,
  });
  return {
    graphHash,
    receiptHash,
    candidatePointerHash: canonicalJsonSha256(value),
    candidateMediaHash: candidateHash,
    previousGraphHash,
    previousReceiptHash,
  };
}
