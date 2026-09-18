/** Genuine source2 admission; only new pre-seal TEST code copies, no native or shared-source mutation. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHash, randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { GUIDED_SOURCE_COLOR_TS_FILES } from "../guided-source-color-cleanup-pins";
import { canonicalJson, canonicalJsonSha256 } from "../auto-edit-hash";
import type { InitialBodySetup } from "./_guided-source-color-body-authority-fixture";
import { bodyMediaInputAdmissionFixture } from "./_guided-body-media-input-admission-fixture";

export const TEST_CONTROLLER_SOURCE = "scripts/producer/guided-body.ts";
type Fault = "missing" | "current-differs" | "lock-differs";

/** Publish before original job/claim/approval seals. The existing Python files and tool paths stay untouched. */
function initializeControllerSources(fault?: Fault): InitialBodySetup {
  return (job, root) => {
    const pipeline = job.ctx.pipeline!;
    assert.equal(pipeline.snapshotRoot, path.join(fs.realpathSync(root), "TEST-original-pipeline"));
    assert.equal(pipeline.lockPath, path.join(root, "TEST-original-pipeline-lock.json"));
    for (const relative of GUIDED_SOURCE_COLOR_TS_FILES) {
      if (relative === TEST_CONTROLLER_SOURCE && fault === "missing") continue;
      const current = path.join(process.cwd(), relative), info = fs.lstatSync(current);
      assert(info.isFile()); assert.equal(fs.realpathSync(current), current); assert(info.size <= 2 * 1024 * 1024);
      const bytes = relative === TEST_CONTROLLER_SOURCE && fault === "current-differs"
        ? Buffer.from("// TEST different controller; no execution\n") : fs.readFileSync(current);
      const copied = path.join(pipeline.snapshotRoot, relative);
      fs.mkdirSync(path.dirname(copied), { recursive: true, mode: 0o700 });
      assert.equal(fs.realpathSync(path.dirname(copied)), path.dirname(copied));
      fs.writeFileSync(copied, bytes, { flag: "wx", mode: 0o644 });
      pipeline.files.push({ path: relative, hash: createHash("sha256").update(bytes).digest("hex") });
    }
    pipeline.files.sort((left, right) => left.path.localeCompare(right.path));
    pipeline.digest = canonicalJsonSha256(pipeline.files);
  };
}

/** Seal only after actual TEST media/read/runner rows are finalized, before the original journal publication. */
function finalizeControllerSources(fault?: Fault): InitialBodySetup {
  return (job, root) => {
    const pipeline = job.ctx.pipeline!;
    assert.equal(pipeline.lockPath, path.join(fs.realpathSync(root), "TEST-original-pipeline-lock.json"));
    pipeline.files.sort((left, right) => left.path.localeCompare(right.path));
    pipeline.digest = canonicalJsonSha256(pipeline.files);
    const lock = { schemaVersion: 1, state: "pinned", runId: pipeline.runId, digest: pipeline.digest, files: pipeline.files };
    fs.writeFileSync(pipeline.lockPath, canonicalJson(fault === "lock-differs" ? { ...lock, runId: "TEST-other" } : lock), { flag: "wx", mode: 0o600 });
  };
}

export async function bodyControllerSourcesFixture(t: TestContext, fault?: Fault) {
  const fixture = await bodyMediaInputAdmissionFixture(t, initializeControllerSources(fault), finalizeControllerSources(fault));
  const root = fs.realpathSync(fixture.f.f.staging.root);
  return { ...fixture, root, copied: path.join(root, "TEST-original-pipeline", TEST_CONTROLLER_SOURCE),
    lock: path.join(root, "TEST-original-pipeline-lock.json") };
}
export type BodyControllerSourcesFixture = Awaited<ReturnType<typeof bodyControllerSourcesFixture>>;

/** Exact two fixture-owned files only. Never accept a source/tool inventory path as a mutation target. */
export function replaceControllerFixtureFile(f: BodyControllerSourcesFixture, role: "copy" | "lock"): void {
  const file = role === "copy" ? path.join(f.root, "TEST-original-pipeline", TEST_CONTROLLER_SOURCE)
    : path.join(f.root, "TEST-original-pipeline-lock.json");
  assert.equal(file, role === "copy" ? f.copied : f.lock);
  assert.equal(fs.realpathSync(file), file); assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const temporary = path.join(path.dirname(file), `TEST-controller-replacement-${randomUUID()}`);
  fs.writeFileSync(temporary, fs.readFileSync(file), { flag: "wx", mode: Number(stat.mode) & 0o777 });
  fs.renameSync(temporary, file);
}
