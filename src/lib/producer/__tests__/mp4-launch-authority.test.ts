import assert from "node:assert/strict";
import childProcess from "node:child_process";
import { syncBuiltinESMExports } from "node:module";
import { existsSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test, { mock } from "node:test";
import { NextRequest } from "next/server";
import {
  PALMIER_AUTHORITY_GUARD_TIMEOUT_MS,
  PalmierCanonicalError,
  runPalmierAuthorityGuard,
} from "../../../app/api/producer/ai-edit/palmier-canonical";
import { guardMp4LaunchAuthority } from "../../../app/api/producer/auto-edit/mp4-launch-authority";
import { POST } from "../../../app/api/producer/auto-edit/route";
import { guardAutoEditDeliveryForLaunch } from "../../../app/api/producer/auto-edit/launch";
import { fixture } from "./_auto-edit-pipeline-resume-fixture";

const STATE = "palmier.sync.json";
const AUTHORITY = "palmier.timeline-authority.json";
const CANDIDATE = "palmier.timeline-candidate.json";

async function withProject(run: (dir: string) => Promise<void>): Promise<void> {
  const dir = mkdtempSync(path.join(os.tmpdir(), "mp4-ownership-"));
  try { await run(dir); } finally { rmSync(dir, { recursive: true, force: true }); }
}

function bootstrap(dir: string, assetKind = "source") {
  const state = {
    schemaVersion: 4, ownership: "sniper", workspaceMode: "managed-draft",
    projectId: "palmier-project", projectPath: dir, latestTimelineId: "source-head",
    draft: { assetKind, authoritative: false },
  };
  const authority = {
    schemaVersion: 1, authority: "palmier", origin: "sniper-bootstrap",
    projectId: state.projectId, timelineId: state.latestTimelineId,
    fingerprint: "a".repeat(64), readbackCoverage: { complete: true },
  };
  writeRecord(dir, STATE, state);
  writeRecord(dir, AUTHORITY, authority);
  return { state, authority };
}

function writeRecord(dir: string, name: string, value: unknown): void {
  writeFileSync(path.join(dir, name), JSON.stringify(value));
}

function migrationConflict(error: unknown): boolean {
  return error instanceof PalmierCanonicalError && error.statusCode === 409
    && /Keep this project's Palmier workflow/.test(error.message)
    && /separate Sniper branch/.test(error.message)
    && /No in-place MP4 migration was started/.test(error.message);
}

test("new MP4 projects do not discover, open, or contact Palmier", async () => {
  await withProject(async (dir) => {
    const noPalmier = () => { throw new Error("Palmier must not run"); };
    await guardAutoEditDeliveryForLaunch({
      dir, scope: "light", planPath: path.join(dir, "edit_plan.json"),
      manifestPath: path.join(dir, "asset_manifest.json"), transcriptsDir: dir,
      deliveryPolicy: "mp4-only",
    }, { classify: noPalmier, legacyGuard: async () => noPalmier() });
  });
});

test("source and saved-cut bootstraps require unchanged live readback", async () => {
  for (const kind of ["source", "saved-cut"]) {
    await withProject(async (dir) => {
      bootstrap(dir, kind);
      const before = readFileSync(path.join(dir, STATE), "utf8");
      let calls = 0;
      await guardMp4LaunchAuthority(dir, async (observed) => {
        assert.equal(observed, dir);
        calls += 1;
      });
      assert.equal(calls, 1);
      assert.equal(readFileSync(path.join(dir, STATE), "utf8"), before);
    });
  }
});

test("manual, promoted, handed-off, checkpoint and unknown authority fail before readback", async () => {
  const cases = [
    { state: { ownership: "palmier" } },
    { state: { ownership: undefined } },
    { state: { workspaceMode: "verified-mirror" } },
    { state: { workingCheckpoint: { authoritative: false } } },
    { state: { draft: { assetKind: "source", authoritative: true } } },
    { state: { schemaVersion: 3 } },
    ...["palmier-manual", "sniper-promoted", "untrusted-bootstrap", "unknown"]
      .map((origin) => ({ authority: { origin } })),
    { authority: { projectId: "different-project" } },
    { authority: { timelineId: "different-head" } },
    { authority: { readbackCoverage: { complete: false } } },
    { authority: { fingerprint: "" } },
  ];
  for (const change of cases) {
    await withProject(async (dir) => {
      const base = bootstrap(dir);
      writeRecord(dir, STATE, { ...base.state, ...("state" in change ? change.state : {}) });
      writeRecord(dir, AUTHORITY, { ...base.authority, ...("authority" in change ? change.authority : {}) });
      await assert.rejects(guardMp4LaunchAuthority(dir, async () => {
        assert.fail("known incompatible state must fail without contacting Palmier");
      }), migrationConflict);
    });
  }
});

test("orphaned, malformed and unsafe records never become an absent-workspace fallback", async () => {
  for (const name of [STATE, AUTHORITY, CANDIDATE]) {
    await withProject(async (dir) => {
      writeRecord(dir, name, {});
      await assert.rejects(guardMp4LaunchAuthority(dir), migrationConflict);
      writeFileSync(path.join(dir, name), "{");
      await assert.rejects(guardMp4LaunchAuthority(dir), migrationConflict);
      rmSync(path.join(dir, name));
      symlinkSync(path.join(dir, "missing-authority.json"), path.join(dir, name));
      await assert.rejects(guardMp4LaunchAuthority(dir), migrationConflict);
    });
  }
  await withProject(async (dir) => {
    bootstrap(dir);
    writeRecord(dir, CANDIDATE, { status: "qc-approved" });
    await assert.rejects(guardMp4LaunchAuthority(dir), migrationConflict);
  });
});

test("unobserved human drift and unavailable Palmier both block in-place MP4", async () => {
  for (const message of ["manual Palmier revision preserved", "Palmier is closed"]) {
    await withProject(async (dir) => {
      bootstrap(dir);
      await assert.rejects(guardMp4LaunchAuthority(dir, async () => {
        throw new PalmierCanonicalError(message, 503);
      }), (error) => migrationConflict(error) && (error as Error).message.includes(message));
    });
  }
});

test("fresh and saved-plan HTTP launches preserve a human-owned project's plan and master", async () => {
  const original = process.env.SNIPER_WORKSPACE_ROOT;
  const stub = mock.method(childProcess, "spawn", () => assert.fail("blocked launch must not spawn"));
  syncBuiltinESMExports();
  try {
    await withProject(async (root) => {
      process.env.SNIPER_WORKSPACE_ROOT = root;
      const ctx = fixture(path.join(root, "project"));
      const intent = { mode: "short", scope: "light", lanes: {} };
      writeRecord(path.dirname(ctx.dir), "project.json", { origin: "raw", history: [], intent });
      const { state } = bootstrap(ctx.dir);
      writeRecord(ctx.dir, STATE, { ...state, ownership: "palmier" });
      writeFileSync(path.join(ctx.dir, "final.mp4"), "preserved approved master");
      const plan = readFileSync(ctx.planPath, "utf8");
      for (const action of [intent, { reviewSavedPlan: true }]) {
        const response = await POST(new NextRequest("http://localhost:3000/api/producer/auto-edit", {
          method: "POST", headers: { host: "localhost:3000", "content-type": "application/json" },
          body: JSON.stringify({ dir: ctx.dir, deliveryPolicy: "mp4-only", ...action }),
        }));
        assert.equal(response.status, 409);
        assert.match((await response.json()).error, /separate Sniper branch/);
        assert.equal(readFileSync(ctx.planPath, "utf8"), plan);
        assert.equal(readFileSync(path.join(ctx.dir, "final.mp4"), "utf8"), "preserved approved master");
        assert.equal(existsSync(path.join(ctx.dir, ".sniper-auto-edit-job.json")), false);
      }
      assert.equal(stub.mock.callCount(), 0);
    });
  } finally {
    stub.mock.restore();
    syncBuiltinESMExports();
    if (original === undefined) delete process.env.SNIPER_WORKSPACE_ROOT;
    else process.env.SNIPER_WORKSPACE_ROOT = original;
  }
});

test("the real guard subprocess has a hard deadline and rejects a killed readback", async () => {
  const spawn = childProcess.spawn;
  const replacement: typeof childProcess.spawn = ((...args: Parameters<typeof childProcess.spawn>) => {
    const options = args[2] as childProcess.SpawnOptions;
    assert.equal(options.timeout, PALMIER_AUTHORITY_GUARD_TIMEOUT_MS);
    assert.equal(options.killSignal, "SIGKILL");
    return spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], {
      ...options, timeout: 100,
    });
  }) as typeof childProcess.spawn;
  const stub = mock.method(childProcess, "spawn", replacement);
  syncBuiltinESMExports();
  try {
    const result = await runPalmierAuthorityGuard("/unused-fixture/producer");
    assert.equal(result.code, 1);
    assert.match(result.verdict.error ?? "", /SIGKILL; deadline 10000ms/);
    assert.equal(stub.mock.callCount(), 1);
  } finally {
    stub.mock.restore();
    syncBuiltinESMExports();
  }
});
