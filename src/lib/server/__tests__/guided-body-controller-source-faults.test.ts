/** Original controller capture faults over genuine admission and explicit TEMP code copies; no native execution. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { holdBodyControllerSources, assertBodyControllerSourcesMetadata } from "../guided-body-controller-sources";
import { activateFreshGuidedBody } from "../guided-body-activation";
import { assertBodyClaimSourceColorMetadata } from "../guided-body-lineage";
import { bodyControllerSourcesFixture, replaceControllerFixtureFile } from "./_guided-body-controller-sources-fixture";

test("original caller identity is captured before the first clock or lineage metadata callback", async t => {
  const f = await bodyControllerSourcesFixture(t);
  await f.run(async ({ admission, context }) => {
    for (const mode of ["clock", "lineage"] as const) {
      let changed = false, originalCalls = 0, replacementCalls = 0;
      const input = { admission, remainingMs: () => { originalCalls++; return context.budget.remainingMs(); } };
      const replaceCaller = () => {
        if (changed) return;
        changed = true; input.remainingMs = () => { replacementCalls++; return 3_300_000; };
      };
      const now = performance.now.bind(performance), stat = fs.lstatSync;
      const journal = path.join(admission.before.job.ctx.dir, ".sniper-auto-edit-job.json");
      const clockHook = t.mock.method(performance, "now", () => {
        const value = now(); if (mode === "clock") replaceCaller(); return value;
      });
      const metadataHook = t.mock.method(fs, "lstatSync", ((file: fs.PathLike, options?: { bigint?: boolean }) => {
        const value = stat(file, options as { bigint: true });
        if (mode === "lineage" && String(file) === journal) replaceCaller();
        return value;
      }) as typeof fs.lstatSync);
      try {
        assert.throws(() => holdBodyControllerSources(input), /original caller identity/);
        assert(changed); assert.equal(originalCalls, 0); assert.equal(replacementCalls, 0);
      } finally { metadataHook.mock.restore(); clockHook.mock.restore(); }
    }
  });
});

test("original code metadata remains usable after actual activation CAS without reviving stale admission", async t => {
  const f = await bodyControllerSourcesFixture(t);
  await f.run(async ({ admission, context }) => {
    let calls = 0;
    const held = holdBodyControllerSources({ admission, remainingMs: () => { calls++; return context.budget.remainingMs(); } });
    const activated = activateFreshGuidedBody(context);
    assert.notEqual(activated.current.sha256, admission.current.sha256);
    assert.throws(() => assertBodyClaimSourceColorMetadata(admission), /journal|identity|changed/);
    const before = calls;
    held.assertMetadata(); assertBodyControllerSourcesMetadata(held, admission);
    assert.equal(calls, before, "metadata does not invoke or renew the original caller budget");
    held.check(); assert.equal(calls, before + 1);
    assert.equal(held.scope, "original-source2-controller-source-bytes-not-native-or-launch-authority");
  });
});

test("final source canonical-path IO cannot hide a same-byte original snapshot replacement", async t => {
  const f = await bodyControllerSourcesFixture(t);
  await f.run(async ({ admission, context }) => {
    const held = holdBodyControllerSources({ admission, remainingMs: context.budget.remainingMs });
    const original = fs.realpathSync; let changed = false;
    const hook = t.mock.method(fs, "realpathSync", ((file: fs.PathLike, options?: unknown) => {
      const value = original(file, options as undefined);
      if (!changed && String(file) === f.copied) {
        changed = true; replaceControllerFixtureFile(f, "copy");
      }
      return value;
    }) as typeof fs.realpathSync);
    try { assert.throws(() => held.assertMetadata(), /original source file changed/); assert(changed); }
    finally { hook.mock.restore(); }
  });
});
