import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  assembleCommandArgs,
  runAssemble,
  runAuditB,
  runAuditBOutcome,
} from "../../../app/api/producer/auto-edit/chain";

const dir = "/tmp/sniper-chain-fixture/producer";
const manifest = "/tmp/sniper-chain-fixture/source/asset_manifest.json";
const defaultArgs = assembleCommandArgs(dir, manifest);
assert.ok(defaultArgs.includes("--defer-active"));
assert.equal(
  defaultArgs[defaultArgs.indexOf("--output") + 1],
  path.join(dir, "final.mp4"),
);

const candidate = path.join(dir, ".sniper-qc", "round-1", "final.mp4");
const candidateArgs = assembleCommandArgs(dir, manifest, candidate);
const rendererStart = candidateArgs.indexOf("--") + 1;
assert.equal(candidateArgs[rendererStart + 3], candidate);
assert.deepEqual(candidateArgs.slice(-5), [
  "--fingerprint", path.join(dir, "base.fingerprint.json"),
  "--manifest", manifest,
  "--require-source-set-admission",
]);

async function main(): Promise<void> {
  const failed = await runAuditBOutcome(dir, async () => ({
    event: { event: "audit", overall: "fail", failed: 2 },
    failure: "two deterministic checks failed",
  }));
  assert.equal(failed.failure, "two deterministic checks failed");
  assert.equal(failed.event.overall, "fail");

  const crashed = await runAuditBOutcome(dir, async () => {
    throw new Error("review frames unavailable");
  });
  assert.equal(crashed.event.overall, "error");
  assert.match(crashed.failure ?? "", /candidate is not approved/);
  assert.match(crashed.failure ?? "", /review frames unavailable/);

  const events: Record<string, unknown>[] = [];
  await assert.rejects(
    runAuditB(dir, (event) => events.push(event), async () => failed),
    /two deterministic checks failed/,
  );
  assert.deepEqual(events, [failed.event]);

  await typedAssembleErrorSurvivesIntoErrTail();
}

/** The graph preflight's typed stdout failure must survive in errTail. */
async function typedAssembleErrorSurvivesIntoErrTail(): Promise<void> {
  const tmp = mkdtempSync(path.join(os.tmpdir(), "sniper-chain-assemble-"));
  try {
    const result = await runAssemble(tmp, path.join(tmp, "asset_manifest.json"), () => {});
    assert.equal(result.code, 2);
    assert.match(
      result.errTail, /"error"/,
      "the graph preflight error must land in errTail before a child can run",
    );
    assert.match(result.errTail, /edit_plan\.json/);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
}

main()
  .then(() => console.log("auto-edit-chain.test.ts: all assertions passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
