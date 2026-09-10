import { createHash, randomUUID } from "node:crypto";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import type {
  AutoEditCtx,
  AutoEditDoctrineAuthority,
} from "@/app/api/producer/auto-edit/stream";
import { canonicalJsonSha256 } from "./auto-edit-hash";

export const PRODUCER_CORE_DOCTRINE_PATHS = [
  ".agents/skills/producer/SKILL.md",
  ".claude/skills/producer/SKILL.md",
  "docs/PIPELINE.md",
  "scripts/producer/docs/findings/FAILURE_LEDGER.md",
  "scripts/producer/docs/findings/QC_CHECKLIST.md",
] as const;

export const PRODUCER_REFERENCED_DOCTRINE_PATHS = [
  "CLAUDE.md",
  "docs/studies/EDIT_DECISION_STUDY.md",
  "docs/studies/EDITCRAFT_LESSONS.md",
  "docs/audits/INTRO_MACHINE_VS_PRO_AUDIT.md",
  "docs/studies/LONGFORM_VISUAL_STUDY.md",
  "docs/studies/MEASURED_EDIT_GRAMMAR.md",
  "docs/studies/MOTION_GRAMMAR_STUDY.md",
  "docs/studies/NATEHERK_CARDS.md",
  "docs/studies/NATEHERK_STUDY.md",
  "docs/studies/PACING_RHYTHM_STUDY.md",
  "docs/producer/PRODUCER_EDGE_CASES.md",
  "docs/producer/PRODUCER_PLAN.md",
  "docs/producer/PRODUCER_README.md",
  "docs/studies/PRODUCTION_ENVELOPE_STUDY.md",
  "docs/studies/REFERENCE_STYLE_STUDY.md",
  "docs/studies/SHORTFORM_LESSONS.md",
  "scripts/producer/docs/findings/REFERENCE_EVIDENCE_IS_NOT_TEMPLATE_AUTHORITY.md",
] as const;

const STYLE_DOCTRINE: Record<string, string> = {
  caleb: "docs/studies/CALEB_STYLE.md",
  jadenly: "scripts/producer/docs/findings/JADEN_STYLE.md",
  angela: "docs/studies/ANGELA_STYLE.md",
};
const SHA256 = /^[0-9a-f]{64}$/;
const LEARNING_DIR = ".sniper-learning";

interface DoctrineRow {
  path: string;
  hash: string;
  content: string;
}

interface DoctrineSnapshot {
  schemaVersion: 1;
  state: "pinned";
  runId: string;
  doctrineHash: string;
  files: DoctrineRow[];
  activation: {
    kind: "repository-baseline";
    previousDoctrineHash: null;
    rollbackDoctrineHash: null;
    proposalIds: [];
    evidenceHash: null;
  };
  lockHash: string;
}

function textHash(content: string): string {
  return createHash("sha256").update(content, "utf8").digest("hex");
}

function repositoryRoot(): string {
  let current = path.resolve(process.cwd());
  for (;;) {
    if (existsSync(path.join(current, "scripts", "producer"))) return current;
    const parent = path.dirname(current);
    if (parent === current) throw new Error("Producer repository root was not found");
    current = parent;
  }
}

function safeRunId(value: string): string {
  const safe = value.replace(/[^a-zA-Z0-9._-]/g, "_").slice(-96);
  if (!safe) throw new Error("doctrine run id is empty");
  return safe;
}

function sourcePaths(ctx: AutoEditCtx, additional: readonly string[] = []): string[] {
  const selected = ctx.intent?.style ?? ctx.intent?.reference?.targetStyle;
  const style = selected ? STYLE_DOCTRINE[selected] : undefined;
  return [...new Set([
    ...PRODUCER_CORE_DOCTRINE_PATHS,
    ...PRODUCER_REFERENCED_DOCTRINE_PATHS,
    ...(style ? [style] : []),
    ...additional,
  ])].sort();
}

function readExactUtf8(filePath: string): string {
  const bytes = readFileSync(filePath);
  const content = bytes.toString("utf8");
  if (!Buffer.from(content, "utf8").equals(bytes)) {
    throw new Error(`Producer doctrine is not exact UTF-8 text: ${filePath}`);
  }
  return content;
}

function captureRows(
  ctx: AutoEditCtx,
  root: string,
  additional: readonly string[],
): DoctrineRow[] {
  return sourcePaths(ctx, additional).map((relative) => {
    const source = path.join(root, relative);
    if (!existsSync(source) || !lstatSync(source).isFile()) {
      throw new Error(`Producer doctrine source is missing: ${relative}`);
    }
    const content = readExactUtf8(source);
    return { path: relative, hash: textHash(content), content };
  });
}

function snapshotValue(runId: string, rows: DoctrineRow[]): DoctrineSnapshot {
  const receipts = rows.map(({ path: rowPath, hash }) => ({ path: rowPath, hash }));
  const doctrineHash = canonicalJsonSha256({ schemaVersion: 1, files: receipts });
  const base = {
    schemaVersion: 1 as const,
    state: "pinned" as const,
    runId,
    doctrineHash,
    files: receipts,
    activation: {
      kind: "repository-baseline" as const,
      previousDoctrineHash: null,
      rollbackDoctrineHash: null,
      proposalIds: [] as [],
      evidenceHash: null,
    },
  };
  return { ...base, files: rows, lockHash: canonicalJsonSha256(base) };
}

function writeSnapshotTree(staging: string, snapshot: DoctrineSnapshot): void {
  const filesRoot = path.join(staging, "files");
  for (const row of snapshot.files) {
    const destination = path.join(filesRoot, row.path);
    mkdirSync(path.dirname(destination), { recursive: true, mode: 0o700 });
    writeFileSync(destination, row.content, { flag: "wx", mode: 0o600 });
  }
  writeFileSync(path.join(staging, "doctrine-lock.json"), `${JSON.stringify(snapshot, null, 2)}\n`, {
    flag: "wx", mode: 0o600,
  });
}

