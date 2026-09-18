import assert from "node:assert/strict";
import {
  ACTIVE_PROJECT_POLL_MS,
  IDLE_PROJECT_POLL_MS,
  activeProjectDirs,
  idleProjectDirs,
  projectStatusUrl,
} from "../project-status-polling";
import { SerialRequestQueue } from "../serial-request-queue";

interface Gate {
  resolve: () => void;
}

async function waitFor(check: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (check()) return;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  throw new Error("timed out waiting for polling assertion");
}

async function testSerialDeduplication(): Promise<void> {
  const calls: string[] = [];
  const completed: string[] = [];
  const gates = new Map<string, Gate>();
  let active = 0;
  let maxActive = 0;
  const queue = new SerialRequestQueue<string>({
    request: (key) => new Promise((resolve) => {
      calls.push(key);
      active += 1;
      maxActive = Math.max(maxActive, active);
      gates.set(key, { resolve: () => { active -= 1; resolve(key); } });
    }),
    onSuccess: (_key, value) => completed.push(value),
    onError: () => assert.fail("serial request unexpectedly failed"),
  });
  queue.enqueue(["alpha", "alpha", "beta", "beta"]);
  await waitFor(() => gates.has("alpha"));
  assert.deepEqual(calls, ["alpha"]);
  gates.get("alpha")!.resolve();
  await waitFor(() => gates.has("beta"));
  assert.deepEqual(calls, ["alpha", "beta"]);
  assert.equal(maxActive, 1, "poll requests must never overlap");
  gates.get("beta")!.resolve();
  await waitFor(() => completed.length === 2);
  assert.deepEqual(completed, ["alpha", "beta"]);
  queue.dispose();
}

async function testCancellationAbort(method: "pause" | "dispose"): Promise<void> {
  let aborted = 0;
  let errorCallbacks = 0;
  const queue = new SerialRequestQueue<void>({
    request: (_key, signal) => new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => {
        aborted += 1;
        reject(new DOMException("aborted", "AbortError"));
      }, { once: true });
    }),
    onSuccess: () => assert.fail("aborted request unexpectedly succeeded"),
    onError: () => { errorCallbacks += 1; },
  });
  queue.enqueue(["visible-project"]);
  await new Promise((resolve) => setTimeout(resolve, 0));
  queue[method]();
  await waitFor(() => aborted === 1);
  assert.equal(errorCallbacks, 0, "intentional polling aborts stay silent");
  queue.dispose();
}

async function testHiddenRunGuard(): Promise<void> {
  let visible = false;
  let calls = 0;
  const queue = new SerialRequestQueue<void>({
    request: async () => { calls += 1; },
    shouldRun: () => visible,
    onSuccess: () => {},
    onError: () => assert.fail("guarded request unexpectedly failed"),
  });
  queue.enqueue(["hidden-project"]);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(calls, 0, "hidden tabs must not start status requests");
  visible = true;
  queue.enqueue(["visible-project"]);
  await waitFor(() => calls === 1);
  queue.dispose();
}

function testActiveSelection(): void {
  const dirs = ["running", "candidate-qc", "finished", "unknown"];
  const entries = {
    running: { status: { run: { status: "running" } } },
    "candidate-qc": {
      status: {
        run: null,
        palmier: { candidateQc: { active: true } },
      },
    },
    finished: {
      status: {
        run: { status: "completed" },
        palmier: { candidateQc: { active: false } },
      },
    },
  };
  const active = activeProjectDirs(dirs, entries);
  assert.deepEqual(active, ["running", "candidate-qc"]);
  assert.deepEqual(idleProjectDirs(dirs, active), ["finished", "unknown"],
    "active projects must never also enter the slow polling lane");
  assert.equal(
    projectStatusUrl("/tmp/project with spaces", false),
    "/api/producer/project-status?dir=%2Ftmp%2Fproject%20with%20spaces&recover=0",
  );
  assert.match(projectStatusUrl("/tmp/running", true), /recover=1$/);
  assert.ok(ACTIVE_PROJECT_POLL_MS < IDLE_PROJECT_POLL_MS);
}

async function main(): Promise<void> {
  await testSerialDeduplication();
  await testCancellationAbort("pause");
  await testCancellationAbort("dispose");
  await testHiddenRunGuard();
  testActiveSelection();
  console.log("polling-control.test.ts: all assertions passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
