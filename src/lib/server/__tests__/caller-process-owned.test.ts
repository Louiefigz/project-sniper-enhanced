import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { withCallerProcessDeadline } from "../caller-process-deadline";
import { CutPreviewProcessError, runCutPreviewProcess } from "@/app/api/producer/auto-edit/cut-preview-process";
import { compileCompatibilityProjection } from "@/app/api/producer/auto-edit/compatibility-timeline-projection";
import { canonicalJsonSha256 } from "../auto-edit-hash";

const command = { command: process.execPath, args: ["-e", "console.log(process.pid); setTimeout(()=>{},10000)"],
  cwd: process.cwd(), env: { NODE_ENV: "test" as const }, timeoutMs: 5000 };
const plan = { planVersion: 1, target: { mode: "longform", fps: 30, width: 1920, height: 1080 },
  cutTrack: [{ sourceId: "TEST-only", start: 0, end: 3, speed: 1 }], cutDecisions: { schemaVersion: 1, removals: [] } };

test("original malformed timeout is rejected before caller capping", async () => {
  await withCallerProcessDeadline({ remainingMs: () => 100, maxChildMs: 50 }, async () => {
    for (const timeoutMs of [0, 100.5, 900001, NaN]) {
      assert.throws(() => runCutPreviewProcess({ ...command, timeoutMs }), /bounded POSIX/);
    }
  });
});

test("actual owned inert child is capped and exact group is absent before timeout returns", async () => {
  const began = performance.now();
  await assert.rejects(withCallerProcessDeadline({ remainingMs: () => 5000, maxChildMs: 150 }, async () => {
    await runCutPreviewProcess(command);
  }), (error: unknown) => {
    assert.ok(error instanceof CutPreviewProcessError);
    assert.equal(error.details.timedOut, true); assert.equal(error.details.groupStopped, true);
    assert.equal(error.details.forcedStop, true);
    const pid = Number(error.details.stdout.trim()); assert.ok(pid > 0);
    assert.throws(() => process.kill(-pid, 0), (failure: NodeJS.ErrnoException) => failure.code === "ESRCH");
    return true;
  });
  assert.ok(performance.now() - began < 3000);
});

test("active-scope real Python projection retains original identity without media", async () => {
  const bytes = Buffer.from(JSON.stringify(plan)), hash = canonicalJsonSha256(plan);
  const actual = await withCallerProcessDeadline({ remainingMs: () => 10000, maxChildMs: 10000 },
    () => compileCompatibilityProjection(bytes, hash));
  assert.equal(actual.approvedCutPlanHash, hash); assert.equal(actual.timelineMap.outputDuration, 3);
  assert.equal(actual.timelineMap.segments[0].source_id, "TEST-only");
});

test("unknown projection group observation retains exact private input and original error details", async (context) => {
  const before = new Set(readdirSync(os.tmpdir())), realKill = process.kill.bind(process);
  const denied = context.mock.method(process, "kill", (pid: number, signal?: number | NodeJS.Signals) => {
    if (pid < 0 && signal === 0) throw Object.assign(new Error("TEST observation denied"), { code: "EPERM" });
    return realKill(pid, signal);
  });
  let retained: string | undefined;
  try {
    await assert.rejects(withCallerProcessDeadline({ remainingMs: () => 10000, maxChildMs: 10000 },
      () => compileCompatibilityProjection(Buffer.from(JSON.stringify(plan)), canonicalJsonSha256(plan))), (error: unknown) => {
      assert.ok(error instanceof CutPreviewProcessError); assert.equal(error.details.groupStopped, false);
      retained = (error as CutPreviewProcessError & { retainedProjectionDirectory: string }).retainedProjectionDirectory;
      assert.ok(retained && !before.has(path.basename(retained)));
      assert.equal(existsSync(retained), true);
      assert.deepEqual(JSON.parse(readFileSync(path.join(retained, "edit_plan.json"), "utf8")), plan);
      return true;
    });
  } finally { denied.mock.restore(); }
  // Deliberately retain uncertainty evidence. This test does not reinterpret EPERM as absence.
  context.diagnostic(`TEST unknown-observation evidence retained: ${retained}`);
});

test("scope expiry before projection never creates a private directory", async () => {
  const before = readdirSync(os.tmpdir()).filter((name) => name.startsWith("sniper-compat-projection-"));
  await assert.rejects(withCallerProcessDeadline({ remainingMs: () => 0, maxChildMs: 100 },
    () => compileCompatibilityProjection(Buffer.from(JSON.stringify(plan)), canonicalJsonSha256(plan))), /expired/);
  assert.deepEqual(readdirSync(os.tmpdir()).filter((name) => name.startsWith("sniper-compat-projection-")), before);
});
