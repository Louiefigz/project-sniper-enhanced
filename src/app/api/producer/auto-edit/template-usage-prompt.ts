import type { AutoEditCtx } from "./stream";
import { templateUsageHistoryPath } from "@/lib/server/template-usage-history";

type CommandBuilder = (ctx: AutoEditCtx, script: string, args: string[]) => string;

export interface TemplateUsagePromptAuthority {
  command: string;
  readLine: string;
  selectionStep: string;
}

/** Bind visual form selection to immutable, approved same-mode project history. */
export function templateUsagePromptAuthority(
  ctx: AutoEditCtx,
  command: CommandBuilder,
): TemplateUsagePromptAuthority {
  if (!ctx.templateUsage) throw new Error("template usage authority was not captured before authoring");
  const history = templateUsageHistoryPath(ctx);
  return {
    command: command(ctx, "template_usage_contract.py", [
      ctx.planPath, ctx.transcriptsDir, ctx.manifestPath, history,
      "--expected-digest", ctx.templateUsage.digest,
    ]),
    readLine: `READ ${history} before choosing graphic forms. It is the immutable, digest-bound recent usage window from verified QC-approved same-mode projects; counts and overusedKinds are evidence, never an instruction to violate transcript fit.`,
    selectionStep: `3d. CROSS-PROJECT FORM MEMORY — compatibleKinds is unordered. Prefer a compatible underused form when the same kind appears in overusedKinds. Reuse an overused kind only when it is still the best transcript-specific anatomy: persist the underused alternatives in alternativesConsidered and a 30+ character reuseReason quoting this beat's transcript evidence. Never force novelty when no compatible underused alternative exists.`,
  };
}
