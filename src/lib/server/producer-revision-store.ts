import { parseEditRequestV1 } from "@/lib/producer/contracts/edit-request";
import {
  materializeProducerCommitSync,
  type ProducerRevisionCommitInput,
} from "./producer-revision-materialize";
import {
  recoverProducerCommitSync,
  unresolvedProducerIntentsSync,
  type ProducerCommitHooks,
  type ProducerCommitOutcome,
} from "./producer-revision-recovery";

export class ProducerCommitInProgressError extends Error {
  constructor(readonly idempotencyKey: string) {
    super(`producer commit ${idempotencyKey} requires recovery before new work`);
    this.name = "ProducerCommitInProgressError";
  }
}

/**
 * Materialize a closed batch, reserve one immutable child for its expected
 * parent, advance the append-only lineage, and seal its committed receipt.
 */
export function commitProducerRevisionSync(
  input: ProducerRevisionCommitInput,
  hooks: ProducerCommitHooks = {},
): ProducerCommitOutcome {
  const request = parseEditRequestV1(input.request);
  const unresolved = unresolvedProducerIntentsSync(input.producerDir)
    .filter((intent) => intent.idempotencyKey !== request.idempotencyKey);
  if (unresolved.length) {
    throw new ProducerCommitInProgressError(unresolved[0].idempotencyKey);
  }
  const materialized = materializeProducerCommitSync(input);
  hooks.after?.("after-materialized");
  return recoverProducerCommitSync(
    input.producerDir,
    materialized.record.idempotencyKey,
    hooks,
  );
}

export type {
  ProducerRevisionCommitInput,
  ProducerCommitHooks,
  ProducerCommitOutcome,
};
