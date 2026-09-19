/**
 * Stored edit intent from the command line — project.json's "what did the operator ask for".
 *
 * Render, the delivery-approval mint and native Short/long-form preparation read the project's
 * stored, capability-resolved intent from project.json and fail closed without it. The app wrote
 * it (POST /api/producer/intent, and at ingest). Buyers drive Sniper only from their own Codex or
 * Claude Code, so this is the same write from the command line. It is NOT a bypass: it reuses the
 * app's OWN validateIntent + reconcileIntentCapabilities + recordProjectIntentResolution under the
 * same project mutation guard, so an unknown lane, a lane the media cannot support, or a busy
 * project is refused exactly as the app refused it.
 *
 * Usage (from the Sniper folder):
 *   ./sniper node --import tsx scripts/infra/project-intent.ts <projectRoot> --intent '<json>'
 *   ./sniper node --import tsx scripts/infra/project-intent.ts <projectRoot> --intent-file <file>
 *   ./sniper node --import tsx scripts/infra/project-intent.ts <projectRoot>      # print it
 * <projectRoot> is the project folder whose source/asset_manifest.json ingest.py wrote (its
 * producer/ folder is accepted too). A project without project.json gets one here, as the app's
 * own ingest created it. Prints JSON; exit 0 when saved (or printed), 1 when refused.
 */
import path from "node:path";
import { existsSync, readFileSync } from "node:fs";
import {
  findProjectRoot,
  readProjectJson,
  recordProjectIntentResolution,
  writeProjectJson,
} from "@/app/api/_lib/workspace";
import { guardProjectMutation } from "@/app/api/_lib/project-mutation";
import { reconcileIntentCapabilities } from "@/lib/producer/intent-capabilities";
import { validateIntent } from "@/lib/producer/intent-presets";
import type { AssetManifest } from "@/lib/producer/types";

const USAGE = "usage: node --import tsx scripts/infra/project-intent.ts <projectRoot> "
  + "[--intent '<json>' | --intent-file <file>]";

function parseArgs(argv: string[]): { dir: string; intent: unknown | undefined } {
  const [dir, flag, value] = argv;
  if (!dir || !path.isAbsolute(dir)) throw new Error(`${USAGE}\n  (<projectRoot> must be an absolute path)`);
  if (flag === undefined) return { dir, intent: undefined };
  if (value === undefined || argv.length > 3) throw new Error(USAGE);
  if (flag === "--intent") return { dir, intent: JSON.parse(value) };
  if (flag === "--intent-file") return { dir, intent: JSON.parse(readFileSync(value, "utf8")) };
  throw new Error(USAGE);
}

/** The project root, creating project.json for an ingested project that has none yet. */
function projectRoot(dir: string): string {
  const clean = path.resolve(dir).replace(/\/$/, "");
  const found = findProjectRoot(clean);
  if (found && existsSync(path.join(found, "project.json"))) return found;
  const root = found ?? clean;
  if (!existsSync(path.join(root, "source", "asset_manifest.json"))) {
    throw new Error(`${root} is not an ingested project: run scripts/producer/ingest.py <footage> `
      + `--out ${path.join(root, "source", "asset_manifest.json")} first.`);
  }
  writeProjectJson(root, { origin: "raw", history: [] });
  return root;
}

function readManifest(root: string): AssetManifest {
  return JSON.parse(readFileSync(path.join(root, "source", "asset_manifest.json"), "utf8")) as AssetManifest;
}

async function main(): Promise<number> {
  const { dir, intent } = parseArgs(process.argv.slice(2));
  const root = projectRoot(dir);
  if (intent === undefined) {
    const project = readProjectJson(root);
    console.log(JSON.stringify({
      projectRoot: root,
      intent: project?.resolvedIntent ?? project?.intent ?? null,
      requestedIntent: project?.requestedIntent ?? project?.intent ?? null,
      intentDecisions: project?.intentDecisions ?? [],
    }, null, 2));
    return 0;
  }
  const guarded = guardProjectMutation({
    projectRoot: root,
    producerDir: path.join(root, "producer"),
    operation: "saving this edit request",
  });
  if (guarded.response) {
    const body = (await guarded.response.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error || "the project refused this update");
  }
  try {
    const resolution = reconcileIntentCapabilities(validateIntent(intent), readManifest(root));
    recordProjectIntentResolution(root, resolution, "intent");
    console.log(JSON.stringify({
      ok: resolution.ok,
      ...(resolution.ok ? {} : { error: resolution.error }),
      projectRoot: root,
      requestedIntent: resolution.requestedIntent,
      intent: resolution.resolvedIntent ?? null,
      intentDecisions: resolution.decisions,
    }, null, 2));
    return resolution.ok ? 0 : 1;
  } finally {
    guarded.lease.release();
  }
}

main().then((code) => process.exit(code)).catch((error: unknown) => {
  console.error(`✗ edit request not saved: ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
});
