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
assert.equal(defaultArgs[3], path.join(dir, "final.mp4"));

const candidate = path.join(dir, ".sniper-qc", "round-1", "final.mp4");
const candidateArgs = assembleCommandArgs(dir, manifest, candidate);
assert.equal(candidateArgs[3], candidate);
assert.deepEqual(candidateArgs.slice(-4), [
  "--fingerprint", path.join(dir, "base.fingerprint.json"),
  "--manifest", manifest,
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

/**
 * Regression (geometry contract v3 A2): assemble.py emits its typed errors —
 * including "NoLegalRegion: {...}" — via emit() on STDOUT. runAssemble's
 * errTail must carry that typed text so the re-plan route can key on it; a
 * stderr-only tail turned every render-time NoLegalRegion into an untyped
 * terminal failure. This spawns the REAL assemble.py (no plan file, so it hits
 * the typed emit path and exits 1) instead of faking the tail.
 */
async function typedAssembleErrorSurvivesIntoErrTail(): Promise<void> {
  const tmp = mkdtempSync(path.join(os.tmpdir(), "sniper-chain-assemble-"));
  try {
    const result = await runAssemble(tmp, path.join(tmp, "asset_manifest.json"), () => {});
    assert.equal(result.code, 1);
    assert.match(
      result.errTail, /"error"/,
      "assemble.py's typed emit() error must land in errTail — the NoLegalRegion re-plan route reads it",
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
