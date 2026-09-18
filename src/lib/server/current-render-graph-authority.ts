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

const POINTER_KEYS = [
  "schemaVersion", "graphHash", "receiptHash",
] as const;

export interface CurrentRenderGraphAuthority {
  graphHash: string;
  receiptHash: string;
  activePointerHash: string;
  finalMediaHash: string;
}

export interface CurrentRenderGraphExpectation {
  producerDir: string;
  expectedGraphHash: string;
  expectedFinalHash: string;
}

function activePointer(
  root: string,
): { graphHash: string; receiptHash: string; hash: string } {
  const pointerPath = path.join(root, "ACTIVE.json");
  assertAuthorityFileSync(
    pointerPath, root, "active render graph pointer");
  const pointer = objectValue(
    readAuthorityJsonSync(pointerPath), "active render graph pointer");
  exactKeys(pointer, POINTER_KEYS, POINTER_KEYS, "active render graph pointer");
  if (pointer.schemaVersion !== 1) {
    throw new Error("active render graph pointer version is unsupported");
  }
  return {
    graphHash: sha256(pointer.graphHash, "active graph hash"),
    receiptHash: sha256(pointer.receiptHash, "active receipt hash"),
    hash: canonicalJsonSha256(pointer),
  };
}

/** Reopen ACTIVE, its immutable generation, and the exact promoted final. */
export function observeCurrentRenderGraphAuthoritySync(
  input: CurrentRenderGraphExpectation,
): CurrentRenderGraphAuthority {
  const producer = canonicalProducerDirectorySync(input.producerDir);
  const root = path.join(producer, ".render-graph-v1");
  const pointer = activePointer(root);
  if (pointer.graphHash !== input.expectedGraphHash) {
    throw new Error("foreign render graph became ACTIVE during promotion");
  }
  observeRenderGraphGenerationSync({
    producerDir: producer,
    graphHash: pointer.graphHash,
    receiptHash: pointer.receiptHash,
    expectedMediaPath: path.join(producer, "final.mp4"),
    expectedMediaHash: input.expectedFinalHash,
  });
  return {
    graphHash: pointer.graphHash,
    receiptHash: pointer.receiptHash,
    activePointerHash: pointer.hash,
    finalMediaHash: input.expectedFinalHash,
  };
}
