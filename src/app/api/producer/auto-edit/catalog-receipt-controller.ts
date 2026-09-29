import { execFileSync } from "node:child_process";
import { mkdirSync, renameSync, rmSync } from "node:fs";
import path from "node:path";
import { pythonInterpreter, runtimeScriptsDir } from "../../_lib/spawn-python";
import { executablePipelineRoot } from "@/lib/server/auto-edit-pipeline-authority";
import type { CatalogReceiptAuthorityPin } from "@/lib/server/visual-plan-binding";
import type { AutoEditCtx } from "./stream";

const AUTHORITY_DIR = ".sniper-visual-catalog-authority";

function pipeline(ctx: AutoEditCtx): NonNullable<AutoEditCtx["pipeline"]> {
  const authority = ctx.visualPlanPipeline ?? ctx.pipeline;
  if (!authority) throw new Error("catalog receipt issuance requires pipeline authority");
  return authority;
}

/** Run the installed issuer only after the author process has been fenced. */
export function issueCatalogReceipts(
  ctx: AutoEditCtx,
  visualPlanPath: string,
): CatalogReceiptAuthorityPin {
  const authority = pipeline(ctx);
  const parent = path.join(ctx.dir, AUTHORITY_DIR);
  mkdirSync(parent, { recursive: true, mode: 0o700 });
  const output = `${visualPlanPath}.catalog-receipts.tmp`;
  const script = path.join(
    runtimeScriptsDir(), "producer/planner/catalog_receipt_issuer_cli.py",
  );
  try {
    const raw = execFileSync(pythonInterpreter(), ["-B", script, visualPlanPath,
      output, parent], {
      encoding: "utf8", timeout: 120_000, maxBuffer: 2 * 1024 * 1024,
      env: { NODE_ENV: "production", PYTHONDONTWRITEBYTECODE: "1", PYTHONUTF8: "1",
        SNIPER_PIPELINE_ROOT: executablePipelineRoot(ctx.dir, authority) },
    });
    const value = JSON.parse(raw) as {
      plan?: unknown; authority?: CatalogReceiptAuthorityPin;
    };
    if (value.plan !== output || !value.authority) {
      throw new Error("catalog receipt issuer returned malformed authority");
    }
    renameSync(output, visualPlanPath);
    return value.authority;
  } finally {
    rmSync(output, { force: true });
  }
}