function authority(snapshotDir: string, snapshot: DoctrineSnapshot): AutoEditDoctrineAuthority {
  return {
    runId: snapshot.runId,
    doctrineHash: snapshot.doctrineHash,
    snapshotPath: path.join(snapshotDir, "doctrine-lock.json"),
    files: Object.fromEntries(snapshot.files.map((row) => [
      row.path, path.join(snapshotDir, "files", row.path),
    ])),
  };
}

/** Capture exact doctrine bytes before any writer/critic process can start. */
export function captureAutoEditDoctrine(
  ctx: AutoEditCtx,
  runId: string,
  root = repositoryRoot(),
  additionalPaths: readonly string[] = [],
): AutoEditDoctrineAuthority {
  const stableRunId = safeRunId(runId);
  const rows = captureRows(ctx, root, additionalPaths);
  const snapshot = snapshotValue(stableRunId, rows);
  const runs = path.join(ctx.dir, LEARNING_DIR, "runs");
  const destination = path.join(runs, stableRunId, "doctrine");
  const staging = path.join(runs, `.${stableRunId}.${randomUUID()}.tmp`);
  if (existsSync(destination)) throw new Error(`Doctrine snapshot already exists for ${stableRunId}`);
  mkdirSync(staging, { recursive: true, mode: 0o700 });
  try {
    writeSnapshotTree(staging, snapshot);
    mkdirSync(path.dirname(destination), { recursive: true, mode: 0o700 });
    renameSync(staging, destination);
  } finally {
    rmSync(staging, { recursive: true, force: true });
  }
  return authority(destination, snapshot);
}

function validEnvelope(value: unknown): value is DoctrineSnapshot {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as Partial<DoctrineSnapshot>;
  return item.schemaVersion === 1 && item.state === "pinned"
    && typeof item.runId === "string" && typeof item.doctrineHash === "string"
    && SHA256.test(item.doctrineHash) && typeof item.lockHash === "string"
    && SHA256.test(item.lockHash) && Array.isArray(item.files)
    && item.activation?.kind === "repository-baseline";
}

function verifyRows(snapshotPath: string, snapshot: DoctrineSnapshot): void {
  const seen = new Set<string>();
  const filesRoot = path.join(path.dirname(snapshotPath), "files");
  for (const row of snapshot.files) {
    const valid = row && typeof row.path === "string" && row.path
      && !path.isAbsolute(row.path) && !row.path.split(path.sep).includes("..")
      && typeof row.content === "string" && SHA256.test(row.hash);
    if (!valid || seen.has(row.path) || textHash(row.content) !== row.hash) {
      throw new Error("Pinned Producer doctrine snapshot was changed");
    }
    seen.add(row.path);
    const copy = path.join(filesRoot, row.path);
    if (!existsSync(copy) || !lstatSync(copy).isFile() || readExactUtf8(copy) !== row.content) {
      throw new Error(`Pinned Producer doctrine copy was changed: ${row.path}`);
    }
  }
}

/** Restore a persisted doctrine lock without consulting live repository text. */
export function restoreAutoEditDoctrine(
  expected: AutoEditDoctrineAuthority,
): AutoEditDoctrineAuthority {
  if (!path.isAbsolute(expected.snapshotPath) || !existsSync(expected.snapshotPath)
      || !lstatSync(expected.snapshotPath).isFile()) {
    throw new Error("Pinned Producer doctrine snapshot is missing");
  }
  const value: unknown = JSON.parse(readFileSync(expected.snapshotPath, "utf8"));
  if (!validEnvelope(value)) throw new Error("Pinned Producer doctrine envelope is invalid");
  verifyRows(expected.snapshotPath, value);
  const receipt = { ...value, files: value.files.map(({ path: rowPath, hash }) => ({ path: rowPath, hash })) };
  delete (receipt as Partial<DoctrineSnapshot>).lockHash;
  const doctrineHash = canonicalJsonSha256({ schemaVersion: 1, files: receipt.files });
  if (doctrineHash !== value.doctrineHash || canonicalJsonSha256(receipt) !== value.lockHash
      || value.runId !== expected.runId || value.doctrineHash !== expected.doctrineHash) {
    throw new Error("Pinned Producer doctrine authority does not match its receipt");
  }
  const restored = authority(path.dirname(expected.snapshotPath), value);
  if (canonicalJsonSha256(restored.files) !== canonicalJsonSha256(expected.files)) {
    throw new Error("Pinned Producer doctrine file map was changed");
  }
  return restored;
}

export function doctrinePromptPath(ctx: AutoEditCtx, relative: string): string {
  return ctx.doctrine?.files[relative] ?? path.join(repositoryRoot(), relative);
}

export function doctrinePromptRoot(ctx: AutoEditCtx): string {
  return ctx.doctrine
    ? path.join(path.dirname(ctx.doctrine.snapshotPath), "files")
    : repositoryRoot();
}

export interface DoctrineLaunchInput {
  ctx: AutoEditCtx;
  runId: string;
  resume: boolean;
  saved?: AutoEditDoctrineAuthority;
}

export function prepareAutoEditDoctrineContext(input: DoctrineLaunchInput): AutoEditCtx {
  if (input.resume && !input.saved) {
    throw new Error("checkpoint predates immutable doctrine locking");
  }
  const doctrine = input.saved
    ? restoreAutoEditDoctrine(input.saved)
    : captureAutoEditDoctrine(input.ctx, input.runId);
  return { ...input.ctx, doctrine };
}
