/**
 * Ordinary render admission: current independent reviews, bounded decoded
 * previews and the existing deterministic gate bundle. No provider calls.
 * --draft runs the same gates for watermarked drafts and bounded context preparation;
 * it never writes the readiness receipt required by a final render.
 * Usage: ./sniper node --import tsx scripts/infra/mint-delivery-approval.ts <producerDir> [--draft]
 */
import path from "node:path";
import { existsSync } from "node:fs";
import { prepareSavedPlanReview } from "@/app/api/producer/auto-edit/saved-plan-request";
import { runSurgicalGovernance } from "@/app/api/producer/ai-edit/surgical-governance";
import {
  templateUsageApprovalRequired,
  writeTemplateUsageApproval,
} from "@/lib/server/template-usage-approval";
import { atomicWriteFileSync } from "@/lib/server/atomic-file";
import { SURGICAL_EDIT_LANES, type SurgicalEditScope } from "@/lib/producer/surgical-edit";
import { assertPlanReviews, writeRenderReadiness, DRAFT_READY, RENDER_READY } from "@/lib/server/plan-readiness";
import { readinessPacket } from "@/lib/server/plan-readiness-packet";

async function main(): Promise<void> {
  const arg = process.argv[2];
  if (!arg) throw new Error("usage: node --import tsx scripts/infra/mint-delivery-approval.ts <producerDir> [--draft]");
  const dir = path.resolve(arg);
  const draft = process.argv[3] === "--draft";
  if (process.argv.length > (draft ? 4 : 3)) throw new Error("Expected <producerDir> and optional --draft");
  const planPath = path.join(dir, "edit_plan.json");
  if (!existsSync(planPath)) throw new Error(`no edit_plan.json in ${dir}`);

  // Resolves the stored operator intent + media authority the plan was authored
  // against (fails if project.json is missing/partial — the same binding render needs).
  const { ctx } = prepareSavedPlanReview(dir);

  const before = readinessPacket(ctx);
  if (!draft) assertPlanReviews(dir, before);

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
  if (readinessPacket(ctx).digest !== before.digest) throw new Error("Inputs changed while deterministic gates ran; rerun on the current plan");

  if (governance.cutApproval) {
    atomicWriteFileSync(governance.cutApproval.path, governance.cutApproval.text);
  }
  if (templateUsageApprovalRequired(dir)) writeTemplateUsageApproval({
    producerDir: dir,
    planPath,
    manifestPath: ctx.manifestPath,
    transcriptsDir: ctx.transcriptsDir,
    templateUsage: governance.templateUsage,
    verdict: governance.verdict.gates.templateUsage,
    operatorIntentVerdict: governance.verdict.gates.operatorIntent,
  });
  writeRenderReadiness(ctx, { draft, gates: governance.verdict });

  console.log(`✓ render readiness minted: ${path.join(dir, draft ? DRAFT_READY : RENDER_READY)}`);
  console.log(draft ? "  deterministic gates passed; watermarked drafts and bounded context previews are admitted; no final delivery."
    : "  deterministic gates, current independent reviews and preview evidence passed for this plan.");
  if (governance.warnings.length) {
    console.log(`  advisory warnings: ${governance.warnings.join(" | ")}`);
  }
}

main().catch((error: unknown) => {
  console.error(`✗ mint refused: ${error instanceof Error ? error.message : String(error)}`);
  console.error("  current reviews, previews, deterministic gates and unchanged inputs are required; final render remains blocked.");
  process.exit(1);
});
