/** Explicit real owned-process rejection tests against an already admitted synthetic source. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { observeProjectSource } from "../../../src/lib/server/grade-observation-service";
import { parents, readRecord } from "../../../src/lib/server/grade-observation-store";

async function main() {
  const dir = process.argv[2];
  if (!dir?.startsWith("/private/tmp/sniper-grade-project-live-") || fs.realpathSync(dir) !== dir)
    throw new Error("Only an explicitly retained synthetic admission fixture is allowed");
  const project = path.dirname(dir), workspace = path.dirname(project);
  assert.equal(readRecord(path.join(project, "project.json")).syntheticTestOnly, true);
  process.env.SNIPER_WORKSPACE_ROOT = workspace;
  const original = parents(dir), findings = [];
  for (const name of ["unknown-history", "incomplete-source-groups"]) {
    const started = performance.now();
    const result = await observeProjectSource({ dir, sourceId: "raw-1", expectedPlanHash: original.planSha256,
      expectedManifestHash: original.manifestSha256, declaration: { schemaVersion: 1, sourceId: "raw-1",
        sourceProfile: "bt709-sdr", cameraProfile: null, historyState: name === "unknown-history" ? "unknown" : "known",
        transformHistory: [], lightingGroups: [{ id: "whole", startFrame: 0,
          endFrame: name === "incomplete-source-groups" ? 179 : 180, intent: "unknown", description: "Synthetic negative test" }] } });
    assert(!(result instanceof Response));
    assert.equal(result.status, "failed"); assert.equal(result.cleanupVerified, true);
    assert.equal(result.decodedFrames, null); assert.equal(result.gradeApplicable, false);
    const attempt = path.join(dir, ".sniper-grade-observations", result.jobId);
    assert(!fs.existsSync(path.join(attempt, "execution")), "invalid declaration must fail before container launch");
    assert.deepEqual(parents(dir), original);
    assert(!fs.existsSync(path.join(project, ".sniper-project-mutation.lock")));
    assert(!fs.existsSync(path.join(workspace, ".sniper-color-resource/active.json")));
    findings.push({ name, ...result, wallMs: performance.now() - started, containerNotLaunched: true });
  }
  assert(!fs.existsSync(path.join(dir, "final.mp4")));
  console.log(JSON.stringify({ producerDir: dir, findings, canonicalInputsUnchanged: true, noFinal: true }));
}
main().catch(error => { console.error(String(error)); process.exitCode = 1; });
