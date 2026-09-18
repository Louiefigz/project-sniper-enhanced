import assert from "node:assert/strict";
import { AsyncResource } from "node:async_hooks";
import { test, type TestContext } from "node:test";
import { freshJob } from "../auto-edit-job-builders";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { AUTHORED_PREPARATION_LIMIT_MS as LIMIT, AuthoredPreparationDeadlineError,
  authoredPreparationRuntime as runtime, authoredPreparationRemainingMs as remaining,
  withAuthoredPreparationDeadline as within } from "../guided-project-preparation-deadline";

const START = Date.parse("2026-01-01T00:00:00.000Z");
interface Scheduled { callback: () => void; delay: number; cancelled: boolean }

/** Fake host clocks/timers only: never launch a provider, worker, media tool or signal. */
function clock(t: TestContext) {
  const value = { wall: START, mono: 100, timers: [] as Scheduled[] };
  t.mock.method(runtime, "wall", () => value.wall);
  t.mock.method(runtime, "monotonic", () => value.mono);
  t.mock.method(runtime, "schedule", (callback: () => void, delay: number) => {
    const timer = { callback: AsyncResource.bind(callback), delay, cancelled: false };
    value.timers.push(timer);
    return timer as unknown as ReturnType<typeof setTimeout>;
  });
  t.mock.method(runtime, "cancel", (timer: unknown) => { (timer as Scheduled).cancelled = true; });
  return value;
}

/** An in-memory TEST job; policy fields are metadata, not fabricated source or approval receipts. */
function job() {
  const ctx: AutoEditCtx = { dir: "/private/TEST-preparation", scope: "light", planPath: "/private/TEST-plan.json",
    manifestPath: "/private/TEST-manifest.json", transcriptsDir: "/private/TEST-transcripts",
    authoredCut: { schemaVersion: 1, policy: "source-brief-cut", requestHash: "a".repeat(64),
      initialPlanSha256: "b".repeat(64), transcriptDigest: "c".repeat(64), preparationStartedAt: new Date(START).toISOString() } };
  return freshJob({ ctx, token: "TEST-preparation", snapshots: 0 }, new Date(START).toISOString());
}

test("legacy work has no preparation timer or clock observation", async (t) => {
  const fake = clock(t), current = job(); delete current.ctx.authoredCut;
  t.mock.method(runtime, "wall", () => { throw new Error("legacy must not observe this clock"); });
  assert.equal(remaining(current.ctx), null);
  assert.equal(await within(current, () => assert.fail("legacy expiry"), async () => 7), 7);
  assert.equal(fake.timers.length, 0);
});

test("prelaunch time uses original wall only and has no configurable allowance", (t) => {
  const fake = clock(t), current = job(); fake.wall += 25_000; fake.mono = NaN;
  assert.equal(LIMIT, 7_200_000); assert.equal(remaining(current.ctx), LIMIT - 25_000);
  current.ctx.authoredCut = { ...current.ctx.authoredCut!, timeoutMs: LIMIT * 2 } as typeof current.ctx.authoredCut;
  assert.throws(() => remaining(current.ctx), /binding-invalid/);
});

test("expired or invalid entry starts neither work, scheduler nor expiration callback", async (t) => {
  const fake = clock(t), current = job(); let calls = 0;
  fake.wall = START + LIMIT;
  await assert.rejects(within(current, () => calls++, async () => calls++), /expired/);
  fake.wall = START;
  current.ctx.authoredCut!.preparationStartedAt = "not-a-clock";
  await assert.rejects(within(current, () => calls++, async () => calls++), /binding-invalid/);
  assert.equal(calls, 0); assert.equal(fake.timers.length, 0);
});

test("invalid and pre-origin wall readings reject without inventing free queue time", (t) => {
  const fake = clock(t), current = job();
  for (const wall of [START - 1, NaN, Infinity, START + 0.5]) {
    fake.wall = wall;
    assert.throws(() => remaining(current.ctx), /clock-invalid/);
  }
});

test("one scope includes queue, lease, phases and settlement without a renewed timer", async (t) => {
  const fake = clock(t), current = job(); fake.wall += 20_000;
  const result = await within(current, () => assert.fail("unexpected expiry"), async () => {
    assert.equal(fake.timers[0].delay, LIMIT - 20_000);
    fake.wall += 5_000; fake.mono += 7_000; // Simulated mutation-lease wait.
    assert.equal(remaining(structuredClone(current.ctx)), LIMIT - 27_000);
    await within(current, () => assert.fail("nested origin"), async () => {
      fake.wall += 2000; fake.mono += 3000;
      assert.equal(remaining(current.ctx), LIMIT - 30_000);
    });
    assert.equal(fake.timers.length, 1); assert.equal(fake.timers[0].cancelled, false);
    return "TEST awaiting operator";
  });
  assert.equal(result, "TEST awaiting operator"); assert.equal(fake.timers[0].cancelled, true);
});

