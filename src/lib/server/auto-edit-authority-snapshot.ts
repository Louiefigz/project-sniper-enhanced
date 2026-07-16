import { createHash } from "node:crypto";
import {
  existsSync,
  lstatSync,
  readFileSync,
  readdirSync,
} from "node:fs";
import path from "node:path";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { fileSha256 } from "./auto-edit-hash";
import { planContentHash } from "./auto-edit-authority";
import { restoreAutoEditDoctrine } from "./auto-edit-doctrine";
import { restoreAutoEditPipeline } from "./auto-edit-pipeline-authority";

export const AUTO_EDIT_AUTHORITY_SCHEMA_VERSION = 1 as const;
export const AUTO_EDIT_QUALITY_POLICY_VERSION = 1 as const;

export interface AutoEditAuthoritySnapshot {
  schemaVersion: typeof AUTO_EDIT_AUTHORITY_SCHEMA_VERSION;
  qualityPolicyVersion: typeof AUTO_EDIT_QUALITY_POLICY_VERSION;
  digest: string;
  planHash: string | null;
  planContentHash: string | null;
  manifestHash: string | null;
  operatorIntentDigest: string;
  transcriptDigest: string;
  referenceDigest: string;
  pipelineDigest: string;
}

interface FileAuthority {
  path: string;
  hash: string | null;
}

function compareText(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => compareText(left, right))
      .map(([key, item]) => [key, stableValue(item)]),
  );
}

export function stableAuthorityHash(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(stableValue(value))).digest("hex");
}

function logicalFile(filePath: string, base: string): FileAuthority {
  const relative = path.relative(base, filePath);
  return {
    path: (relative && !relative.startsWith("..") ? relative : path.basename(filePath))
      .split(path.sep).join("/"),
    hash: fileSha256(filePath) ?? null,
  };
}

function jsonValue(filePath: string): unknown {
  try {
    return JSON.parse(readFileSync(filePath, "utf8")) as unknown;
  } catch {
    return null;
  }
}

function storedIntent(ctx: AutoEditCtx): unknown {
  const project = jsonValue(path.join(path.dirname(ctx.dir), "project.json"));
  if (!project || typeof project !== "object" || Array.isArray(project)) return null;
  return (project as Record<string, unknown>).intent ?? null;
}

function transcriptFiles(ctx: AutoEditCtx): FileAuthority[] {
  const manifest = jsonValue(ctx.manifestPath) as { sources?: unknown } | null;
  if (!manifest || !Array.isArray(manifest.sources)) return [];
  return manifest.sources.map((source, index) => {
    const transcript = source && typeof source === "object" && !Array.isArray(source)
      ? (source as Record<string, unknown>).transcriptPath : null;
    if (typeof transcript !== "string" || !transcript) {
      return { path: `source-${index + 1}:missing-transcript`, hash: null };
    }
    const resolved = path.isAbsolute(transcript)
      ? transcript : path.join(path.dirname(ctx.manifestPath), transcript);
    return logicalFile(resolved, ctx.transcriptsDir);
  });
}

function referenceFiles(ctx: AutoEditCtx): FileAuthority[] {
  const study = ctx.referenceStudy;
  if (!study) return [];
  const studyOutputDir = path.dirname(study.deepStudyPath);
  const candidates = [
    study.profilePath,
    study.deepStudyPath,
    ...study.representativeFrames,
    path.join(studyOutputDir, "reference.json"),
    path.join(studyOutputDir, "fingerprint.json"),
    path.join(study.dir, "reference-source.json"),
  ];
  return [...new Set(candidates)].map((item) => logicalFile(item, study.dir));
}

function repositoryRoot(): string {
  let current = path.resolve(process.cwd());
  for (;;) {
    if (existsSync(path.join(current, "scripts", "producer"))) return current;
    const parent = path.dirname(current);
    if (parent === current) return path.resolve(process.cwd());
    current = parent;
  }
}

function excludedPipelinePath(relative: string): boolean {
  const parts = relative.split(path.sep);
  return parts.some((part) => [
    "__pycache__", "__tests__", "node_modules", "renders", "cache", "tests", "docs",
    "study",
  ].includes(part)) || /\.(?:mov|mp4|wav|mp3|pyc)$/i.test(relative);
}

function pipelineFileAllowed(filePath: string): boolean {
  return /\.(?:py|ts|tsx|js|json|html|css|md|svg|png|jpe?g)$/i.test(filePath);
}

