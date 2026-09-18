import assert from "node:assert/strict";
import { createHash } from "node:crypto";
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
import {
  QC_PROMOTION_RECONCILIATION_FILE,
  SURGICAL_RECONCILIATION_CANDIDATE_FILE,
  SURGICAL_RECONCILIATION_FILE,
} from "../ask-editor-reconciliation";

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

async function reconciliationBlocksEveryWriter(root: string): Promise<void> {
  const producerDir = path.join(root, "producer");
  mkdirSync(producerDir);
  const candidatePath = path.join(
    producerDir, SURGICAL_RECONCILIATION_CANDIDATE_FILE,
  );
  const candidate = Buffer.from('{"candidate":true}\n');
  writeFileSync(candidatePath, candidate);
  writeFileSync(path.join(producerDir, SURGICAL_RECONCILIATION_FILE), JSON.stringify({
    schemaVersion: 1,
    status: "manual-reconciliation-required",
    promotedChildHash: createHash("sha256").update(candidate).digest("hex"),
    retainedCandidatePath: candidatePath,
  }));
  const blocked = guardProjectMutation({
    projectRoot: root,
    producerDir,
    operation: "saving timeline changes",
  });
  assert.ok(blocked.response);
  const body = await blocked.response.json() as Record<string, unknown>;
  assert.equal(body.code, "PROJECT_RECONCILIATION_REQUIRED");
  assert.equal(body.retryable, false);
  rmSync(candidatePath);
  rmSync(path.join(producerDir, SURGICAL_RECONCILIATION_FILE));
  const qcReconciliation = path.join(
    producerDir, QC_PROMOTION_RECONCILIATION_FILE);
  writeFileSync(qcReconciliation, "{}\n");
  const qcBlocked = guardProjectMutation({
    projectRoot: root,
    producerDir,
    operation: "rendering another candidate",
  });
  assert.ok(qcBlocked.response);
  const qcBody = await qcBlocked.response.json() as Record<string, unknown>;
  assert.equal(qcBody.code, "PROJECT_RECONCILIATION_REQUIRED");
  assert.equal(qcBody.retryable, false);
  rmSync(qcReconciliation);
  const clear = guardProjectMutation({
    projectRoot: root,
    producerDir,
    operation: "saving timeline changes",
  });
  assert.ok(clear.lease);
  clear.lease.release();
}

async function main(): Promise<void> {
  const tmp = mkdtempSync(path.join(os.tmpdir(), "sniper-project-mutation-"));
  try {
    leaseSerializes(path.join(tmp, "lease"));
    const runRoot = path.join(tmp, "active");
    mkdirSync(runRoot);
    await activeRunIsActionable(runRoot);
    const reconcileRoot = path.join(tmp, "reconcile");
    mkdirSync(reconcileRoot);
    await reconciliationBlocksEveryWriter(reconcileRoot);
    atomicReplacement(tmp);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
}

void main()
  .then(() => console.log("project-mutation-lease.test.ts: all assertions passed"))
  .catch((error) => { console.error(error); process.exitCode = 1; });
