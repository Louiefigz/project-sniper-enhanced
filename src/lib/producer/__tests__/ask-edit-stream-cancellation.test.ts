import assert from "node:assert/strict";
import {
  assertStreamActive,
  createStreamCancellationFence,
  finishStream,
} from "../../../app/api/producer/ai-edit/stream-cancellation";

async function main(): Promise<void> {
  const fence = createStreamCancellationFence();
  let released = false;
  void fence.wait.then(() => { released = true; });
  fence.cancel();
  await Promise.resolve();
  assert.equal(fence.signal.aborted, true);
  assert.equal(fence.isCancelled(), true);
  assert.equal(released, false, "cancellation alone must not release the lease");
  assert.throws(() => assertStreamActive(fence.signal), /cancelled/);
  fence.settle();
  await fence.wait;
  assert.equal(released, true);
  fence.settle();

  const cleanupFence = createStreamCancellationFence();
  cleanupFence.cancel();
  const actions: string[] = [];
  const failure = finishStream(
    cleanupFence,
    () => { actions.push("release"); },
    () => { actions.push("close"); },
    () => {
      actions.push("rollback");
      throw new Error("rollback failed");
    },
  );
  await cleanupFence.wait;
  assert.match(String(failure), /rollback failed/);
  assert.deepEqual(actions, ["rollback", "release", "close"]);

  const releaseFence = createStreamCancellationFence();
  releaseFence.cancel();
  let closed = false;
  const releaseFailure = finishStream(
    releaseFence,
    () => { throw new Error("release failed"); },
    () => { closed = true; },
  );
  await releaseFence.wait;
  assert.match(String(releaseFailure), /release failed/);
  assert.equal(closed, true);
}

void main()
  .then(() => console.log("ask-edit-stream-cancellation.test.ts: passed"))
  .catch((error) => { console.error(error); process.exitCode = 1; });
