import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import type { ChildProcess } from "node:child_process";
import { test, type TestContext } from "node:test";
import { trackProcessTree } from "@/app/api/_lib/child-process-lifecycle";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { assertBootstrapQuiescent, BootstrapCleanupError, withBootstrapProcessScope } from "../guided-project-bootstrap-observer";
import { bootstrapFailureCleanup } from "../guided-project-bootstrap-worker";

function child(t: TestContext, pid: number): ChildProcess {
  const value = Object.assign(new EventEmitter(), { pid }) as ChildProcess;
  t.after(() => value.emit("close", 0)); return value;
}
function absent(): never { throw Object.assign(new Error("TEST absent"), { code: "ESRCH" }); }

test("normal sequential stage drains reopen and final scope observes every registered group", async (t) => {
  const seen: number[] = [];
  t.mock.method(process, "kill", (pid: number) => { seen.push(pid); return absent(); });
  await withBootstrapProcessScope(async () => {
    for (const id of [91001, 91002, 91003]) {
      trackProcessTree(child(t, id)); await assertBootstrapQuiescent();
    }
    await assertBootstrapQuiescent(true);
  }, () => assert.fail("no late registration"));
  assert.deepEqual(seen, [-91001, -91002, -91003]);
});

test("microtask registration during settlement poisons PAUSE and observes the late group", async (t) => {
  const late = child(t, 91002), seen: number[] = []; let recorded = 0;
  t.mock.method(process, "kill", (pid: number) => {
    seen.push(pid);
    if (pid === -91001) queueMicrotask(() => trackProcessTree(late));
    return absent();
  });
  await assert.rejects(withBootstrapProcessScope(async () => { trackProcessTree(child(t, 91001)); },
    () => { recorded++; }), BootstrapCleanupError);
  assert.deepEqual(seen, [-91001, -91002]); assert.equal(recorded, 1);
});

test("registration after final seal synchronously revokes pause even if the group is already absent", async (t) => {
  t.mock.method(process, "kill", absent); let recorded = 0;
  await assert.rejects(withBootstrapProcessScope(async () => {
    await assertBootstrapQuiescent(true);
    trackProcessTree(child(t, 91003));
    assert.equal(recorded, 1);
    await assertBootstrapQuiescent(true);
  }, () => { recorded++; }), BootstrapCleanupError);
});

test("survivor is stopped but rejected; unavailable observation stays cleanup unknown", async (t) => {
  const signals: unknown[] = []; let alive = true;
  t.mock.method(process, "kill", (_pid: number, signal: unknown) => {
    signals.push(signal);
    if (signal === "SIGTERM") alive = false;
    if (!alive && signal === 0) return absent();
    return true;
  });
  await assert.rejects(withBootstrapProcessScope(async () => { trackProcessTree(child(t, 91001)); }, () => {}),
    (error: unknown) => error instanceof BootstrapCleanupError && error.observation.clean && error.observation.forced);
  assert.ok(signals.includes("SIGTERM"));
  t.mock.method(process, "kill", () => { throw Object.assign(new Error("TEST unknown"), { code: "EPERM" }); });
  await assert.rejects(withBootstrapProcessScope(async () => { trackProcessTree(child(t, 91002)); }, () => {}),
    (error: unknown) => error instanceof BootstrapCleanupError && !error.observation.clean);
});

test("outer group forced-stop never becomes nested cleanup proof, including wrapped failure", () => {
  const error = new CutPreviewProcessError("TEST forced", { timedOut: true, groupStopped: true,
    forcedStop: true, stdout: "TEST private output", stderr: "TEST private diagnostic" });
  assert.deepEqual(bootstrapFailureCleanup(error), { verified: false, forcedStop: true });
  assert.deepEqual(bootstrapFailureCleanup(new BootstrapCleanupError("scope", { clean: true, forced: true }, error)),
    { verified: false, forcedStop: true });
});

test("no ambient scope and nested scope cannot authorize a quiescence fact", async () => {
  await assert.rejects(assertBootstrapQuiescent(), /lacks/);
  await assert.rejects(withBootstrapProcessScope(() => withBootstrapProcessScope(async () => {}, () => {}), () => {}), /Nested/);
});
