/** Offline current-plan review packet and render admission. Never invokes a provider. */
import path from "node:path";
import { prepareSavedPlanReview } from "../../src/app/api/producer/auto-edit/saved-plan-request";
import { assertRenderReadiness } from "../../src/lib/server/plan-readiness";
import { readinessPacket } from "../../src/lib/server/plan-readiness-packet";
import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { pythonInterpreter } from "../../src/app/api/_lib/spawn-python";
import { atomicWriteJsonSync } from "../../src/lib/server/atomic-file";
import { canonicalJsonSha256 as hash, fileSha256 } from "../../src/lib/server/auto-edit-hash";

const [command, directory, plan, manifest] = process.argv.slice(2);
try {
  if (!["packet", "check", "check-draft", "preview"].includes(command) || !directory) throw new Error("usage: plan-readiness.ts packet|check|check-draft <producerDir> [plan manifest]; preview <producerDir> <clip> <unitId>...");
  const { ctx } = prepareSavedPlanReview(path.resolve(directory));
  if (command !== "preview") {
    if (plan && fileSha256(path.resolve(plan)) !== fileSha256(ctx.planPath)) throw new Error("Readiness belongs to different plan bytes");
    if (manifest && path.resolve(manifest) !== path.resolve(ctx.manifestPath)) throw new Error("Readiness belongs to a different manifest path");
  }
  if (command === "preview") {
    const packet = readinessPacket(ctx), ids = process.argv.slice(5);
    if (!plan || !ids.length || new Set(ids).size !== ids.length) throw new Error("Preview requires a clip and unique unit IDs");
    const units = Object.fromEntries(ids.map(id => {
      const unit = packet.units.find(row => row.id === id);
      if (!unit) throw new Error(`Unknown review unit: ${id}`);
      return [id, unit.hash];
    }));
    const root = path.join(ctx.dir, ".sniper-previews");
    mkdirSync(root, { recursive: true });
    const result = spawnSync(pythonInterpreter(), ["scripts/producer/readiness_preview.py", path.resolve(plan), path.join(root, "media")],
      { encoding: "utf8", timeout: 120000, maxBuffer: 1024 * 1024 });
    if (result.error || result.status !== 0) throw new Error(result.error?.message || result.stderr || result.stdout);
    if (readinessPacket(ctx).digest !== packet.digest) throw new Error("Plan changed while preview was decoded");
    const core = { schemaVersion: 1, kind: "producer-readiness-preview", units, media: JSON.parse(result.stdout) };
    const digest = hash(core), receipt = path.join(root, `${digest}.json`);
    atomicWriteJsonSync(receipt, { ...core, digest });
    console.log(JSON.stringify({ receipt, units, media: core.media }, null, 2));
  } else if (command === "packet") console.log(JSON.stringify(readinessPacket(ctx), null, 2));
  else {
    assertRenderReadiness(ctx, command === "check-draft");
    console.log(JSON.stringify({ status: "current-render-readiness", draft: command === "check-draft" }));
  }
} catch (error) {
  console.error(`Render readiness refused: ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
}
