import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { parseEditBatchV1 } from "@/lib/producer/contracts/edit-batch";
import { parseCutRestoreSpeechV1 } from "@/lib/producer/contracts/cut-restore-speech-v1";
import { invalidateRenderGraphV1 } from
  "@/lib/producer/contracts/render-graph";
import {
  cutRestoreAction,
  fixtureSha,
} from "@/lib/producer/__tests__/_cut-restore-speech-fixture";
import { commitProducerRevisionSync } from "../producer-revision-store";
import { producerAuthorityPaths } from "../producer-authority-files";
import {
  bootstrapRevisionFixture,
  cleanRevisionFixture,
  revisionCommitInput,
} from "./_producer-revision-fixture";
import { cutRepairProofFixture } from
  "./_p2-cut-repair-promotion-fixture";

const fixture = bootstrapRevisionFixture();
try {
  const treatment = revisionCommitInput(
    fixture.producer,
    fixture.genesis,
    "c",
  );
  const childTimeline = fixtureSha("7");
  const action = parseCutRestoreSpeechV1(cutRestoreAction(
    treatment.batch.base.pictureLockHash,
    treatment.batch.base.timelineMapHash,
  ));
  const operationId = treatment.batch.operations[0].operationId;
  const inputKey = `cut.restoreSpeech.${operationId}`;
  const boundGraph = {
    ...treatment.renderGraph,
    nodes: treatment.renderGraph.nodes.map((node) => node.nodeId === "node-scene"
      ? {
          ...node,
          kind: "dialogue-stem" as const,
          inputDigests: {
            ...node.inputDigests,
            [inputKey]: fixtureSha("0"),
          },
        } : node),
  };
  const invalidated = invalidateRenderGraphV1(boundGraph, {
    [inputKey]: canonicalJsonSha256(action),
  });
  const promotion = cutRepairProofFixture(
    fixture.producer, action, childTimeline);
  const invariantProof = promotion.hashes.invariant;
  const input = {
    ...treatment,
    batch: {
      ...treatment.batch,
      stage: "cut" as const,
      operations: [{
        ...treatment.batch.operations[0],
        action,
      }],
    },
    revision: {
      ...treatment.revision,
      timelineMapHash: childTimeline,
      pictureLockHash: promotion.hashes.pictureLock,
      workflowState: "PICTURE_LOCKED" as const,
      authoritativeSidecars: {
        pictureLock: promotion.hashes.pictureLock,
        pictureLockSupersession: promotion.hashes.supersession,
        cutRepairFragmentReceipt: promotion.hashes.fragment,
        cutRepairCompositeReceipt: promotion.hashes.composite,
        cutRepairInvariantProof: invariantProof,
        cutRepairCandidate: promotion.hashes.candidate,
        captionRepairRevalidation: promotion.hashes.caption,
        palmierCutRepairDisposition: promotion.hashes.palmier,
        cutRepairPromotionEvidence: promotion.hashes.promotion,
      },
    },
    renderGraph: invalidated.graph,
    invalidationReceipt: invalidated.receipt,
    invariantProofHash: invariantProof,
    cutRepairProof: promotion.proof,
    projectionReceipt: treatment.projectionReceipt
      ? { ...treatment.projectionReceipt, timelineMapHash: childTimeline }
      : null,
  };
  assert.throws(
    () => commitProducerRevisionSync({
      ...input,
      cutRepairProof: undefined,
    }),
    /Python-owned proof envelope/,
  );
  assert.throws(
    () => commitProducerRevisionSync({
      ...input,
      cutRepairProof: {
        ...promotion.proof,
        promotionEvidence: {},
      },
    }),
    /promotion evidence/,
  );
  const evidence = promotion.proof.promotionEvidence as
    Record<string, unknown>;
  const alignment = evidence.alignment as Record<string, unknown>;
  const receipt = alignment.receipt as Record<string, unknown>;
  const falseReceipt = { ...receipt, sourceSpanBoundaryMatch: false };
  assert.throws(
    () => commitProducerRevisionSync({
      ...input,
      cutRepairProof: {
        ...promotion.proof,
        promotionEvidence: {
          ...evidence,
          alignment: {
            ...alignment,
            receipt: falseReceipt,
            receiptHash: canonicalJsonSha256(falseReceipt),
          },
        },
      },
    }),
    /transcript-bound source waveform/,
  );
  assert.throws(
    () => commitProducerRevisionSync({
      ...input,
      revision: {
        ...input.revision,
        workflowState: "CUT_REVIEW",
      },
    }),
    /child-lock supersession/,
  );
  assert.throws(
    () => parseEditBatchV1({
      ...input.batch,
      base: {
        ...input.batch.base,
        timelineMapHash: childTimeline,
        pictureLockHash: promotion.hashes.pictureLock,
      },
    }),
    /does not bind the batch parent lock and timeline/,
  );
  const result = commitProducerRevisionSync(input);
  assert.equal(result.status, "committed");
  const paths = producerAuthorityPaths(fixture.producer);
  assert.ok(fs.existsSync(path.join(
    paths.objects.media, `${promotion.hashes.fragmentMedia}.mov`)));
  assert.ok(fs.existsSync(path.join(
    paths.objects.media, `${promotion.hashes.compositeMedia}.mov`)));

  const staleLock = {
    ...input,
    revision: {
      ...input.revision,
      pictureLockHash: treatment.batch.base.pictureLockHash,
    },
    request: {
      ...input.request,
      idempotencyKey: "2c000000-0000-4000-8000-000000000002",
    },
    batch: {
      ...input.batch,
      idempotencyKey: "2c000000-0000-4000-8000-000000000002",
    },
  };
  assert.throws(
    () => commitProducerRevisionSync(staleLock),
    /child-lock supersession/,
  );
  fs.writeFileSync(path.join(
    paths.objects.media, `${promotion.hashes.fragmentMedia}.mov`), "tampered");
  assert.throws(
    () => commitProducerRevisionSync(input),
    /conflicts with its hash path/,
  );
} finally {
  cleanRevisionFixture(fixture.root);
}

console.log("p2-cut-repair-revision tests passed");
