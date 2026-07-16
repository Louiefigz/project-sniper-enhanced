import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { bindTemplateUsageForJob } from
  "../../../app/api/producer/auto-edit/template-usage-stage";
import { startAutoEditJob, readAutoEditJob, autoEditJobPath } from
  "../../server/auto-edit-job-store";
import { captureTemplateUsageAuthority } from "../../server/template-usage-history";

const root = mkdtempSync(path.join(os.tmpdir(), "sniper-usage-stage-"));
try {
  const dir = path.join(root, "project", "producer");
  const source = path.join(root, "project", "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  const planPath = path.join(dir, "edit_plan.json");
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(planPath, '{"target":{"mode":"longform"},"graphicsTrack":[]}');
  writeFileSync(manifestPath, '{"sources":[]}');
  const ctx = {
    dir, scope: "produced" as const, intent: { mode: "longform" as const, lanes: {} },
    planPath, manifestPath, transcriptsDir: source,
    doctrine: { runId: "usage-stage", doctrineHash: "a".repeat(64),
      snapshotPath: path.join(dir, "doctrine.json"), files: {} },
  };
  const job = startAutoEditJob({ ctx, token: "usage-stage", snapshots: 0 });
  const bound = bindTemplateUsageForJob(job, {
    capture: (value) => captureTemplateUsageAuthority(value, root, { projectDirs: () => [] }),
  });
  assert.equal(bound.job.ctx.templateUsage?.digest, bound.history.digest);
  assert.deepEqual(readAutoEditJob(autoEditJobPath(dir))?.ctx.templateUsage,
    bound.authority, "binding must be durable before the writer starts");
  const reused = bindTemplateUsageForJob(bound.job);
  assert.equal(reused.authority.digest, bound.authority.digest);
} finally {
  rmSync(root, { recursive: true, force: true });
}
console.log("template-usage-stage.test.ts: all assertions passed");
