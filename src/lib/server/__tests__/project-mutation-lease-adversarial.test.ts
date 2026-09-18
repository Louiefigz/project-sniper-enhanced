import assert from "node:assert/strict";
import {
  existsSync,
  linkSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { guardProjectMutation } from
  "../../../app/api/_lib/project-mutation";
import { acquireProjectMutationLease } from "../project-mutation-lease";

async function staleLeaseFailsClosed(root: string): Promise<void> {
  mkdirSync(root);
  const lock = path.join(root, ".sniper-project-mutation.lock");
  mkdirSync(lock);
  writeFileSync(path.join(lock, "owner.json"), JSON.stringify({
    pid: 2_147_483_647,
    nonce: "dead-owner",
    operation: "interrupted mutation",
    createdAt: "2020-01-01T00:00:00.000Z",
  }));
  for (const operation of ["first contender", "second contender"]) {
    const blocked = acquireProjectMutationLease(root, operation);
    assert.equal(blocked.lease, undefined);
    assert.equal(blocked.conflict?.stale, true);
    assert.equal(readFileSync(path.join(lock, "owner.json"), "utf8").includes(
      "dead-owner",
    ), true, "stale recovery must never delete a pathname a successor could own");
  }
  const producerDir = path.join(root, "producer");
  mkdirSync(producerDir);
  const guarded = guardProjectMutation({
    projectRoot: root,
    producerDir,
    operation: "saving timeline changes",
  });
  assert.equal(guarded.response?.status, 409);
  const body = await guarded.response?.json() as Record<string, unknown>;
  assert.equal(body.code, "PROJECT_MUTATION_RECOVERY_REQUIRED");
  assert.equal(body.retryable, false);
}

function recoverExactDeadOwner(root: string): void {
  mkdirSync(root);
  const nonce = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa";
  const owner = path.join(root, `.sniper-project-mutation.owner-${nonce}.json`);
  const lock = path.join(root, ".sniper-project-mutation.lock");
  writeFileSync(owner, JSON.stringify({
    pid: 2_147_483_647,
    identity: { pid: 2_147_483_647, startToken: "linux-ticks:1" },
    nonce,
    operation: "crashed mutation",
    createdAt: "2020-01-01T00:00:00.000Z",
  }));
  linkSync(owner, lock);
  const recovered = acquireProjectMutationLease(root, "recovered mutation");
  assert.ok(recovered.lease);
  assert.equal(existsSync(owner), false);
  assert.equal(readFileSync(lock, "utf8").includes("recovered mutation"), true);
  recovered.lease.release();
  assert.equal(existsSync(lock), false);
}

function interruptedRecoveryClaimFailsClosed(root: string): void {
  mkdirSync(root);
  const nonce = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
  const owner = path.join(root, `.sniper-project-mutation.owner-${nonce}.json`);
  const lock = path.join(root, ".sniper-project-mutation.lock");
  const recovery = path.join(root, ".sniper-project-mutation.recovery");
  writeFileSync(owner, JSON.stringify({
    pid: 2_147_483_647,
    identity: { pid: 2_147_483_647, startToken: "linux-ticks:1" },
    nonce,
    operation: "interrupted stale recovery",
    createdAt: "2020-01-01T00:00:00.000Z",
  }));
  linkSync(owner, lock);
  linkSync(owner, recovery);
  const blocked = acquireProjectMutationLease(root, "second recovery");
  assert.equal(blocked.lease, undefined);
  assert.equal(existsSync(lock), true);
  assert.equal(existsSync(owner), true);
  assert.equal(existsSync(recovery), true);
}

function mismatchedOwnerInodeFailsClosed(root: string): void {
  mkdirSync(root);
  const nonce = "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb";
  const owner = path.join(root, `.sniper-project-mutation.owner-${nonce}.json`);
  const lock = path.join(root, ".sniper-project-mutation.lock");
  const record = JSON.stringify({
    pid: 2_147_483_647,
    identity: { pid: 2_147_483_647 },
    nonce,
    operation: "unverifiable mutation",
    createdAt: "2020-01-01T00:00:00.000Z",
  });
  writeFileSync(lock, record);
  writeFileSync(owner, record);
  const blocked = acquireProjectMutationLease(root, "must not reap");
  assert.equal(blocked.lease, undefined);
  assert.equal(blocked.conflict?.stale, true);
  assert.equal(existsSync(lock), true);
}

function malformedHardLinkedOwnerFailsClosed(root: string): void {
  const mutations = [
    (row: Record<string, unknown>) => { delete row.identity; },
    (row: Record<string, unknown>) => {
      row.identity = { pid: 123 };
    },
    (row: Record<string, unknown>) => {
      row.identity = { pid: 123, startToken: "unsupported:1" };
    },
    (row: Record<string, unknown>) => {
      row.identity = { pid: 123, unsupported: true };
    },
    (row: Record<string, unknown>) => {
      row.identity = { pid: 124 };
    },
  ];
  for (const [index, mutate] of mutations.entries()) {
    const candidate = path.join(root, String(index));
    mkdirSync(candidate, { recursive: true });
    const nonce = `cccccccc-cccc-4ccc-8ccc-ccccccccccc${index}`;
    const owner = path.join(
      candidate, `.sniper-project-mutation.owner-${nonce}.json`,
    );
    const lock = path.join(candidate, ".sniper-project-mutation.lock");
    const row: Record<string, unknown> = {
      pid: 123,
      identity: { pid: 123 },
      nonce,
      operation: "malformed mutation",
      createdAt: "2020-01-01T00:00:00.000Z",
    };
    mutate(row);
    writeFileSync(owner, JSON.stringify(row));
    linkSync(owner, lock);
    const blocked = acquireProjectMutationLease(candidate, "must fail closed");
    assert.equal(blocked.lease, undefined);
    assert.equal(existsSync(lock), true);
    assert.equal(existsSync(owner), true);
  }
}

function releasePreservesForeignSuccessor(root: string): void {
  mkdirSync(root);
  const acquired = acquireProjectMutationLease(root, "original mutation");
  assert.ok(acquired.lease);
  const lock = path.join(root, ".sniper-project-mutation.lock");
  unlinkSync(lock);
  writeFileSync(lock, "foreign successor\n");
  acquired.lease.release();
  assert.equal(readFileSync(lock, "utf8"), "foreign successor\n");
}

function invalidOperationCreatesNoOwner(root: string): void {
  mkdirSync(root);
  assert.throws(
    () => acquireProjectMutationLease(root, " "),
    /operation\/owner identity is invalid/u,
  );
  assert.deepEqual(readdirSync(root), []);
}

async function main(): Promise<void> {
  const tmp = mkdtempSync(path.join(os.tmpdir(), "sniper-mutation-adversarial-"));
  try {
    await staleLeaseFailsClosed(path.join(tmp, "stale-lease"));
    recoverExactDeadOwner(path.join(tmp, "recover-dead-owner"));
    interruptedRecoveryClaimFailsClosed(path.join(tmp, "interrupted-recovery"));
    mismatchedOwnerInodeFailsClosed(path.join(tmp, "mismatched-owner"));
    malformedHardLinkedOwnerFailsClosed(path.join(tmp, "malformed-owner"));
    releasePreservesForeignSuccessor(path.join(tmp, "foreign-successor"));
    invalidOperationCreatesNoOwner(path.join(tmp, "invalid-operation"));
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
}

void main()
  .then(() => console.log("project mutation lease adversarial tests passed"))
  .catch((error) => { console.error(error); process.exitCode = 1; });
