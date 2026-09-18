import { assertNoPromotionReconciliation } from
  "./ask-editor-reconciliation";
import { recoverProducerQcPromotionIntentSync } from
  "./producer-qc-promotion-intent";

/** Resolve a complete durable QC boundary before permitting another writer. */
export function assertAutoEditPromotionReadySync(producerDir: string): void {
  recoverProducerQcPromotionIntentSync(producerDir);
  assertNoPromotionReconciliation(producerDir);
}
