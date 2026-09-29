import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { closeSync, constants, existsSync, fstatSync, lstatSync, openSync,
  readFileSync, realpathSync, statSync } from "node:fs";
import path from "node:path";
import { pythonInterpreter, runtimeScriptsDir } from "@/app/api/_lib/spawn-python";
import type { AutoEditPipelineAuthority } from
  "@/app/api/producer/auto-edit/stream";
import { fileSha256 } from "./auto-edit-hash";
import { executablePipelineRoot } from "./auto-edit-pipeline-authority";

const MAX_VISUAL_PLAN_BYTES = 4 * 1024 * 1024;
const SHA256 = /^[a-f0-9]{64}$/;

export interface VisualPlanBinding {
  schemaVersion: 1;
  path: string;
  byteHash: string;
  visualPlanSha256: string;
  pictureInputSha256: string;
  catalogPinSha256: string;
  upstreamAuthoritySha256: string;
  catalogReceiptAuthority?: CatalogReceiptAuthorityPin;
}

export interface CatalogReceiptAuthorityPin {
  schemaVersion: 1;
  path: string;
  sha256: string;
  digest: string;
  authorityId: string;
  runId: string;
  nonce: string;
  pipelineAuthoritySha256: string;
}

export interface BoundVisualPlan extends VisualPlanBinding {
  content: unknown;
}

export interface VisualPlanValidationAuthority {
  producerDir: string;
  pipeline: AutoEditPipelineAuthority;
}

function validationRuntime(authority?: VisualPlanValidationAuthority): {
  cli: string;
  pipelineRoot?: string;
} {
  if (!authority) {
    return { cli: path.join(runtimeScriptsDir(), "producer/planner/visual_plan_cli.py") };
  }
  const pipelineRoot = executablePipelineRoot(
    authority.producerDir, authority.pipeline,
  );
  return {
    // Historical snapshots are data authority only. Execute the installed
    // controller's validator so a rewritten project snapshot cannot become code.
    cli: path.join(runtimeScriptsDir(), "producer/planner/visual_plan_cli.py"),
    pipelineRoot,
  };
}

export function visualPlanValidationAuthority(
  ctx: {
    dir: string;
    pipeline?: AutoEditPipelineAuthority;
    visualPlanPipeline?: AutoEditPipelineAuthority;
  },
): VisualPlanValidationAuthority | undefined {
  const pipeline = ctx.visualPlanPipeline ?? ctx.pipeline;
  return pipeline ? { producerDir: ctx.dir, pipeline } : undefined;
}

function fingerprints(
  file: string,
  authority?: VisualPlanValidationAuthority,
  receipt?: CatalogReceiptAuthorityPin,
): Omit<VisualPlanBinding, "schemaVersion" | "path" | "byteHash" | "catalogReceiptAuthority"> {
  const runtime = validationRuntime(authority);
  const args = ["-B", runtime.cli, "fingerprints", file];
  if (receipt) args.push("--receipt-authority", receipt.path);
  const raw = execFileSync(pythonInterpreter(), args, {
    encoding: "utf8", timeout: 15_000, maxBuffer: 1024 * 1024,
    env: { NODE_ENV: "production", PYTHONDONTWRITEBYTECODE: "1", PYTHONUTF8: "1",
      ...(runtime.pipelineRoot ? { SNIPER_PIPELINE_ROOT: runtime.pipelineRoot } : {}) },
  });
  const value = JSON.parse(raw) as Record<string, unknown>;
  const keys = ["visualPlanSha256", "pictureInputSha256", "catalogPinSha256",
    "upstreamAuthoritySha256"] as const;
  if (Object.keys(value).sort().join("\0") !== [...keys].sort().join("\0")
      || keys.some((key) => typeof value[key] !== "string" || !SHA256.test(value[key]))) {
    throw new Error("visual-plan validator returned malformed fingerprints");
  }
  return Object.fromEntries(keys.map((key) => [key, value[key]])) as
    Omit<VisualPlanBinding, "schemaVersion" | "path" | "byteHash" | "catalogReceiptAuthority">;
}

