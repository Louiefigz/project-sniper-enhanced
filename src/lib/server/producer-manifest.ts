import fs from "node:fs";
import path from "node:path";

export interface ProducerManifestLookup {
  path: string | null;
  transcriptsDir: string | null;
  candidates: string[];
  error: string | null;
}

function hasSources(filePath: string): boolean {
  try {
    const value = JSON.parse(fs.readFileSync(filePath, "utf8")) as { sources?: unknown };
    return Array.isArray(value.sources);
  } catch {
    return false;
  }
}

function recordedManifest(producerDir: string): { path: string | null; error: string | null } {
  const fingerprint = path.join(producerDir, "base.fingerprint.json");
  if (!fs.existsSync(fingerprint)) return { path: null, error: null };
  try {
    const value = JSON.parse(fs.readFileSync(fingerprint, "utf8")) as {
      manifestPath?: unknown;
    };
    return {
      path: typeof value.manifestPath === "string" && value.manifestPath
        ? value.manifestPath
        : null,
      error: null,
    };
  } catch (error) {
    return {
      path: null,
      error: `${fingerprint} is not valid JSON: ${(error as Error).message}`,
    };
  }
}

function discoveredManifests(producerDir: string): string[] {
  const sourceDir = path.resolve(producerDir, "..", "source");
  const candidates: string[] = [];
  if (fs.existsSync(sourceDir)) {
    for (const name of fs.readdirSync(sourceDir).sort()) {
      if (!name.endsWith(".json") || name.endsWith(".transcript.json")) continue;
      const candidate = path.join(sourceDir, name);
      if (hasSources(candidate)) candidates.push(candidate);
    }
  }
  const legacy = path.join(producerDir, "asset_manifest.json");
  if (fs.existsSync(legacy) && hasSources(legacy)) candidates.push(legacy);
  return [...new Set(candidates.map((candidate) => path.resolve(candidate)))];
}

/** One fail-closed manifest authority for Auto Edit, status, and Palmier. */
export function lookupProducerManifest(producerDir: string): ProducerManifestLookup {
  const dir = path.resolve(producerDir);
  const recorded = recordedManifest(dir);
  if (recorded.error) {
    return { path: null, transcriptsDir: null, candidates: [], error: recorded.error };
  }
  if (recorded.path) {
    const resolved = path.resolve(recorded.path);
    if (!fs.existsSync(resolved)) {
      return {
        path: null,
        transcriptsDir: null,
        candidates: [],
        error: `base.fingerprint.json records ${resolved}, but that manifest is gone`,
      };
    }
    if (!hasSources(resolved)) {
      return {
        path: null,
        transcriptsDir: null,
        candidates: [resolved],
        error: `base.fingerprint.json records ${resolved}, but it is not an asset manifest`,
      };
    }
    return {
      path: resolved,
      transcriptsDir: path.dirname(resolved),
      candidates: [resolved],
      error: null,
    };
  }

  const candidates = discoveredManifests(dir);
  if (candidates.length === 1) {
    return {
      path: candidates[0],
      transcriptsDir: path.dirname(candidates[0]),
      candidates,
      error: null,
    };
  }
  const sourceDir = path.resolve(dir, "..", "source");
  const error = candidates.length
    ? `ambiguous asset manifests: ${candidates.join(", ")}`
    : `no asset manifest found in ${sourceDir} or ${dir}`;
  return { path: null, transcriptsDir: null, candidates, error };
}
