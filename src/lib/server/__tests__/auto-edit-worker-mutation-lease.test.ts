import assert from "node:assert/strict";
import { acquireAutoEditWorkerMutationLease } from
  "../auto-edit-worker-mutation-lease";
import type {
  ProjectMutationLease,
  ProjectMutationLeaseResult,
} from "../project-mutation-lease";

async function retriesLaunchHandoff(): Promise<void> {
  let attempts = 0;
  const waits: number[] = [];
  let released = false;
  const lease: ProjectMutationLease = {
    release: () => { released = true; },
  };
  const acquire = (): ProjectMutationLeaseResult => {
    attempts += 1;
    return attempts === 1
      ? { conflict: { operation: "starting Auto Edit", stale: false } }
      : { lease };
  };
  const observed = await acquireAutoEditWorkerMutationLease("/project", {
    acquire,
    wait: async (milliseconds) => { waits.push(milliseconds); },
    attempts: 2,
  });
  assert.equal(observed, lease);
  assert.deepEqual(waits, [25]);
  observed.release();
  assert.equal(released, true);
}

async function exhaustedHandoffIsNamed(): Promise<void> {
  let attempts = 0;
  await assert.rejects(
    acquireAutoEditWorkerMutationLease("/project", {
      acquire: () => {
        attempts += 1;
        return {
          conflict: {
            operation: "rendering another project update",
            stale: true,
          },
        };
      },
      wait: async () => {},
      attempts: 3,
    }),
    /held by rendering another project update \(stale owner requires recovery\)/,
  );
  assert.equal(attempts, 3);
}

async function main(): Promise<void> {
  await retriesLaunchHandoff();
  await exhaustedHandoffIsNamed();
  console.log("Auto Edit worker mutation lease tests passed");
}

void main();