function assertReceiptAuthority(
  value?: CatalogReceiptAuthorityPin,
): CatalogReceiptAuthorityPin | undefined {
  if (!value) return undefined;
  const stat = lstatSync(value.path);
  if (stat.isSymbolicLink() || !stat.isFile() || stat.nlink !== 1
      || stat.size < 2 || stat.size > MAX_VISUAL_PLAN_BYTES
      || realpathSync(value.path) !== value.path) {
    throw new Error("catalog receipt authority differs from its controller pin");
  }
  const descriptor = openSync(value.path, constants.O_RDONLY | constants.O_NOFOLLOW);
  let bytes: Buffer, before: ReturnType<typeof fstatSync>, after: ReturnType<typeof fstatSync>;
  try {
    before = fstatSync(descriptor); bytes = readFileSync(descriptor); after = fstatSync(descriptor);
  } finally { closeSync(descriptor); }
  const identity = (item: ReturnType<typeof fstatSync>) => [item.dev, item.ino,
    item.size, item.mtimeMs, item.ctimeMs, item.nlink].join(":");
  if (identity(before) !== identity(after) || before.nlink !== 1
      || bytes.length !== stat.size
      || createHash("sha256").update(bytes).digest("hex") !== value.sha256) {
    throw new Error("catalog receipt authority differs from its controller pin");
  }
  const document = JSON.parse(bytes.toString("utf8")) as Record<string, unknown>;
  for (const key of ["digest", "authorityId", "runId", "nonce",
    "pipelineAuthoritySha256"] as const) {
    if (document[key] !== value[key]) {
      throw new Error(`catalog receipt authority ${key} differs from its controller pin`);
    }
  }
  return value;
}

/** Validate one bounded planning artifact and freeze its exact identity. */
export function resolveVisualPlanBinding(
  file: string,
  authority?: VisualPlanValidationAuthority,
  receiptAuthority?: CatalogReceiptAuthorityPin,
): VisualPlanBinding | null {
  if (!existsSync(file)) return null;
  const stat = lstatSync(file);
  if (stat.isSymbolicLink() || !stat.isFile()
      || stat.size < 2 || stat.size > MAX_VISUAL_PLAN_BYTES) {
    throw new Error("VISUAL-PLAN.json must be one bounded regular file");
  }
  const canonical = realpathSync(file);
  const before = fileSha256(canonical);
  if (!before) throw new Error("VISUAL-PLAN.json is unreadable");
  const receipt = assertReceiptAuthority(receiptAuthority);
  const result = fingerprints(canonical, authority, receipt);
  const after = fileSha256(canonical);
  if (before !== after || statSync(canonical).size !== stat.size) {
    throw new Error("VISUAL-PLAN.json changed during validation");
  }
  return { schemaVersion: 1, path: canonical, byteHash: before, ...result,
    ...(receipt ? { catalogReceiptAuthority: receipt } : {}) };
}

/** Recheck the frozen artifact before a later prompt, review, or compilation step. */
export function assertVisualPlanBinding(
  binding: VisualPlanBinding,
  authority?: VisualPlanValidationAuthority,
): VisualPlanBinding {
  const current = resolveVisualPlanBinding(
    binding.path, authority, binding.catalogReceiptAuthority,
  );
  const ordered = (value: VisualPlanBinding) => Object.entries(value)
    .sort(([left], [right]) => left.localeCompare(right));
  if (!current || JSON.stringify(ordered(current)) !== JSON.stringify(ordered(binding))) {
    throw new Error("VISUAL-PLAN.json changed after planning context resolution");
  }
  return current;
}

/** Supply bounded plan content to a critic while retaining the validated pins. */
export function boundVisualPlanContent(
  binding: VisualPlanBinding,
  authority?: VisualPlanValidationAuthority,
): BoundVisualPlan {
  const current = assertVisualPlanBinding(binding, authority);
  const bytes = readFileSync(current.path);
  if (bytes.length > MAX_VISUAL_PLAN_BYTES || fileSha256(current.path) !== current.byteHash) {
    throw new Error("VISUAL-PLAN.json changed before bounded review read");
  }
  try {
    return { ...current, content: JSON.parse(bytes.toString("utf8")) as unknown };
  } catch (error) {
    throw new Error(`VISUAL-PLAN.json is invalid JSON: ${(error as Error).message}`);
  }
}

/** Resolve the enforced project visual-plan authority; absent only on legacy/ineligible work. */
export function projectVisualPlanBinding(
  producerDir: string,
  authority?: VisualPlanValidationAuthority,
  receiptAuthority?: CatalogReceiptAuthorityPin,
): VisualPlanBinding | null {
  return resolveVisualPlanBinding(
    path.join(producerDir, "VISUAL-PLAN.json"), authority, receiptAuthority,
  );
}

type NativeVisualMode = "short" | "long";

/** Validate one allocated whole-project route and return its exact frozen bytes. */
export function nativeVisualPlanSource(
  binding: VisualPlanBinding | undefined,
  mode: NativeVisualMode,
): string | null {
  if (!binding) return null;
  const bound = boundVisualPlanContent(binding);
  const plan = bound.content as {
    project?: { mode?: unknown };
    allocation?: { status?: unknown; route?: unknown };
  };
  const route = mode === "short" ? "native-short" : "native-long";
  if (plan.project?.mode !== mode || plan.allocation?.status !== "allocated"
      || plan.allocation?.route !== route) {
    throw new Error(`VISUAL-PLAN.json must allocate the complete ${mode} project to ${route}`);
  }
  const source = readFileSync(bound.path, "utf8");
  if (fileSha256(bound.path) !== bound.byteHash) {
    throw new Error("VISUAL-PLAN.json changed before native project staging");
  }
  return source;
}
