/** Actual source2 writer and activation CAS; only native/readiness metadata are TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { writeGuidedBodyMediaInput } from "../guided-body-input";
import { activateFreshGuidedBody, readGuidedBodyActivation } from "../guided-body-activation";
import { assertBodyControllerInvocation, assertBodyControllerActivationMetadata } from "../guided-body-controller-handoff";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { autoEditJobPath } from "../auto-edit-job-persistence";
import { bodyControllerSourcesFixture, replaceControllerFixtureFile } from "./_guided-body-controller-sources-fixture";

test("source2 writer binds actual return values and rejects copied or changed invocation", async t => {
  const f = await bodyControllerSourcesFixture(t);
  await f.run(async ({ write }) => {
    const invocation = write(); assertBodyControllerInvocation(invocation);
    assert.throws(() => assertBodyControllerInvocation({ ...invocation }), /actual original invocation/);
    invocation.input.schemaVersion = 1;
    assert.throws(() => assertBodyControllerInvocation(invocation), /original handoff values changed/);
  });
});

test("source2 writer refuses a missing original budget before guard or publication", async t => {
  const f = await bodyControllerSourcesFixture(t);
  await f.run(async ({ admission }) => {
    let calls = 0;
    assert.throws(() => writeGuidedBodyMediaInput(admission, () => { calls++; }), /original remaining budget/);
    assert.equal(calls, 0); assert.equal(fs.existsSync(path.join(admission.execution, "body-media-input.json")), false);
  });
});

test("actual post-CAS activation retains code checks; status and copies do not mint live handoff", async t => {
  const f = await bodyControllerSourcesFixture(t);
  await f.run(async ({ context }) => {
    const actual = activateFreshGuidedBody(context); assertBodyControllerActivationMetadata(actual);
    const historical = readGuidedBodyActivation(context.dir);
    assert.equal(historical.activationHash, actual.activationHash);
    assert.throws(() => assertBodyControllerActivationMetadata(historical), /actual original live return/);
    assert.throws(() => assertBodyControllerActivationMetadata({ ...actual }), /actual original live return/);
    replaceControllerFixtureFile(f, "copy");
    assert.throws(() => assertBodyControllerActivationMetadata(actual), /original source file changed/);
    assert.equal(readGuidedBodyActivation(context.dir).activationHash, actual.activationHash,
      "historical status does not require equivalence with current controller sources");
  });
});

test("source2 current code changing after writer blocks activation CAS and preserves private evidence", async t => {
  const f = await bodyControllerSourcesFixture(t);
  await f.run(async ({ admission, context }) => {
    const mkdir = fs.mkdirSync, output = path.join(admission.execution, "body-media-output"); let changed = false;
    const hook = t.mock.method(fs, "mkdirSync", ((file: fs.PathLike, options?: unknown) => {
      const result = mkdir(file, options as fs.MakeDirectoryOptions);
      if (!changed && String(file) === output) { changed = true; replaceControllerFixtureFile(f, "copy"); }
      return result;
    }) as typeof fs.mkdirSync);
    try { assert.throws(() => activateFreshGuidedBody(context), /original source file changed/); assert(changed); }
    finally { hook.mock.restore(); }
    assert.equal(observeHumanCutJob(context.dir).sha256, admission.current.sha256);
    assert(fs.existsSync(path.join(admission.execution, "body-media-input.json")));
    assert.equal(observeHumanCutJob(context.dir).job.guidedHandoffV2!.bodyActivationHash, undefined);
  });
});

test("source2 code mutation at actual activation CAS cannot return successful live handoff", async t => {
  const f = await bodyControllerSourcesFixture(t);
  await f.run(async ({ context }) => {
    const rename = fs.renameSync, journal = autoEditJobPath(context.dir); let changed = false;
    const hook = t.mock.method(fs, "renameSync", (from: fs.PathLike, to: fs.PathLike) => {
      rename(from, to);
      if (!changed && String(to) === journal) { changed = true; replaceControllerFixtureFile(f, "copy"); }
    });
    try { assert.throws(() => activateFreshGuidedBody(context), /original source file changed/); assert(changed); }
    finally { hook.mock.restore(); }
    assert(observeHumanCutJob(context.dir).job.guidedHandoffV2!.bodyActivationHash,
      "a completed CAS is retained, never silently rolled back or replayed after a failed tail");
  });
});
