import assert from "node:assert/strict";
import path from "node:path";
import {
  assembleCommandArgs,
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
}

main()
  .then(() => console.log("auto-edit-chain.test.ts: all assertions passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