function walkPipelineFiles(root: string, item: string): string[] {
  if (!existsSync(item)) return [];
  const relative = path.relative(root, item);
  if (excludedPipelinePath(relative)) return [];
  const stat = lstatSync(item);
  if (stat.isSymbolicLink()) return [];
  if (stat.isFile()) return pipelineFileAllowed(item) ? [item] : [];
  if (!stat.isDirectory()) return [];
  return readdirSync(item).sort().flatMap((name) => walkPipelineFiles(root, path.join(item, name)));
}

let pipelineCache: { signature: string; files: FileAuthority[] } | null = null;

function pinnedDoctrineAuthority(ctx: AutoEditCtx, root: string): FileAuthority[] {
  if (ctx.doctrine) {
    const restored = restoreAutoEditDoctrine(ctx.doctrine);
    return [{ path: ".sniper/pinned-producer-doctrine", hash: restored.doctrineHash }];
  }
  const legacy = path.join(root, ".agents", "skills", "producer", "SKILL.md");
  return walkPipelineFiles(root, legacy).map((item) => logicalFile(item, root));
}

function livePipelineFiles(root: string): FileAuthority[] {
  const roots = [
    path.join(root, "scripts", "producer"),
    path.join(root, "templates", "motion"),
    path.join(root, "src", "app", "api", "producer", "auto-edit"),
    path.join(root, "src", "app", "api", "producer", "ai-edit"),
    path.join(root, "src", "app", "api", "producer", "live-build"),
    path.join(root, "src", "app", "api", "producer", "palmier"),
    path.join(root, "src", "app", "api", "_lib"),
    path.join(root, "src", "lib", "producer"),
    path.join(root, "src", "lib", "server"),
    path.join(root, "package.json"),
    path.join(root, "package-lock.json"),
  ];
  const paths = [...new Set(roots.flatMap((item) => walkPipelineFiles(root, item)))].sort();
  const signature = stableAuthorityHash(paths.map((item) => {
    const stat = lstatSync(item);
    return [path.relative(root, item), stat.size, stat.mtimeMs];
  }));
  if (pipelineCache?.signature !== signature) {
    pipelineCache = { signature, files: paths.map((item) => logicalFile(item, root)) };
  }
  return pipelineCache.files;
}

function pipelineFiles(ctx: AutoEditCtx): FileAuthority[] {
  const root = repositoryRoot();
  const pipeline = ctx.pipeline
    ? restoreAutoEditPipeline(ctx.pipeline).files
    : livePipelineFiles(root);
  return [...pipeline, ...pinnedDoctrineAuthority(ctx, root)]
    .sort((left, right) => compareText(left.path, right.path));
}

/**
 * Versioned render/QC authority. Source videos are deliberately represented by
 * their manifest content hashes; only plans, transcripts, reference-study
 * evidence, renderer/config/template sources, and QC policy code are hashed.
 */
export function autoEditAuthoritySnapshot(ctx: AutoEditCtx): AutoEditAuthoritySnapshot {
  const components = {
    schemaVersion: AUTO_EDIT_AUTHORITY_SCHEMA_VERSION,
    qualityPolicyVersion: AUTO_EDIT_QUALITY_POLICY_VERSION,
    scope: ctx.scope,
    planHash: fileSha256(ctx.planPath) ?? null,
    planContentHash: planContentHash(ctx.planPath) ?? null,
    manifestHash: fileSha256(ctx.manifestPath) ?? null,
    operatorIntent: { stored: storedIntent(ctx), requested: ctx.intent ?? null },
    transcripts: transcriptFiles(ctx),
    reference: {
      request: ctx.intent?.reference ?? null,
      identity: ctx.referenceStudy
        ? { id: ctx.referenceStudy.id, mode: ctx.referenceStudy.mode, title: ctx.referenceStudy.title }
        : null,
      files: referenceFiles(ctx),
    },
    pipelineFiles: pipelineFiles(ctx),
  };
  const operatorIntentDigest = stableAuthorityHash(components.operatorIntent);
  const transcriptDigest = stableAuthorityHash(components.transcripts);
  const referenceDigest = stableAuthorityHash(components.reference);
  const pipelineDigest = stableAuthorityHash(components.pipelineFiles);
  const summary = {
    schemaVersion: components.schemaVersion,
    qualityPolicyVersion: components.qualityPolicyVersion,
    scope: components.scope,
    planHash: components.planHash,
    planContentHash: components.planContentHash,
    manifestHash: components.manifestHash,
    operatorIntentDigest,
    transcriptDigest,
    referenceDigest,
    pipelineDigest,
  };
  return { ...summary, digest: stableAuthorityHash(summary) };
}

export function sameAutoEditAuthority(
  left: AutoEditAuthoritySnapshot,
  right: AutoEditAuthoritySnapshot,
): boolean {
  return left.digest === right.digest;
}