test("stalled wall still charges monotonic time and floors the remaining child allowance", async (t) => {
  const fake = clock(t), current = job();
  await within(current, () => assert.fail("unexpected expiry"), async () => {
    fake.mono += 1234.25;
    assert.equal(remaining(current.ctx), LIMIT - 1235);
  });
});

test("wall and monotonic rollback each poison all later phases and request shutdown once", async (t) => {
  const fake = clock(t);
  for (const kind of ["wall", "mono"] as const) {
    fake.wall = START + 10; fake.mono = 100;
    const current = job(); let expired = 0;
    await assert.rejects(within(current, () => expired++, async () => {
      fake[kind]--;
      assert.throws(() => remaining(current.ctx), /clock-invalid/);
      fake.wall += 100; fake.mono += 100;
      assert.throws(() => remaining(current.ctx), /clock-invalid/);
    }), /clock-invalid/);
    assert.equal(expired, 1);
  }
});

test("wall-forward exhaustion fails before successful return even when timer delivery is delayed", async (t) => {
  const fake = clock(t), current = job(); let expired = 0;
  await assert.rejects(within(current, () => expired++, async () => {
    fake.wall += LIMIT;
    return "must not become PAUSE";
  }), (error: unknown) => error instanceof AuthoredPreparationDeadlineError && error.kind === "expired" && error.cleanup === "unknown");
  assert.equal(expired, 1); assert.equal(fake.timers[0].cancelled, true);
});

test("timer requests shutdown but cannot settle or clear while the callback remains live", async (t) => {
  const fake = clock(t), current = job(); let expired = 0, settled = false;
  let finish!: (value: string) => void;
  const pending = within(current, () => expired++, () => new Promise<string>(resolve => { finish = resolve; }));
  pending.then(() => { settled = true; }, () => { settled = true; });
  fake.wall += LIMIT; fake.mono += LIMIT; fake.timers[0].callback();
  await Promise.resolve();
  assert.equal(expired, 1); assert.equal(settled, false); assert.equal(fake.timers[0].cancelled, false);
  fake.wall += 5000; fake.mono += 5000; // Cleanup elapsed, never a work-clock extension.
  finish("TEST actual callback settled");
  await assert.rejects(pending, /PREPARATION expired.*cleanup remains unknown/);
  assert.equal(fake.timers[0].cancelled, true); assert.equal(expired, 1);
});

test("late ordinary errors retain deadline cause while timely ordinary errors stay unchanged", async (t) => {
  const fake = clock(t), current = job(), original = new Error("TEST ordinary failure"); let expired = 0;
  await assert.rejects(within(current, () => expired++, async () => { throw original; }), error => error === original);
  await assert.rejects(within(current, () => expired++, async () => {
    fake.mono += LIMIT; throw original;
  }), /expired/);
  assert.equal(expired, 1);
});

test("policy deletion, changed origin or different context cannot reopen the live scope", async (t) => {
  clock(t);
  for (const change of ["delete", "origin", "dir"]) {
    const current = job(); let expired = 0, nested = 0;
    await assert.rejects(within(current, () => expired++, async () => {
      const other = structuredClone(current);
      if (change === "delete") delete other.ctx.authoredCut;
      if (change === "origin") other.ctx.authoredCut!.preparationStartedAt = new Date(START - 1000).toISOString();
      if (change === "dir") other.ctx.dir += "-other";
      await within(other, () => assert.fail("fresh timer"), async () => nested++);
    }), /binding-invalid/);
    assert.equal(expired, 1); assert.equal(nested, 0);
  }
});

test("returned scope clears timer and stale callbacks cannot expire a successful pause", async (t) => {
  const fake = clock(t), current = job(); let expired = 0, oldGuard!: () => number | null;
  await within(current, () => expired++, async () => { oldGuard = AsyncResource.bind(() => remaining(current.ctx)); });
  fake.timers[0].callback();
  assert.equal(expired, 0); assert.equal(fake.timers[0].cancelled, true);
  assert.throws(oldGuard, /scope-closed/);
});

test("time consumed while arming is charged before any worker callback starts", async (t) => {
  const fake = clock(t), current = job(); let ran = 0, expired = 0;
  t.mock.method(runtime, "schedule", () => {
    fake.wall += LIMIT;
    const timer = { callback: () => {}, delay: LIMIT, cancelled: false }; fake.timers.push(timer);
    return timer as unknown as ReturnType<typeof setTimeout>;
  });
  await assert.rejects(within(current, () => expired++, async () => ran++), /expired/);
  assert.equal(ran, 0); assert.equal(expired, 1); assert.equal(fake.timers[0].cancelled, true);
});

test("shutdown callback failure stays unknown and cannot manufacture successful settlement", async (t) => {
  const fake = clock(t), current = job(); let finish!: () => void;
  const pending = within(current, () => { throw new Error("TEST stop failed"); }, () => new Promise<void>(resolve => { finish = resolve; }));
  fake.wall += LIMIT; fake.timers[0].callback(); finish();
  await assert.rejects(pending, (error: unknown) => error instanceof AuthoredPreparationDeadlineError
    && error.kind === "expired" && error.cleanup === "unknown" && error.shutdownError === "Error: TEST stop failed");
});
