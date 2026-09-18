import { readFileSync } from "fs";
import { isDeepStrictEqual } from "node:util";
import {
  appendHistory,
  findProjectRoot,
  readProjectJson,
  setProjectIntentResolution,
} from "../../_lib/workspace";
import { reconcileIntentCapabilities } from "@/lib/producer/intent-capabilities";
import {
  validateIntent,
  type ProjectIntent,
} from "@/lib/producer/intent-presets";
import type { AssetManifest } from "@/lib/producer/types";

type ComparableIntent = Omit<ProjectIntent, "preset">;

function comparable(intent: ProjectIntent): ComparableIntent {
  const result = { ...intent };
  delete result.preset;
  return result;
}

function readManifest(manifestPath: string): AssetManifest {
  try {
    return JSON.parse(readFileSync(manifestPath, "utf8")) as AssetManifest;
  } catch (error) {
    throw new Error(`cannot verify edit assets: ${(error as Error).message}`);
  }
}

/** Assert that the launch payload is the same request persisted in project.json. */
export function assertIntentMatches(
  stored: ProjectIntent,
  requested: ProjectIntent,
): void {
  const expected = comparable(stored);
  const actual = comparable(requested);
  if (isDeepStrictEqual(actual, expected)) return;
  const fields = Object.keys({ ...expected, ...actual }).filter((field) =>
    !isDeepStrictEqual(
      expected[field as keyof ComparableIntent],
      actual[field as keyof ComparableIntent],
    ));
  throw new Error(`launch intent differs from stored operator intent: ${fields.sort().join(", ")}`);
}

/** Load the persisted authority and reject missing, corrupt, or drifted launches. */
export function storedAutoEditIntent(producerDir: string): ProjectIntent {
  const root = findProjectRoot(producerDir);
  if (!root) throw new Error("Auto Edit requires a workspace project with project.json");
  const project = readProjectJson(root);
  const raw = project?.resolvedIntent ?? project?.intent;
  if (!raw) throw new Error("project has no stored edit intent; set Short/Long and an edit level first");
  try {
    return validateIntent(raw);
  } catch (error) {
    throw new Error(`stored edit intent is invalid: ${(error as Error).message}`);
  }
}

/**
 * Reconcile unresolved legacy asset obligations before any model starts.
 *
 * Older projects stored only the requested intent, so a Produced edit with an
 * empty b-roll pool looked permanently invalid until the operator re-ingested
 * unchanged media. Persist the same requested/resolved/decision contract used
 * by fresh ingest and return the effective intent to this launch. Full/Mimic
 * also continue with an explicit fidelity warning rather than losing all work.
 */
export function reconcileStoredIntentCapabilities(
  producerDir: string,
  intent: ProjectIntent,
  manifestPath: string,
): ProjectIntent {
  const resolution = reconcileIntentCapabilities(intent, readManifest(manifestPath));
  if (resolution.decisions.length) {
    const root = findProjectRoot(producerDir);
    if (!root) throw new Error("cannot save the media capability decision: project.json was not found");
    setProjectIntentResolution(root, resolution);
    appendHistory(root, "intent-capability");
  }
  if (!resolution.ok || !resolution.resolvedIntent) throw new Error(resolution.error);
  return resolution.resolvedIntent;
}

/** Load stored authority and require a launch payload to match it exactly. */
export function authoritativeAutoEditIntent(
  producerDir: string,
  body: Record<string, unknown>,
  manifestPath?: string,
): ProjectIntent {
  const stored = storedAutoEditIntent(producerDir);
  let requested: ProjectIntent;
  try {
    requested = validateIntent(body);
  } catch (error) {
    throw new Error(`launch edit intent is invalid: ${(error as Error).message}`);
  }
  try {
    assertIntentMatches(stored, requested);
  } catch (originalMismatch) {
    const effective = manifestPath
      ? reconcileIntentCapabilities(stored, readManifest(manifestPath)).resolvedIntent
      : undefined;
    if (!effective) throw originalMismatch;
    try { assertIntentMatches(effective, requested); } catch { throw originalMismatch; }
  }
  return stored;
}
