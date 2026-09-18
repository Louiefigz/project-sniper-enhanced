/** TEST-only durable pre-fork identity. Records authorize cleanup, never observation. */
import fs from "node:fs";
import path from "node:path";
import { workspaceRoot } from "../../../src/app/api/_lib/workspace";
import { cutPreviewLeaseGuard } from "../../../src/app/api/producer/auto-edit/cut-preview-lease";
import { acquireProjectMutationLease } from "../../../src/lib/server/project-mutation-lease";
import { readBytes, sha } from "../../../src/app/api/producer/studio/import/files";
import { captureProcessIdentity, type ProcessIdentity } from "../../../src/lib/server/process-liveness";
import { object, privateDirectory, readRecord, SHA } from "../../../src/lib/server/grade-observation-store";
import { writeHeldRecord } from "./live_grade_v2_finalization";

export interface V2Pin { path: string; sha256: string }
export interface V2Runtime {
  docker: string; dockerSha256: string; socket: string; socketDevice: string; socketInode: string;
  imageId: string; userId: string; approvalSha256: string;
}
export interface V2Lifecycle {
  schemaVersion: 1; kind: "TEST-grade-v2-lifecycle"; root: string; producerDir: string;
  directory: string; resource: string; python: string; inputSha256: string; owner: ProcessIdentity; supervisor: ProcessIdentity;
  startedNs: string; deadlineNs: string; supervisorDeadlineNs: string; containerName: string;
  source: { path: string; sha256: string }; pins: V2Pin[]; runtime: V2Runtime;
}
export function hashV2(file: string, max = 8 * 1024 * 1024): string { return sha(readBytes(file, max)); }

/** Require positive identity facts; no heartbeat or guessed PID fallback. */
export function exactIdentity(pid: number): ProcessIdentity {
  const value = captureProcessIdentity(pid);
  if (!value.bootSession || !value.startToken) throw new Error("Exact process identity unavailable");
  return value;
}
export function groupState(pid: number): "absent" | "present" | "unknown" {
  if (!Number.isSafeInteger(pid) || pid < 2) return "unknown";
  try { process.kill(-pid, 0); return "present"; }
  catch (error) { return (error as NodeJS.ErrnoException).code === "ESRCH" ? "absent" : "unknown"; }
}

/** No daemon call; bind the exact local control endpoint and executable bytes. */
export function runtimeV2(root: string): V2Runtime {
  const env = process.env, docker = fs.realpathSync(env.SNIPER_DOCKER_PATH ?? "");
  const socket = fs.realpathSync(env.SNIPER_DOCKER_SOCKET ?? ""), info = fs.statSync(socket);
  const approvalPath = path.join(root, "scripts/producer/headless/render_image_approval.json");
  const approval = readRecord(approvalPath), imageId = env.SNIPER_RENDER_IMAGE_ID ?? "", userId = env.SNIPER_RENDER_UID_GID ?? "";
  if (!path.isAbsolute(env.SNIPER_DOCKER_PATH ?? "") || !path.isAbsolute(env.SNIPER_DOCKER_SOCKET ?? "")
      || !info.isSocket() || info.uid !== process.getuid?.() || !/^sha256:[a-f0-9]{64}$/u.test(imageId)
      || approval.imageId !== imageId || !/^[1-9][0-9]*:[1-9][0-9]*$/u.test(userId)) throw new Error("Invalid exact local runtime");
  return { docker, dockerSha256: hashV2(docker, 128 * 1024 * 1024), socket, socketDevice: String(info.dev),
    socketInode: String(info.ino), imageId, userId, approvalSha256: hashV2(approvalPath) };
}
export function pinV2(paths: string[]): V2Pin[] {
  return [...new Set(paths)].sort().map(file => ({ path: file, sha256: hashV2(file, 128 * 1024 * 1024) }));
}
export function checkPinsV2(pins: V2Pin[]): void {
  for (const row of pins) if (hashV2(row.path, 128 * 1024 * 1024) !== row.sha256) throw new Error("Held TEST lifecycle code changed");
}

