import assert from "node:assert/strict";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { atomicWriteFileSync } from "../atomic-file";
import { acquireProjectMutationLease } from "../project-mutation-lease";
import { guardProjectMutation } from "../../../app/api/_lib/project-mutation";
import {
  beginProducerRunWithToken,
  clearProducerRun,
} from "../producer-run-registry";

function leaseSerializes(root: string): void {
  mkdirSync(root);
  const first = acquireProjectMutationLease(root, "saving timeline changes");
  assert.ok(first.lease);
  const blocked = acquireProjectMutationLease(root, "applying an AI timeline change");
  assert.equal(blocked.lease, undefined);
  assert.equal(blocked.conflict?.operation, "saving timeline changes");
  first.lease.release();
  const next = acquireProjectMutationLease(root, "applying an AI timeline change");
  assert.ok(next.lease);
  next.lease.release();
}

async function activeRunIsActionable(root: string): Promise<void> {
  const producerDir = path.join(root, "producer");
  mkdirSync(producerDir);
  beginProducerRunWithToken({
    dir: producerDir,
    kind: "auto_edit",
    phase: "planning_review",
    message: "reviewing",
    token: "active-run",
  });
  const guarded = guardProjectMutation({
    projectRoot: root,
    producerDir,
    operation: "saving timeline changes",
  });
  assert.ok(guarded.response);
  assert.equal(guarded.response.status, 409);
  const body = await guarded.response.json() as Record<string, unknown>;
  assert.equal(body.code, "PROJECT_MUTATION_BUSY");
  assert.equal(body.action, "stop_keep_checkpoint");
  assert.match(String(body.error), /Stop & keep checkpoint/);
  clearProducerRun(producerDir);
  const after = guardProjectMutation({
    projectRoot: root,
    producerDir,
    operation: "saving timeline changes",
  });
  assert.ok(after.lease);
  after.lease.release();
}

function atomicReplacement(root: string): void {
  const destination = path.join(root, "authority.json");
  writeFileSync(destination, "old\n");
  atomicWriteFileSync(destination, "new\n");
  assert.equal(readFileSync(destination, "utf8"), "new\n");
  assert.deepEqual(
    readdirSync(root).filter((name) => name.includes("authority.json.") && name.endsWith(".tmp")),
    [],
  );
}

async function main(): Promise<void> {
  const tmp = mkdtempSync(path.join(os.tmpdir(), "sniper-project-mutation-"));
  try {
    leaseSerializes(path.join(tmp, "lease"));
    const runRoot = path.join(tmp, "active");
    mkdirSync(runRoot);
    await activeRunIsActionable(runRoot);
    atomicReplacement(tmp);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
}

void main()
  .then(() => console.log("project-mutation-lease.test.ts: all assertions passed"))
  .catch((error) => { console.error(error); process.exitCode = 1; });
