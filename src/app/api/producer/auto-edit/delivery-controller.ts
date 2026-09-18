import {
  resolvedAutoEditDeliveryPolicy,
  type AutoEditDeliveryPolicy,
} from "@/lib/producer/auto-edit-delivery-policy";
import { publishAutoEditDeliveryReceiptSync } from
  "@/lib/server/auto-edit-delivery-receipt";
import type { PipelineDependencies } from "./pipeline-dependencies";
import type { PipelineRuntime } from "./pipeline-types";

export interface AutoEditDeliveryController {
  policy: AutoEditDeliveryPolicy;
  dependencies: PipelineDependencies;
  finish: () => void;
}

interface DeliveryState {
  run: PipelineRuntime;
  base: PipelineDependencies;
  policy: AutoEditDeliveryPolicy;
  palmierEnabled: boolean;
  forwardedPalmierCalls: number;
}

function suppressed(state: DeliveryState, boundary: string): void {
  state.run.io.send({
    event: "delivery_boundary_suppressed",
    deliveryPolicy: state.policy,
    boundary,
    requestKey: state.run.job.requestKey,
  });
}

function boundDependencies(state: DeliveryState): PipelineDependencies {
  return {
    ...state.base,
    palmierPrimary: async (runtime) => {
      if (!state.palmierEnabled) {
        suppressed(state, "native-primary-selection");
        return false;
      }
      state.forwardedPalmierCalls += 1;
      return state.base.palmierPrimary(runtime);
    },
    checkpoint: async (ctx, spec, send) => {
      if (!state.palmierEnabled) {
        suppressed(state, `${spec.stage}-checkpoint`);
        return { status: "deferred", reason: "MP4-only delivery" };
      }
      state.forwardedPalmierCalls += 1;
      return state.base.checkpoint(ctx, spec, send);
    },
    approvedMirror: async (ctx, send) => {
      if (!state.palmierEnabled) {
        suppressed(state, "approved-mirror");
        return;
      }
      state.forwardedPalmierCalls += 1;
      await state.base.approvedMirror(ctx, send);
    },
  };
}

function finishMp4Delivery(state: DeliveryState): void {
  if (state.palmierEnabled) return;
  if (state.forwardedPalmierCalls !== 0) {
    throw new Error(
      `MP4-only delivery forwarded ${state.forwardedPalmierCalls} Palmier adapter call(s)`,
    );
  }
  const stored = publishAutoEditDeliveryReceiptSync(state.run.job);
  state.run.io.send({
    event: "mp4_only_delivery_receipt",
    deliveryPolicy: state.policy,
    observedPalmierAdapterCalls: 0,
    observationScope: stored.receipt.observationScope,
    receiptHash: stored.hash,
    receiptPath: stored.path,
    requestKey: state.run.job.requestKey,
    runId: state.run.job.token,
    finalHash: state.run.job.finalHash,
  });
}

/** Bind every production Palmier adapter to one closed delivery authority. */
export function bindAutoEditDeliveryController(
  run: PipelineRuntime,
  base: PipelineDependencies,
): AutoEditDeliveryController {
  const policy = resolvedAutoEditDeliveryPolicy(run.job.ctx);
  const state: DeliveryState = {
    run, base, policy,
    palmierEnabled: policy === "palmier-hybrid",
    forwardedPalmierCalls: 0,
  };
  run.io.send({
    event: "delivery_policy_selected",
    deliveryPolicy: policy,
    palmierAllowed: state.palmierEnabled,
    requestKey: run.job.requestKey,
  });
  return {
    policy,
    dependencies: boundDependencies(state),
    finish: () => finishMp4Delivery(state),
  };
}
