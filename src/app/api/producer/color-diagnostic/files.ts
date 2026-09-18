import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { atomicCreateJsonSync } from "@/lib/server/atomic-file";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { captureProcessIdentity, type ProcessIdentity } from "@/lib/server/process-liveness";
import type { ColorDescriptor, ColorStart } from "@/lib/producer/color-diagnostic";
import { readBytes, decodeText } from "../studio/import/files";
import { ColorError, object, SHA, UUID, validateContexts } from "./request";

export const hash = (bytes: string | Buffer): string => createHash("sha256").update(bytes).digest("hex");
export const readJson = (file: string): Record<string, unknown> => object(JSON.parse(decodeText(readBytes(file, 2 * 1024 * 1024))));
export interface JobRequest {
  schema: 1; request: ColorStart; descriptor: ColorDescriptor; startedAt: string;
  owner: ProcessIdentity; digest: string; planText: string;
}
export interface JobTerminal {
  diagnosticId: string | null; cleanupVerified: boolean; elapsedMs: number;
  interrupted: boolean; requestDigest: string;
}

/** Only canonical, private, same-user directories may contain private evidence. */
export function privateDir(root: string, create = false): string {
  if (create && !fs.existsSync(root)) fs.mkdirSync(root, { mode: 0o700 });
  const info = fs.lstatSync(root);
  if (fs.realpathSync(root) !== root || !info.isDirectory() || info.isSymbolicLink()
      || info.uid !== process.getuid?.() || (info.mode & 0o077) !== 0) {
    throw new ColorError("Private diagnostic storage is unsafe", 409, "COLOR_STORAGE_UNSAFE");
  }
  return root;
}
export function jobDir(dir: string, id: string, create = false): string {
  if (!UUID.test(id)) throw new ColorError("Invalid diagnostic token");
  const store = path.join(dir, ".sniper-color-jobs");
  if (!create && !fs.existsSync(store)) throw new ColorError("Diagnostic not found", 404);
  privateDir(store, create);
  const job = path.join(store, id);
  if (create) fs.mkdirSync(job, { mode: 0o700 });
  return privateDir(job);
}
export function createRecord(file: string, value: unknown): void {
  privateDir(path.dirname(file));
  atomicCreateJsonSync(file, value);
  fs.chmodSync(file, 0o400);
}
export function newRequest(request: ColorStart, descriptor: ColorDescriptor, receivedAt = Date.now()): JobRequest {
  const owner = captureProcessIdentity(process.pid);
  if (!owner.startToken || !owner.bootSession) throw new ColorError("Exact process identity is unavailable", 503);
  const planText = decodeText(readBytes(path.join(request.dir, "edit_plan.json"), 2 * 1024 * 1024));
  if (hash(planText) !== request.expectedPlanHash) throw new ColorError("Saved plan changed", 409);
  const body = { schema: 1 as const, request, descriptor, startedAt: new Date(receivedAt).toISOString(), owner, planText };
  return { ...body, digest: canonicalJsonSha256(body) };
}
export function readRequest(dir: string, id: string): JobRequest {
  const value = readJson(path.join(jobDir(dir, id), "request.json")) as unknown as JobRequest;
  const { digest, ...body } = value;
  if (value.schema !== 1 || value.request?.dir !== dir || value.request?.jobId !== id
      || digest !== canonicalJsonSha256(body) || !SHA.test(value.request.expectedPlanHash)
      || !SHA.test(value.request.expectedManifestHash)
      || value.descriptor?.planHash !== value.request.expectedPlanHash
      || value.descriptor?.manifestHash !== value.request.expectedManifestHash
      || typeof value.planText !== "string" || hash(value.planText) !== value.request.expectedPlanHash
      || hash(JSON.stringify(object(JSON.parse(value.planText)).cutTrack ?? [])) !== value.descriptor.cutHash
      || !Number.isFinite(Date.parse(value.startedAt)) || !value.owner?.startToken || !value.owner?.bootSession) {
    throw new ColorError("Diagnostic request binding is invalid", 409);
  }
  validateContexts(value.request.contexts, value.descriptor.sources);
  return value;
}
export function descriptor(dir: string): ColorDescriptor {
  const planRaw = readBytes(path.join(dir, "edit_plan.json"), 2 * 1024 * 1024);
  const manifestRaw = readBytes(path.join(dir, "asset_manifest.json"), 2 * 1024 * 1024);
  const plan = object(JSON.parse(decodeText(planRaw))), manifest = object(JSON.parse(decodeText(manifestRaw)));
  const cut = Array.isArray(plan.cutTrack) ? plan.cutTrack.map(object) : [];
  const ids = new Set(cut.map(row => row.sourceId));
  const rows = Array.isArray(manifest.sources) ? manifest.sources.map(object).filter(row => ids.has(row.id)) : [];
  if (!rows.length || rows.length > 8 || new Set(rows.map(row => row.id)).size !== ids.size) throw new ColorError("A saved cut with 1–8 distinct sources is required", 409);
  const sources = rows.map(row => {
    if (typeof row.id !== "string" || row.id.length > 200 || typeof row.duration !== "number"
        || !Number.isFinite(row.duration) || row.duration <= 0 || row.duration > 21600) throw new ColorError("Source duration or identity is unsupported", 409);
    return { id: row.id, duration: row.duration, label: typeof row.path === "string" ? path.basename(row.path).slice(0, 200) : row.id,
      sha256: typeof row.sourceSha256 === "string" && SHA.test(row.sourceSha256) ? row.sourceSha256 : null };
  });
  const project = readJson(path.join(path.dirname(dir), "project.json"));
  const history = Array.isArray(project.history) ? project.history.slice(-40).map(object) : [];
  return { ok: true, kind: "descriptor", planHash: hash(planRaw), manifestHash: hash(manifestRaw),
    cutHash: hash(JSON.stringify(plan.cutTrack ?? [])), sources,
    blockers: !manifest.sourceSetAdmission || sources.some(row => !row.sha256)
      ? ["Current source-set admission is required. Re-ingest legacy media; this panel does not admit it."] : [],
    projectHistory: history.map(row => ({ stage: String(row.stage ?? "unknown").slice(0, 200), at: String(row.at ?? "unknown").slice(0, 100) })) };
}
