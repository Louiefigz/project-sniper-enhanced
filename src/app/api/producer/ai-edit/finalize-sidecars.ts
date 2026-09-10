import { atomicWriteFileSync } from "@/lib/server/atomic-file";
import {
  templateUsageApprovalPath,
  writeTemplateUsageApproval,
} from "@/lib/server/template-usage-approval";
import type { SurgicalGovernanceResult } from "./surgical-governance";
import { backupFile, type FileBackup } from "./finalize-file-backup";
import {
  commitPlanRefitReceipt,
  planRefitReceiptPath,
  type PlanRefitReceipt,
} from "../../_lib/plan-refit-receipt";

interface SidecarGovernance {
  cutApproval?: { path: string; text: string };
  verdict?: SurgicalGovernanceResult["verdict"];
  templateUsage?: SurgicalGovernanceResult["templateUsage"];
}

export interface FinalizeSidecarState {
  cutApprovalBackup: FileBackup | null;
  templateApprovalBackup: FileBackup | null;
  refitReceiptBackup: FileBackup | null;
}

interface FinalizeSidecarInput {
  producerDir: string;
  planPath: string;
  manifestPath: string;
  transcriptsDir: string;
  governance: SidecarGovernance;
  state: FinalizeSidecarState;
  templateApproval?: typeof writeTemplateUsageApproval;
  cutApprovalWriter?: typeof atomicWriteFileSync;
}

/** Promote reversible approval sidecars only after the plan child is current. */
export function promoteFinalizeSidecars(input: FinalizeSidecarInput): void {
  const { governance, state } = input;
  if (governance.cutApproval) {
    state.cutApprovalBackup = backupFile(governance.cutApproval.path);
    (input.cutApprovalWriter ?? atomicWriteFileSync)(
      governance.cutApproval.path,
      governance.cutApproval.text,
    );
  }
  if (!governance.verdict || !governance.templateUsage) return;
  state.templateApprovalBackup = backupFile(
    templateUsageApprovalPath(input.producerDir),
  );
  (input.templateApproval ?? writeTemplateUsageApproval)({
    producerDir: input.producerDir,
    planPath: input.planPath,
    manifestPath: input.manifestPath,
    transcriptsDir: input.transcriptsDir,
    templateUsage: governance.templateUsage,
    verdict: governance.verdict.gates.templateUsage,
    operatorIntentVerdict: governance.verdict.gates.operatorIntent,
  });
}

interface FinalizeRefitInput {
  dir: string;
  authorityPath: string;
  receipt: PlanRefitReceipt | null;
  state: FinalizeSidecarState;
  commit?: typeof commitPlanRefitReceipt;
}

/** Preserve the prior committed receipt before publishing child lineage. */
export function commitFinalizeRefit(
  input: FinalizeRefitInput,
): PlanRefitReceipt | null {
  if (!input.receipt) return null;
  input.state.refitReceiptBackup = backupFile(planRefitReceiptPath(input.dir));
  return (input.commit ?? commitPlanRefitReceipt)(
    input.dir,
    input.receipt,
    input.authorityPath,
  );
}
