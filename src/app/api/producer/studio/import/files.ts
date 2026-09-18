import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { atomicCreateJsonSync, atomicWriteJsonSync } from "@/lib/server/atomic-file";
import { ImportError, type ImportHead, type OriginalSession, type Proposal } from "./model";
import { assertOriginalBindings, assertProposalBindings, sha } from "./evidence";
export { jsonText, sha } from "./evidence";

export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;

/** Bounded no-follow reads; never return a racing or non-regular authority file. */
export function readBytes(file: string, limit = 8 * 1024 * 1024): Buffer {
  if (fs.realpathSync(file) !== file) throw new ImportError("Import evidence/input symlinks are not supported");
  const parent = path.dirname(file); const parentBefore = fs.lstatSync(parent, { bigint: true });
  const namedBefore = fs.lstatSync(file, { bigint: true });
  if (!namedBefore.isFile() || namedBefore.nlink !== BigInt(1) || namedBefore.size > BigInt(limit)) {
    throw new ImportError("Import input must be a bounded regular file without hardlinks");
  }
  const fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
  try {
    const before = fs.fstatSync(fd, { bigint: true });
    if (!before.isFile() || before.nlink !== BigInt(1) || before.size > BigInt(limit)
        || before.dev !== namedBefore.dev || before.ino !== namedBefore.ino) throw new ImportError("Import input changed before reading");
    const bytes = Buffer.alloc(Number(before.size));
    let offset = 0;
    while (offset < bytes.length) {
      const count = fs.readSync(fd, bytes, offset, bytes.length - offset, offset);
      if (!count) throw new ImportError("Import input changed while reading");
      offset += count;
    }
    const after = fs.fstatSync(fd, { bigint: true }); const namedAfter = fs.lstatSync(file, { bigint: true });
    const parentAfter = fs.lstatSync(parent, { bigint: true });
    if (after.size !== before.size || after.mtimeNs !== before.mtimeNs || after.ctimeNs !== before.ctimeNs
        || after.nlink !== BigInt(1) || namedAfter.nlink !== BigInt(1) || namedAfter.dev !== before.dev || namedAfter.ino !== before.ino
        || parentBefore.dev !== parentAfter.dev || parentBefore.ino !== parentAfter.ino
        || fs.realpathSync(file) !== file) throw new ImportError("Import input changed while reading");
    return bytes;
  } finally { fs.closeSync(fd); }
}

export function decodeText(bytes: Buffer): string {
  const text = bytes.toString("utf8");
  if (!Buffer.from(text, "utf8").equals(bytes)) throw new ImportError("Studio import text must be valid UTF-8");
  return text;
}

export function readText(file: string, limit = 8 * 1024 * 1024): string {
  return decodeText(readBytes(file, limit));
}

export function evidenceDir(dir: string, create = false): string {
  const root = path.join(dir, ".sniper-studio-imports");
  if (create && !fs.existsSync(root)) fs.mkdirSync(root, { mode: 0o700 });
  if (fs.existsSync(root) && (fs.realpathSync(root) !== root || !fs.lstatSync(root).isDirectory())) {
    throw new ImportError("Studio import evidence directory is unsafe");
  }
  return root;
}

export function seal<T extends object>(value: T): T & { digest: string } {
  return { ...value, digest: sha(JSON.stringify(value)) };
}

function checked<T extends { digest: string }>(file: string): T {
  const record = JSON.parse(readText(file)) as T;
  const { digest, ...body } = record;
  if (typeof digest !== "string" || digest !== sha(JSON.stringify(body))) throw new ImportError("Studio import evidence digest is invalid");
  return record;
}

export function readSession(dir: string): OriginalSession | null {
  const file = path.join(evidenceDir(dir), "session.json");
  if (!fs.existsSync(file)) return null;
  const session = checked<OriginalSession>(file);
  if (session.schema !== 1 || session.dir !== dir) throw new ImportError("Studio import session belongs to another project");
  assertOriginalBindings(session);
  return session;
}

export function createSession(dir: string, session: OriginalSession): void {
  assertOriginalBindings(session);
  atomicCreateJsonSync(path.join(evidenceDir(dir, true), "session.json"), session);
}

export function createProposal(dir: string, proposal: Proposal): void {
  assertProposalBindings(proposal);
  atomicCreateJsonSync(path.join(evidenceDir(dir, true), `${proposal.id}.json`), proposal);
}

export function readProposal(dir: string, id: string): Proposal {
  if (!UUID.test(id)) throw new ImportError("Invalid Studio proposal identity", 400, "INVALID_REQUEST");
  const proposal = checked<Proposal>(path.join(evidenceDir(dir), `${id}.json`));
  if (proposal.id !== id || proposal.schema !== 1) throw new ImportError("Studio proposal identity mismatch");
  assertProposalBindings(proposal);
  return proposal;
}

export function readHead(dir: string): ImportHead | null {
  const file = path.join(evidenceDir(dir), "head.json");
  return fs.existsSync(file) ? JSON.parse(readText(file)) as ImportHead : null;
}

/** Durable intent precedes the plan write; committed state is exact after-SHA equality. */
export function writeHead(dir: string, proposal: Proposal): void {
  atomicWriteJsonSync(path.join(evidenceDir(dir), "head.json"), {
    proposalId: proposal.id, digest: proposal.digest, previous: proposal.previous,
  });
}

export async function withBridgeInput<T>(dir: string, input: unknown, run: (file: string) => Promise<T>): Promise<T> {
  const file = path.join(evidenceDir(dir, true), `${randomUUID()}.request.json`);
  atomicCreateJsonSync(file, input);
  try { return await run(file); } finally { fs.rmSync(file, { force: true }); }
}
