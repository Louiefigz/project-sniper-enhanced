/** Actual source2 admission and original TS metadata only; no activation, tools, native or approval. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { holdBodyControllerSources, assertBodyControllerSourcesMetadata } from "../guided-body-controller-sources";
import { BODY_DEADLINE_POLICY } from "../guided-body-deadline";
import { GUIDED_SOURCE_COLOR_TS_FILES } from "../guided-source-color-cleanup-pins";
import { bodyControllerSourcesFixture, replaceControllerFixtureFile } from "./_guided-body-controller-sources-fixture";

test("genuine source2 pins current and original 0644 files once; repeated checks retain metadata without reads", async t => {
  const f = await bodyControllerSourcesFixture(t);
  await f.run(async ({ admission, context }) => {
    const held = holdBodyControllerSources({ admission, remainingMs: context.budget.remainingMs });
    assert.deepEqual(held.files.map(row => row.path), GUIDED_SOURCE_COLOR_TS_FILES);
    assert.equal(held.pipelineDigest, admission.before.job.ctx.pipeline!.digest);
    assert(Object.isFrozen(held)); assert(Object.isFrozen(held.files)); assert(held.files.every(Object.isFrozen));
    assert.equal(fs.lstatSync(f.copied).mode & 0o777, 0o644);
    const read = t.mock.method(fs, "readSync", () => { throw new Error("TEST repeated source read"); });
    held.assertMetadata(); assertBodyControllerSourcesMetadata(held, admission); assert.equal(read.mock.callCount(), 0);
    read.mock.restore(); held.check();
    assert(context.budget.remainingMs() > 25 * 60_000);
  });
});

for (const fault of ["missing", "current-differs", "lock-differs"] as const) {
  test(`original ${fault} source qualification refuses without input or activation publication`, async t => {
    const f = await bodyControllerSourcesFixture(t, fault);
    await f.run(async ({ admission, context }) => {
      assert.throws(() => holdBodyControllerSources({ admission, remainingMs: context.budget.remainingMs }));
      assert(!fs.existsSync(path.join(admission.execution, "body-media-input.json")));
      assert(!fs.existsSync(path.join(admission.execution, "body-execution-activation.json")));
    });
  });
}

test("copied admission and original version downgrade refuse before caller callbacks", async t => {
  const f = await bodyControllerSourcesFixture(t);
  await f.run(async ({ admission }) => {
    let calls = 0; const remainingMs = () => { calls++; return 1000; };
    assert.throws(() => holdBodyControllerSources({ admission: { ...admission }, remainingMs }), /actual original/);
    admission.input.row.schemaVersion = 1; admission.input.input.schemaVersion = 1;
    assert.throws(() => holdBodyControllerSources({ admission, remainingMs }), /changed/);
    assert.equal(calls, 0);
  });
});

test("the first monotonic sample cannot rebaseline original admission bytes or caller identity", async t => {
  const f = await bodyControllerSourcesFixture(t);
  await f.run(async ({ admission, context }) => {
    const input = { admission, remainingMs: context.budget.remainingMs }, actual = performance.now.bind(performance);
    let sampled = false;
    t.mock.method(performance, "now", () => {
      if (!sampled) { sampled = true; admission.current.bytes[0] ^= 1; input.remainingMs = () => 1000; }
      return actual();
    });
    assert.throws(() => holdBodyControllerSources(input), /original caller identity/); assert(sampled);
  });
});

for (const role of ["copy", "lock"] as const) {
  test(`first original remaining callback cannot substitute a captured ${role}`, async t => {
    const f = await bodyControllerSourcesFixture(t);
    await f.run(async ({ admission, context }) => {
      let calls = 0;
      assert.throws(() => holdBodyControllerSources({ admission, remainingMs: () => {
        const value = context.budget.remainingMs(); if (++calls === 1) replaceControllerFixtureFile(f, role); return value;
      } }), /original source file changed/);
      assert.equal(calls, 1);
    });
  });
}

test("late original callback cannot substitute a captured source and invalidate-then-revive", async t => {
  const f = await bodyControllerSourcesFixture(t);
  await f.run(async ({ admission, context }) => {
    let armed = false;
    const held = holdBodyControllerSources({ admission, remainingMs: () => {
      const value = context.budget.remainingMs(); if (armed) replaceControllerFixtureFile(f, "copy"); return value;
    } });
    armed = true; assert.throws(() => held.check(), /original source file changed/);
    assert.throws(() => held.assertMetadata(), /invalid/);
  });
});

test("private holder copies, original callback substitution and pipeline object substitution refuse", async t => {
  const f = await bodyControllerSourcesFixture(t);
  await f.run(async ({ admission, context }) => {
    const input = { admission, remainingMs: context.budget.remainingMs }, held = holdBodyControllerSources(input);
    assert.throws(() => assertBodyControllerSourcesMetadata({ ...held }), /actual original private/);
    assert.throws(() => assertBodyControllerSourcesMetadata(held, { ...admission }), /another original/);
    input.remainingMs = () => 1000; assert.throws(() => held.check(), /caller identity/);
    const next = holdBodyControllerSources({ admission, remainingMs: context.budget.remainingMs });
    admission.before.job.ctx.pipeline = structuredClone(admission.before.job.ctx.pipeline);
    assert.throws(() => next.assertMetadata(), /pipeline identity/);
  });
});

test("final source-file sweep is followed by original ancestry recheck", async t => {
  const f = await bodyControllerSourcesFixture(t);
  await f.run(async ({ admission, context }) => {
    const held = holdBodyControllerSources({ admission, remainingMs: context.budget.remainingMs });
    const original = fs.lstatSync, parent = path.dirname(f.copied); let switched = false;
    const stat = t.mock.method(fs, "lstatSync", ((file: fs.PathLike, options?: { bigint?: boolean }) => {
      const value = original(file, options as { bigint: true });
      if (String(file) === f.lock) switched = true;
      if (switched && String(file) === parent) return Object.assign(Object.create(Object.getPrototypeOf(value)), value, { ino: value.ino + BigInt(1) });
      return value;
    }) as typeof fs.lstatSync);
    assert.throws(() => held.assertMetadata(), /source parent/); assert(switched); stat.mock.restore();
  });
});

test("recursive original caller check permanently invalidates its private holder", async t => {
  const f = await bodyControllerSourcesFixture(t);
  await f.run(async ({ admission, context }) => {
    let replay: (() => void) | undefined;
    const held = holdBodyControllerSources({ admission, remainingMs: () => { replay?.(); return context.budget.remainingMs(); } });
    replay = held.check; assert.throws(() => held.check(), /reenter/);
    replay = undefined; assert.throws(() => held.assertMetadata(), /invalid/);
    const failure = new Error("TEST original caller failure"); let throwNext = false;
    const next = holdBodyControllerSources({ admission, remainingMs: () => {
      if (throwNext) throw failure; return context.budget.remainingMs();
    } });
    throwNext = true; assert.throws(() => next.check(), error => error === failure);
    assert.throws(() => next.assertMetadata(), /invalid/);
  });
});

test("original 55-minute floor charges capture and callback time, honors smaller samples, and cannot regain allowance", async t => {
  const f = await bodyControllerSourcesFixture(t);
  await f.run(async ({ admission }) => {
    const actual = performance.now.bind(performance); let offset = 0, allowance = BODY_DEADLINE_POLICY.wholeAttemptMs;
    t.mock.method(performance, "now", () => actual() + offset);
    const held = holdBodyControllerSources({ admission, remainingMs: () => allowance });
    offset += 26 * 60_000; held.assertMetadata();
    allowance = 100; held.check(); allowance = BODY_DEADLINE_POLICY.wholeAttemptMs;
    offset += 101; assert.throws(() => held.check(), /expired/); assert.throws(() => held.assertMetadata(), /invalid/);
  });
});

test("first callback overrun and later monotonic rollback cannot mint or recover a hold", async t => {
  const f = await bodyControllerSourcesFixture(t);
  await f.run(async ({ admission }) => {
    const actual = performance.now.bind(performance); let offset = 0;
    t.mock.method(performance, "now", () => actual() + offset);
    assert.throws(() => holdBodyControllerSources({ admission, remainingMs: () => { offset += 1001; return 1000; } }), /expired/);
    const held = holdBodyControllerSources({ admission, remainingMs: () => 60_000 });
    offset -= 1000; assert.throws(() => held.assertMetadata(), /backwards/);
    offset += 2000; assert.throws(() => held.assertMetadata(), /invalid/);
  });
});

test("nonfinite, expired and above-body-ceiling original samples are rejected", async t => {
  const f = await bodyControllerSourcesFixture(t);
  await f.run(async ({ admission }) => {
    for (const value of [0, -1, NaN, Infinity, BODY_DEADLINE_POLICY.wholeAttemptMs + 1]) {
      assert.throws(() => holdBodyControllerSources({ admission, remainingMs: () => value }));
    }
  });
});
