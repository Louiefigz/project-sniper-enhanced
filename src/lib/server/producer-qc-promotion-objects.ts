import path from "node:path";
import type { ApprovalRecord } from "./auto-edit-approval";
import {
  assertObjectHashSync,
  readAuthorityJsonSync,
  writeAuthorityObjectSync,
  type ProducerAuthorityPaths,
} from "./producer-authority-files";
import type { CurrentRenderGraphAuthority } from
  "./current-render-graph-authority";

interface QcPromotionObjectInput {
  producerDir: string;
  graph: CurrentRenderGraphAuthority;
  approval: ApprovalRecord;
  approvalHash: string;
}

function storeExact(
  directory: string,
  value: unknown,
  expectedHash: string,
  label: string,
): void {
  if (writeAuthorityObjectSync(directory, value).hash !== expectedHash) {
    throw new Error(`${label} changed during QC revision materialization`);
  }
}

/** Copy every live QC/graph fact into immutable revision object storage. */
export function storeQcPromotionObjectsSync(
  paths: ProducerAuthorityPaths,
  input: QcPromotionObjectInput,
): void {
  assertObjectHashSync(paths.objects.graphs, input.graph.graphHash);
  const generation = path.join(
    input.producerDir,
    ".render-graph-v1",
    "generations",
    input.graph.graphHash,
  );
  const receipt = readAuthorityJsonSync(path.join(
    generation, "receipts", `${input.graph.receiptHash}.json`));
  const pointer = readAuthorityJsonSync(path.join(
    input.producerDir, ".render-graph-v1", "ACTIVE.json"));
  storeExact(
    paths.objects.receipts,
    input.approval,
    input.approvalHash,
    "QC approval",
  );
  storeExact(
    paths.objects.receipts,
    receipt,
    input.graph.receiptHash,
    "current render graph receipt",
  );
  storeExact(
    paths.objects.receipts,
    pointer,
    input.graph.activePointerHash,
    "current render graph pointer",
  );
}
