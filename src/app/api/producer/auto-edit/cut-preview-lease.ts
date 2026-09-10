import { constants, openSync, fstatSync, lstatSync, readSync, closeSync, realpathSync } from "node:fs";
import path from "node:path";
import type { ProjectMutationLease } from "@/lib/server/project-mutation-lease";
import { durableProcessAlive, validProcessIdentity } from "@/lib/server/process-liveness";
import { mutationProjectRoot } from "../../_lib/project-mutation";

function readLeaseRow(descriptor: number, size: number) {
  const bytes = Buffer.alloc(size + 1);
  const count = readSync(descriptor, bytes, 0, bytes.length, 0);
  if (count !== size) throw new Error("cut preview lease bytes changed");
  const row = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes.subarray(0, count)));
  const created = typeof row?.createdAt === "string" ? Date.parse(row.createdAt) : Number.NaN;
  if (!row || typeof row !== "object" || Array.isArray(row)
      || Object.keys(row).sort().join(",") !== "createdAt,identity,nonce,operation,pid"
      || row.pid !== process.pid || typeof row.nonce !== "string"
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(row.nonce)
      || typeof row.operation !== "string" || !row.operation.trim() || row.operation.length > 500
      || !Number.isFinite(created) || new Date(created).toISOString() !== row.createdAt
      || created > Date.now() + 60_000 || !validProcessIdentity(row.identity)
      || row.identity.pid !== row.pid
      || !durableProcessAlive(row.pid, row.identity, row.createdAt, { maxHeartbeatAgeMs: Number.MAX_SAFE_INTEGER })) {
    throw new Error("cut preview caller does not own the live project lease");
  }
  return row;
}

function readLease(producerDir: string) {
  const root = mutationProjectRoot(producerDir);
  if (realpathSync(root) !== root || lstatSync(root).isSymbolicLink()) throw new Error("cut preview lease root is unsafe");
  const lock = path.join(root, ".sniper-project-mutation.lock");
  const descriptor = openSync(lock, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const info = fstatSync(descriptor);
    if (!info.isFile() || info.size <= 0 || info.size > 16_000 || info.nlink !== 2) throw new Error("cut preview requires an exact live lease inode");
    const row = readLeaseRow(descriptor, info.size);
    const owner = lstatSync(path.join(root, `.sniper-project-mutation.owner-${row.nonce}.json`));
    const current = lstatSync(lock);
    if (!owner.isFile() || owner.isSymbolicLink() || current.isSymbolicLink()
        || owner.dev !== info.dev || owner.ino !== info.ino || current.ino !== info.ino
        || current.dev !== info.dev) {
      throw new Error("cut preview lease identity changed");
    }
    for (const item of [owner, current, fstatSync(descriptor)])
      for (const field of ["dev", "ino", "size", "mtimeMs", "ctimeMs", "nlink"] as const)
        if (item[field] !== info[field]) throw new Error("cut preview lease identity changed");
    return { nonce: row.nonce as string, ino: info.ino, dev: info.dev };
  } finally { closeSync(descriptor); }
}

/** Verify a caller-held lease by live owner/lock inode and nonce, never a boolean. */
export function cutPreviewLeaseGuard(producerDir: string, lease: ProjectMutationLease): () => void {
  if (!lease || typeof lease.release !== "function") throw new Error("cut preview requires its caller's held lease");
  const expected = readLease(producerDir);
  return () => {
    const current = readLease(producerDir);
    if (current.nonce !== expected.nonce || current.dev !== expected.dev || current.ino !== expected.ino) {
      throw new Error("cut preview project lease was replaced");
    }
  };
}
