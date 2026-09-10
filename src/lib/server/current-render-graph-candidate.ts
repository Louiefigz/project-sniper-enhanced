import path from "node:path";
import {
  promoteApprovedCandidate,
  type ApprovalRecord,
  type CandidatePromotionHooks,
} from "./auto-edit-quality-artifacts";
import {
  observeCurrentRenderGraphAuthoritySync,
} from "./current-render-graph-authority";
import {
  commitProducerQcPromotionSync,
  prepareProducerQcPromotionSync,
  type ProducerQcPromotionPreparation,
} from "./producer-qc-promotion";
import {
  observeStagedRenderGraphAuthoritySync,
} from "./staged-render-graph-authority";
import { recoverProducerQcPromotionIntentSync } from
  "./producer-qc-promotion-intent";
import {
  recoverRenderGraphPromotionSync,
  renderGraphPromotionCrashHooks,
  type RenderGraphPromotionCrashInput,
} from "./current-render-graph-promotion-recovery";
import {
  activateOrResolve,
  candidateArgs,
  runCandidateCommand,
  verifiedGraphHash,
  type CandidateCommand,
} from "./current-render-graph-candidate-command";

export interface RenderGraphPromotionRuntime {
  command?: CandidateCommand;
  approvalWriter?: CandidatePromotionHooks["approvalWriter"];
  stagedObserver?: typeof observeStagedRenderGraphAuthoritySync;
  activeObserver?: typeof observeCurrentRenderGraphAuthoritySync;
  qcPreparation?: typeof prepareProducerQcPromotionSync;
  qcCommit?: typeof commitProducerQcPromotionSync;
  afterPromotionBoundary?: CandidatePromotionHooks["afterBoundary"];
}

interface GraphPromotion {
  candidate: string;
  producerDir: string;
  expectedSha256: string;
  expectedGraphHash: string;
  command: CandidateCommand;
}

interface GraphPromotionContext {
  graph: GraphPromotion;
  preparation: ProducerQcPromotionPreparation;
  record: ApprovalRecord;
  runtime: RenderGraphPromotionRuntime;
}

function crashInput(
  graph: GraphPromotion,
  runtime: RenderGraphPromotionRuntime,
): RenderGraphPromotionCrashInput {
  return {
    candidate: graph.candidate,
    producerDir: graph.producerDir,
    expectedSha256: graph.expectedSha256,
    command: graph.command,
    productionQc: runtime.qcPreparation === undefined
      && runtime.qcCommit === undefined,
  };
}

function promotionHooks(
  context: GraphPromotionContext,
): CandidatePromotionHooks {
  const { graph, preparation, record, runtime } = context;
  const recovery = renderGraphPromotionCrashHooks(
    crashInput(graph, runtime));
  return {
    beforeApproval: () => activateOrResolve(graph),
    afterApproval: () => {
      const observeActive = runtime.activeObserver
        ?? observeCurrentRenderGraphAuthoritySync;
      const authority = observeActive({
        producerDir: graph.producerDir,
        expectedGraphHash: graph.expectedGraphHash,
        expectedFinalHash: record.finalHash,
      });
      (runtime.qcCommit ?? commitProducerQcPromotionSync)({
        preparation, graph: authority, approval: record,
      });
    },
    ...recovery,
    approvalWriter: runtime.approvalWriter,
    afterBoundary: runtime.afterPromotionBoundary,
    authorityMutablePaths: [
      path.join(graph.producerDir, ".render-graph-v1", "ACTIVE.json"),
      ...(crashInput(graph, runtime).productionQc
        ? [] : preparation.mutablePaths),
    ],
  };
}

function preparePromotionContext(
  candidate: string,
  producerDir: string,
  record: ApprovalRecord,
  runtime: RenderGraphPromotionRuntime,
): GraphPromotionContext | null {
  const command = runtime.command ?? runCandidateCommand;
  const earlyGraph: GraphPromotion = {
    candidate, producerDir, expectedSha256: record.finalHash,
    expectedGraphHash: "", command,
  };
  const earlyInput = crashInput(earlyGraph, runtime);
  if (earlyInput.productionQc
      && recoverRenderGraphPromotionSync(earlyInput, record)
        === "recovered-new") return null;
  const observeStaged = runtime.stagedObserver
    ?? observeStagedRenderGraphAuthoritySync;
  const staged = observeStaged({
    producerDir,
    candidatePath: candidate,
    expectedCandidateHash: record.finalHash,
  });
  const verified = verifiedGraphHash(command(candidateArgs(
    "verify", candidate, producerDir, record.finalHash)));
  if (verified !== staged.graphHash) {
    throw new Error("candidate verifier disagrees with staged graph authority");
  }
  const prepareQc = runtime.qcPreparation
    ?? prepareProducerQcPromotionSync;
  return {
    graph: {
      ...earlyGraph,
      expectedGraphHash: staged.graphHash,
    },
    preparation: prepareQc(producerDir, {
      graphHash: staged.graphHash,
      approval: record,
    }),
    record,
    runtime,
  };
}

/**
 * Keep the prior ACTIVE graph selected through QC, then advance it only after
 * the exact approved candidate has been promoted into final.mp4.
 */
export function promoteApprovedCandidateWithRenderGraph(
  candidate: string,
  producerDir: string,
  record: ApprovalRecord,
  runtime: RenderGraphPromotionRuntime = {},
): void {
  const context = preparePromotionContext(
    candidate, producerDir, record, runtime);
  if (!context) return;
  try {
    promoteApprovedCandidate(
      candidate,
      producerDir,
      record,
      promotionHooks(context),
    );
  } finally {
    recoverProducerQcPromotionIntentSync(producerDir);
  }
}

export {
  activateExactRenderGraphCandidateSync,
  approvedRenderGraphReady,
  rollbackExactRenderGraphCandidateSync,
  verifyExactRenderGraphCandidateSync,
  type ExactRenderGraphActivationInput,
} from "./current-render-graph-exact-activation";
