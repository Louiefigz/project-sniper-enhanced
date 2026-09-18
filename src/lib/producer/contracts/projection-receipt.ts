import {
  exactKeys,
  objectValue,
  sha256,
  stringValue,
} from "./validation";

export interface ProjectionReceiptV1 {
  schemaVersion: 1;
  canonicalPlanHash: string;
  manifestHash: string;
  sourceSnapshotSetHash: string;
  compilerHash: string;
  timelineMapHash: string;
  projectionHash: string;
  generationPath: string;
}

const KEYS = [
  "schemaVersion", "canonicalPlanHash", "manifestHash", "sourceSnapshotSetHash",
  "compilerHash", "timelineMapHash", "projectionHash", "generationPath",
] as const;

export function parseProjectionReceiptV1(value: unknown): ProjectionReceiptV1 {
  const receipt = objectValue(value, "ProjectionReceiptV1");
  exactKeys(receipt, KEYS, KEYS, "ProjectionReceiptV1");
  if (receipt.schemaVersion !== 1) {
    throw new Error("ProjectionReceiptV1 version is unsupported");
  }
  const generationPath = stringValue(
    receipt.generationPath,
    "ProjectionReceiptV1.generationPath",
    512,
  );
  if (generationPath.startsWith("/") || generationPath.split("/").includes("..")) {
    throw new Error("ProjectionReceiptV1.generationPath must be relative and normalized");
  }
  return {
    schemaVersion: 1,
    canonicalPlanHash: sha256(receipt.canonicalPlanHash, "canonicalPlanHash"),
    manifestHash: sha256(receipt.manifestHash, "manifestHash"),
    sourceSnapshotSetHash: sha256(
      receipt.sourceSnapshotSetHash,
      "sourceSnapshotSetHash",
    ),
    compilerHash: sha256(receipt.compilerHash, "compilerHash"),
    timelineMapHash: sha256(receipt.timelineMapHash, "timelineMapHash"),
    projectionHash: sha256(receipt.projectionHash, "projectionHash"),
    generationPath,
  };
}
