import { planRefitEvent } from "../../_lib/plan-refit-transaction";
import {
  finalizeSurgicalEdit,
  type FinalizeSurgicalEditInput,
} from "./finalize";

export async function completeGovernedEdit(
  input: FinalizeSurgicalEditInput,
  send: (value: Record<string, unknown>) => void,
): Promise<void> {
  send({
    event: "surgical_review_started",
    lanes: input.scope.lanes,
    message: "Writer finished; running stored-intent, transcript/cut, hook, claims, lane lint, and fresh craft review.",
  });
  const result = await finalizeSurgicalEdit(input);
  if (result.refit) send(planRefitEvent(result.refit));
  if (result.typedCompatibility) {
    send({
      event: "typed_compatibility_operation",
      kind: result.typedCompatibility.kind,
      operation: result.typedCompatibility.operation.operation,
      operationHash: result.typedCompatibility.operationHash,
    });
  }
  if (result.revisionShadow) {
    send({
      event: "producer_revision_shadow",
      status: result.revisionShadow.status,
      ...("reason" in result.revisionShadow
        ? { reason: result.revisionShadow.reason }
        : {
            childRevisionHash: result.revisionShadow.childRevisionHash,
            receiptHash: result.revisionShadow.receiptHash,
          }),
    });
  }
  send({
    event: "surgical_review",
    ok: true,
    lanes: input.scope.lanes,
    changedFields: result.changedFields,
    typedCompatibility: result.typedCompatibility?.kind,
    summary: result.review.summary,
  });
}
