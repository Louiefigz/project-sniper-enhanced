import { existsSync } from "node:fs";
import path from "node:path";
import {
  producerAuthorityPaths,
  writeAuthorityObjectSync,
  type ProducerAuthorityPaths,
} from "./producer-authority-files";
import {
  type AutoEditGenesisExpectation,
  type AutoEditGenesisFacts,
  observeAutoEditGenesisFactsSync,
} from "./producer-auto-edit-genesis-facts";
import {
  advanceAutoEditRenderedRevisionSync,
  type AutoEditRenderedTransitionHooks,
} from "./producer-auto-edit-rendered-transition";
import {
  initializeProducerAuthoritySync,
} from "./producer-revision-head";

export interface AutoEditGenesisOutcome {
  status: "initialized" | "advanced" | "reused";
  revisionHash: string;
}

function storeGenesisObjects(
  paths: ProducerAuthorityPaths,
  facts: AutoEditGenesisFacts,
): {
  requestLedgerHash: string;
  renderGraphHash: string;
  projectionReceiptHash: string;
  graphReceiptHash: string;
  candidatePointerHash: string;
} {
  const ledger = writeAuthorityObjectSync(paths.objects.requests, {
    schemaVersion: 1,
    kind: "producer-empty-request-ledger",
  });
  const graph = writeAuthorityObjectSync(
    paths.objects.graphs, facts.renderGraph);
  const projection = writeAuthorityObjectSync(
    paths.objects.projections, facts.projection);
  const projectionReceipt = writeAuthorityObjectSync(
    paths.objects.projections, facts.projectionReceipt);
  const receipt = writeAuthorityObjectSync(
    paths.objects.receipts, facts.renderGraphReceipt);
  const pointer = writeAuthorityObjectSync(
    paths.objects.receipts, facts.renderGraphCandidatePointer);
  if (graph.hash !== facts.authoritativeSidecars.stagedRenderGraphV1
      || receipt.hash
        !== facts.authoritativeSidecars.stagedRenderGraphReceiptV1
      || pointer.hash
        !== facts.authoritativeSidecars.stagedRenderGraphCandidatePointerV1
      || projection.hash
        !== facts.authoritativeSidecars.compatibilityTimelineProjectionV1) {
    throw new Error("staged render graph generation changed before genesis");
  }
  return {
    requestLedgerHash: ledger.hash,
    renderGraphHash: graph.hash,
    projectionReceiptHash: projectionReceipt.hash,
    graphReceiptHash: receipt.hash,
    candidatePointerHash: pointer.hash,
  };
}

/** Initialize ordinary Auto Edit only from a fully rendered, proved candidate. */
export function initializeAutoEditProducerAuthoritySync(
  input: AutoEditGenesisExpectation,
  hooks: AutoEditRenderedTransitionHooks = {},
): AutoEditGenesisOutcome {
  const facts = observeAutoEditGenesisFactsSync(input);
  const paths = producerAuthorityPaths(input.producerDir);
  const genesisPath = path.join(paths.advances, "GENESIS.json");
  if (existsSync(genesisPath)) {
    return advanceAutoEditRenderedRevisionSync(input, facts, hooks);
  }
  const stored = storeGenesisObjects(paths, facts);
  const initialized = initializeProducerAuthoritySync(
    input.producerDir,
    {
      schemaVersion: 1,
      parentRevisionHash: null,
      planContentHash: facts.planContentHash,
      manifestHash: facts.manifestHash,
      sourceSnapshotSetHash: facts.sourceSnapshotSetHash,
      transcriptTimingHash: facts.transcriptTimingHash,
      timelineMapHash: facts.timelineMapHash,
      canvasProfileHash: facts.canvasProfileHash,
      destinationProfileHashes: facts.destinationProfileHashes,
      pictureLockHash: facts.pictureLockHash,
      workflowState: "READY_TO_FINALIZE",
      requestLedgerHash: stored.requestLedgerHash,
      renderGraphHash: stored.renderGraphHash,
      projectionReceiptHash: stored.projectionReceiptHash,
      authoritativeSidecars: {
        ...facts.authoritativeSidecars,
        initialRenderGraphReceipt: stored.graphReceiptHash,
        initialRenderGraphCandidatePointer: stored.candidatePointerHash,
      },
    },
    facts.planObject,
  );
  return {
    status: initialized.reused ? "reused" : "initialized",
    revisionHash: initialized.revisionHash,
  };
}

export type { AutoEditGenesisExpectation };