/** This exact input and identity exist before active.json and before child fork. */
export function retainLifecycle(value: V2Lifecycle): string {
  return writeHeldRecord(path.join(value.directory, "TEST-lifecycle.json"), value);
}
function closed(value: Record<string, unknown>, keys: string[]): void {
  if (Object.keys(value).sort().join() !== keys.sort().join()) throw new Error("Malformed TEST lifecycle keys");
}
export function readLifecycle(directory: string, expected: string): V2Lifecycle {
  privateDirectory(directory);
  const file = path.join(directory, "TEST-lifecycle.json"), raw = readBytes(file, 1024 * 1024);
  if (!SHA.test(expected) || sha(raw) !== expected) throw new Error("Original lifecycle bytes changed");
  const row = object(JSON.parse(raw.toString("utf8")));
  closed(row, ["schemaVersion", "kind", "root", "producerDir", "directory", "resource", "python", "inputSha256", "owner", "supervisor",
    "startedNs", "deadlineNs", "supervisorDeadlineNs", "containerName", "source", "pins", "runtime"]);
  const value = row as unknown as V2Lifecycle, jobId = path.basename(directory);
  for (const clock of [value.startedNs, value.deadlineNs, value.supervisorDeadlineNs])
    if (typeof clock !== "string" || !/^[0-9]{1,24}$/u.test(clock)) throw new Error("Invalid original clock field");
  if (value.schemaVersion !== 1 || value.kind !== "TEST-grade-v2-lifecycle" || value.directory !== directory || !path.isAbsolute(value.python)
      || !/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/u.test(jobId)
      || directory !== path.join(value.producerDir, ".sniper-grade-observations", jobId)
      || value.containerName !== "sniper-grade-observation-" + jobId.replaceAll("-", "")
      || !SHA.test(value.inputSha256) || !/^[0-9]{1,24}$/u.test(value.startedNs) || !/^[0-9]{1,24}$/u.test(value.deadlineNs)
      || !/^[0-9]{1,24}$/u.test(value.supervisorDeadlineNs)
      || BigInt(value.deadlineNs) - BigInt(value.startedNs) !== BigInt(120_000_000_000)) throw new Error("Invalid original TEST lifecycle");
  closed(object(value.source), ["path", "sha256"]);
  if (!path.isAbsolute(value.source.path) || !SHA.test(value.source.sha256)) throw new Error("Invalid held source reference");
  for (const identity of [value.owner, value.supervisor]) {
    if (!Number.isSafeInteger(identity.pid) || identity.pid < 2 || typeof identity.bootSession !== "string"
        || !identity.bootSession || typeof identity.startToken !== "string" || !identity.startToken)
      throw new Error("Missing exact lifecycle identity");
    closed(object(identity), ["pid", "bootSession", "startToken"]);
  }
  if (!Array.isArray(value.pins) || value.pins.length < 5 || value.pins.length > 4000
      || new Set(value.pins.map(pin => pin.path)).size !== value.pins.length) throw new Error("Invalid lifecycle pins");
  for (const pin of value.pins) {
    closed(object(pin), ["path", "sha256"]);
    if (!path.isAbsolute(pin.path) || !SHA.test(pin.sha256)) throw new Error("Invalid lifecycle pin");
  }
  return value;
}

/** Unknown/reused/live groups remain fenced; recovery never signals a guessed PID. */
export function requireStoppedV2(value: V2Lifecycle): void {
  const current = exactIdentity(process.pid);
  if (current.bootSession !== value.supervisor.bootSession || groupState(value.supervisor.pid) !== "absent")
    throw new Error("Original supervisor whole-group absence is unproved");
  // A recycled leader PID is not accepted even when it currently heads another group.
  try { process.kill(value.supervisor.pid, 0); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ESRCH") return; throw error; }
  throw new Error("Supervisor PID is live or reused; retain exact claim");
}

export function acquireV2Scope(dir: string, recovery = false) {
  const operation = "TEST-only V2 source observation or exact cleanup; no approval";
  const resource = privateDirectory(path.join(fs.realpathSync(workspaceRoot()), ".sniper-color-resource"), true);
  const project = acquireProjectMutationLease(path.dirname(dir), operation);
  if (!project.lease) throw new Error("TEST project is busy");
  const shared = acquireProjectMutationLease(resource, operation);
  if (!shared.lease) { project.lease.release(); throw new Error("Shared color resource is busy"); }
  const guardProject = cutPreviewLeaseGuard(dir, project.lease), guardResource = cutPreviewLeaseGuard(resource, shared.lease);
  if (!recovery && fs.existsSync(path.join(resource, "active.json"))) {
    shared.lease.release(); project.lease.release(); throw new Error("Prior color ownership requires exact recovery");
  }
  return { resource, guard: () => { guardProject(); guardResource(); },
    release: () => { shared.lease.release(); project.lease.release(); } };
}
