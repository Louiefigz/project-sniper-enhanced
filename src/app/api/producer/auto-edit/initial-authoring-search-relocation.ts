import { createHash } from "node:crypto";
import { existsSync, realpathSync } from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { pythonInterpreter, runtimeScriptsDir } from "../../_lib/spawn-python";
import { atomicCreateFileSync } from "@/lib/server/atomic-file";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { executablePipelineRoot } from "@/lib/server/auto-edit-pipeline-authority";
import { readBoundedAuthoringFile } from "./initial-authoring-capture";
import type { CapturedInitialAuthoring } from "./initial-authoring-staging";
import {
  visualPlanCatalogAuthorityPath, visualPlanContextPath,
  type VisualPlanContext,
} from "./visual-plan-context";

const MAX_QUERY_BYTES = 1024 * 1024;
const MAX_RESULT_BYTES = 32 * 1024 * 1024;
const SHA256 = /^[a-f0-9]{64}$/;

interface SearchPin {
  schemaVersion: 1;
  path: string;
  sha256: string;
  digest: string;
}

export interface CapturedVisualSearch {
  pin: SearchPin;
  query: Buffer;
  result: Buffer;
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, keys: string[], label: string): void {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${label} fields are invalid`);
  }
}

function hash(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function stagedPath(file: unknown, root: string, label: string): string {
  if (typeof file !== "string" || !path.isAbsolute(file)) {
    throw new Error(`${label} path is invalid`);
  }
  const resolved = realpathSync(file), prefix = `${realpathSync(root)}${path.sep}`;
  if (!resolved.startsWith(prefix)) {
    throw new Error(`${label} must remain inside disposable authoring: ${resolved}`);
  }
  return resolved;
}

/** Capture exact staged authority and query bytes before provider paths can change. */
export function captureVisualSearchAuthority(
  root: string, visualPlanBytes: Buffer,
): CapturedVisualSearch {
  const visual = object(JSON.parse(visualPlanBytes.toString("utf8")),
    "captured visual plan");
  const pin = object(visual.searchAuthority, "staged searchAuthority");
  exactKeys(pin, ["schemaVersion", "path", "sha256", "digest"], "staged searchAuthority");
  if (pin.schemaVersion !== 1 || !SHA256.test(String(pin.sha256))
      || !SHA256.test(String(pin.digest))) {
    throw new Error("staged searchAuthority identity is invalid");
  }
  const resultPath = stagedPath(pin.path, root, "staged search authority");
  const resultBytes = readBoundedAuthoringFile(
    resultPath, "staged search authority", MAX_RESULT_BYTES);
  if (hash(resultBytes) !== pin.sha256) {
    throw new Error("staged searchAuthority SHA-256 differs from exact result bytes");
  }
  const result = object(JSON.parse(resultBytes.toString("utf8")), "staged search result");
  const core = Object.fromEntries(Object.entries(result)
    .filter(([key]) => key !== "digest"));
  if (result.digest !== pin.digest || canonicalJsonSha256(core) !== pin.digest) {
    throw new Error("staged searchAuthority digest differs from exact result content");
  }
  const queryPin = object(result.query, "staged search query pin");
  exactKeys(queryPin, ["path", "sha256", "count"], "staged search query pin");
  const queryPath = stagedPath(queryPin.path, root, "staged search query");
  const query = readBoundedAuthoringFile(queryPath, "staged search query", MAX_QUERY_BYTES);
  if (hash(query) !== queryPin.sha256) {
    throw new Error("staged semantic query SHA-256 differs from exact bytes");
  }
  return { query, result: resultBytes, pin: pin as unknown as SearchPin };
}

function createExact(destination: string, bytes: Buffer): void {
  if (!existsSync(destination)) {
    atomicCreateFileSync(destination, bytes);
    return;
  }
  const current = readBoundedAuthoringFile(
    destination, "durable semantic query", MAX_QUERY_BYTES);
  if (!current.equals(bytes)) {
    throw new Error("durable semantic query identity collides with different bytes");
  }
}

function pipelineRoot(captured: CapturedInitialAuthoring): string | undefined {
  const ctx = captured.staging.original;
  const authority = ctx.visualPlanPipeline ?? ctx.pipeline;
  return authority ? executablePipelineRoot(ctx.dir, authority) : undefined;
}

/** Freeze exact staged query bytes and regenerate trusted durable search evidence. */
export function relocateVisualSearchAuthority(
  captured: CapturedInitialAuthoring,
  context: VisualPlanContext,
  visual: Record<string, unknown>,
): SearchPin {
  const staged = captured.visualSearch;
  if (!staged) throw new Error("captured visual search authority is missing");
  const visualPin = object(visual.searchAuthority, "captured visual searchAuthority");
  if (canonicalJsonSha256(visualPin) !== canonicalJsonSha256(staged.pin)) {
    throw new Error("captured visual plan searchAuthority differs from captured search bytes");
  }
  const producer = path.resolve(captured.staging.original.dir);
  const querySha = hash(staged.query);
  const identity = createHash("sha256").update(
    `${querySha}:${String(context.catalogPin.indexSha256)}`,
  ).digest("hex");
  const queryPath = path.join(producer, `VISUAL-SEARCH.${querySha}.json`);
  const resultPath = path.join(producer, `VISUAL-SEARCH-RESULTS.${identity}.json`);
  createExact(queryPath, staged.query);
  const script = path.join(
    runtimeScriptsDir(), "producer/planner/ordinary_visual_plan_search.py");
  const root = pipelineRoot(captured);
  const stdout = execFileSync(pythonInterpreter(), ["-B", script,
    visualPlanCatalogAuthorityPath(captured.staging.original),
    visualPlanContextPath(captured.staging.original), queryPath, resultPath], {
    encoding: "utf8", timeout: 30_000, maxBuffer: 1024 * 1024,
    env: { NODE_ENV: "production", PYTHONDONTWRITEBYTECODE: "1", PYTHONUTF8: "1",
      ...(root ? { SNIPER_PIPELINE_ROOT: root } : {}) },
  });
  const receipt = object(JSON.parse(stdout), "durable search receipt");
  const authority = object(receipt.authority, "durable search authority");
  exactKeys(authority, ["schemaVersion", "path", "sha256", "digest"],
    "durable search authority");
  const result = readBoundedAuthoringFile(
    resultPath, "durable search authority", MAX_RESULT_BYTES);
  if (authority.path !== resultPath || authority.sha256 !== hash(result)
      || authority.schemaVersion !== 1 || !SHA256.test(String(authority.digest))) {
    throw new Error("durable search receipt differs from exact result bytes");
  }
  return authority as unknown as SearchPin;
}

/** Rebind opportunity reviews only when they name the exact staged digest. */
export function relocateSearchReviews(
  visual: Record<string, unknown>, stagedDigest: string, durableDigest: string,
): void {
  if (!Array.isArray(visual.opportunities)) {
    throw new Error("staged visual plan opportunities are invalid");
  }
  for (const raw of visual.opportunities) {
    const opportunity = object(raw, "staged visual opportunity");
    const review = object(opportunity.searchReview, "staged searchReview");
    if (review.searchDigest !== stagedDigest) {
      throw new Error("staged searchReview differs from staged searchAuthority");
    }
    review.searchDigest = durableDigest;
  }
}
