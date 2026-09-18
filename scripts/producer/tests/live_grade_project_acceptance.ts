/** Explicit opt-in internal service acceptance, never discovered as an ordinary test. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { observeProjectSource } from "../../../src/lib/server/grade-observation-service";
import { parents } from "../../../src/lib/server/grade-observation-store";

async function main() {
  const dir = process.argv[2];
  if (!dir || !path.isAbsolute(dir) || !dir.startsWith("/private/tmp/sniper-grade-project-live-"))
    throw new Error("Only a newly created explicit synthetic project is allowed");
  const project = path.dirname(dir), workspace = path.dirname(project);
  if (JSON.parse(fs.readFileSync(path.join(project, "project.json"), "utf8")).syntheticTestOnly !== true)
    throw new Error("Fixture is not explicitly synthetic");
  process.env.SNIPER_WORKSPACE_ROOT = workspace;
  const original = parents(dir), started = performance.now();
  const result = await observeProjectSource({ dir, sourceId: "raw-1", expectedPlanHash: original.planSha256,
    expectedManifestHash: original.manifestSha256, declaration: { schemaVersion: 1, sourceId: "raw-1",
      sourceProfile: "bt709-sdr", cameraProfile: "Deliberately synthetic fixture", historyState: "known", transformHistory: [],
      lightingGroups: [{ id: "dark", startFrame: 0, endFrame: 120, intent: "dark", description: "Intentional synthetic dark plate" },
        { id: "light", startFrame: 120, endFrame: 180, intent: "neutral", description: "Synthetic light plate; no correction" }] } });
  assert(!(result instanceof Response));
  const evidence = { ...result, wallMs: performance.now() - started, producerDir: dir,
    canonicalInputsUnchanged: JSON.stringify(parents(dir)) === JSON.stringify(original),
    noFinal: !fs.existsSync(path.join(dir, "final.mp4")), syntheticOnly: true };
  console.log(JSON.stringify(evidence));
  assert.equal(result.status, "complete"); assert.equal(result.cleanupVerified, true); assert.equal(result.decodedFrames, 180);
  assert.equal(result.gradeApplicable, false); assert.equal(result.deliveryApproved, false);
  assert(evidence.canonicalInputsUnchanged && evidence.noFinal);
  assert(!fs.existsSync(path.join(project, ".sniper-project-mutation.lock")));
  assert(!fs.existsSync(path.join(workspace, ".sniper-color-resource/active.json")));
}
main().catch(error => { console.error(String(error)); process.exitCode = 1; });
