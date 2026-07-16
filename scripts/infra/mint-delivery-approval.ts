/**
 * Harness delivery-approval seam — let a Claude Code / harness edit SHIP.
 *
 * render/assemble/palmier-push all fail closed unless a tamper-evident delivery
 * approval receipt (.sniper-template-usage-approved.json, LESSON-039) exists,
 * bound to the exact plan/manifest/transcript/intent/contract/history hashes.
 * That receipt is otherwise minted ONLY by the app's own review routes
 * (auto-edit planning-loop, ai-edit finalize) — there is no CLI seam, so a
 * harness run that authored + gated + critic-reviewed a plan itself still could
 * not ship.
 *
 * This is that seam, and it is NOT a bypass: it reuses the app's OWN
 * `runSurgicalGovernance` (which builds the template-usage authority, auto-mints
 * the cut-approval from the plan, and runs the full planning gate bundle —
 * operator_intent, transcript_cut, plan_lint, hook_contract, template_usage,
 * claims_contract) and refuses (throws) unless every gate passes; only then does
 * it call the app's OWN `writeTemplateUsageApproval`. The receipt is therefore
 * produced only when the deterministic gates actually pass, exactly as the app
 * requires — the same teeth, reachable from the harness.
 *
 * Usage:  node --import tsx scripts/infra/mint-delivery-approval.ts <producerDir>
 * where <producerDir> holds edit_plan.json and the project.json/source it was
 * authored against. Exit 0 + receipt on pass; exit 1 + the gate errors on any
 * failure.
 */
import path from "node:path";
import { existsSync } from "node:fs";
import { prepareSavedPlanReview } from "@/app/api/producer/auto-edit/saved-plan-request";
import { runSurgicalGovernance } from "@/app/api/producer/ai-edit/surgical-governance";
import {
  templateUsageApprovalPath,
  templateUsageApprovalRequired,
  writeTemplateUsageApproval,
} from "@/lib/server/template-usage-approval";
import { atomicWriteFileSync } from "@/lib/server/atomic-file";
import { SURGICAL_EDIT_LANES, type SurgicalEditScope } from "@/lib/producer/surgical-edit";

async function main(): Promise<void> {
  const arg = process.argv[2];
  if (!arg) throw new Error("usage: node --import tsx scripts/infra/mint-delivery-approval.ts <producerDir>");
  const dir = path.resolve(arg);
  const planPath = path.join(dir, "edit_plan.json");
  if (!existsSync(planPath)) throw new Error(`no edit_plan.json in ${dir}`);

  // Resolves the stored operator intent + media authority the plan was authored
  // against (fails if project.json is missing/partial — the same binding render needs).
  const { ctx } = prepareSavedPlanReview(dir);

  if (!templateUsageApprovalRequired(dir)) {
    console.log("No delivery approval is required for this intent (not produced/full with auto graphics). "
      + "render/assemble will proceed without a receipt.");
    return;
  }

  // Full-lane scope so the cut-approval candidate is minted (scope includes
  // "cuts") and transcript_cut runs in its approved stage — identical to the app.
  const scope: SurgicalEditScope = { lanes: [...SURGICAL_EDIT_LANES] };
  const governance = await runSurgicalGovernance({
    dir,
    planPath,
    manifestPath: ctx.manifestPath,
    transcriptsDir: ctx.transcriptsDir,
    scope,
  });
  // runSurgicalGovernance THROWS unless every gate passed — reaching here means green.

  if (governance.cutApproval) {
    atomicWriteFileSync(governance.cutApproval.path, governance.cutApproval.text);
  }
  writeTemplateUsageApproval({
    producerDir: dir,
    planPath,
    manifestPath: ctx.manifestPath,
    transcriptsDir: ctx.transcriptsDir,
    templateUsage: governance.templateUsage,
    verdict: governance.verdict.gates.templateUsage,
    operatorIntentVerdict: governance.verdict.gates.operatorIntent,
  });

  console.log(`✓ delivery approval minted: ${templateUsageApprovalPath(dir)}`);
  console.log("  every deterministic gate passed; render / assemble / palmier-push are unlocked for THIS exact plan.");
  if (governance.warnings.length) {
    console.log(`  advisory warnings: ${governance.warnings.join(" | ")}`);
  }
}

main().catch((error: unknown) => {
  console.error(`✗ mint refused: ${error instanceof Error ? error.message : String(error)}`);
  console.error("  the plan did not pass the deterministic gates (or its media/intent authority is missing) — nothing was minted.");
  process.exit(1);
});
