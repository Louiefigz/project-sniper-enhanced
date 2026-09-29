/** Materialize the trusted visual-planning context for the current local project. */
import { existsSync, lstatSync, realpathSync } from "node:fs";
import path from "node:path";
import { storedAutoEditIntent } from
  "../../src/app/api/producer/auto-edit/operator-intent-authority";
import { parseAutoEditIntent } from
  "../../src/app/api/producer/auto-edit/stream";
import { materializeVisualPlanContextAuthority, type VisualPlanContext } from
  "../../src/app/api/producer/auto-edit/visual-plan-context";
import { lookupProducerManifest } from
  "../../src/lib/server/producer-manifest";

const USAGE = "Usage: visual-plan-context.ts <absolute-producer-directory>";

function canonicalDirectory(raw: string): string {
  const requested = path.resolve(raw);
  if (!path.isAbsolute(raw) || !existsSync(requested)
      || lstatSync(requested).isSymbolicLink()
      || !lstatSync(requested).isDirectory()
      || realpathSync(requested) !== requested) {
    throw new Error("visual-plan context needs one canonical producer directory");
  }
  return requested;
}

/** Freeze the accepted program, full transcript, catalog and prior-use ledger. */
export function materializeVisualPlanContext(rawProducerDir: string): VisualPlanContext {
  const producerDir = canonicalDirectory(rawProducerDir);
  const stored = storedAutoEditIntent(producerDir);
  const intent = parseAutoEditIntent(stored as unknown as Record<string, unknown>);
  if (!["produced", "full"].includes(stored.scope)) {
    throw new Error("visual-plan context is only required for produced or full edits");
  }
  const manifest = lookupProducerManifest(producerDir);
  if (!manifest.path || !manifest.transcriptsDir) {
    throw new Error(manifest.error ?? "visual-plan context cannot resolve the asset manifest");
  }
  const planPath = path.join(producerDir, "edit_plan.json");
  if (!existsSync(planPath) || lstatSync(planPath).isSymbolicLink()
      || !lstatSync(planPath).isFile()) {
    throw new Error("visual-plan context requires the accepted cut at edit_plan.json");
  }
  const value = materializeVisualPlanContextAuthority({
    dir: producerDir,
    scope: stored.scope,
    intent,
    visualPlanRequiredVersion: 1,
    planPath,
    manifestPath: manifest.path,
    transcriptsDir: manifest.transcriptsDir,
  });
  return value;
}

export function executeVisualPlanContext(argv: string[]): VisualPlanContext {
  if (argv.length !== 1) throw new Error(USAGE);
  return materializeVisualPlanContext(argv[0]);
}

if (require.main === module) {
  try {
    console.log(JSON.stringify(executeVisualPlanContext(process.argv.slice(2))));
  } catch (error) {
    console.error(JSON.stringify({ ok: false, error: String(error).slice(0, 2048) }));
    process.exitCode = 1;
  }
}
