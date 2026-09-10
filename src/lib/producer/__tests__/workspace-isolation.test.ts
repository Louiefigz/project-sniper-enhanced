import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import fs from "node:fs";
import { mock } from "node:test";
import os from "node:os";
import path from "node:path";
import { workspaceOverride, workspaceRoot } from "../../../app/api/_lib/workspace";
import { listProjects, upsertProject } from "../../../app/api/_lib/projects-registry";

const root = mkdtempSync(path.join(os.tmpdir(), "sniper-workspace-isolation-"));
const previous = process.env.SNIPER_WORKSPACE_ROOT;
const personalRegistry = path.join(os.homedir(), ".project-sniper", "projects.json");
const personalConfig = path.join(os.homedir(), ".project-sniper", "config.json");
const readOptional = (file: string) => existsSync(file) ? readFileSync(file, "utf8") : null;
const before = [readOptional(personalRegistry), readOptional(personalConfig)];
try {
  for (const invalid of ["", ".", "relative", "/", "/.", "//", `${root}/../outside`]) {
    process.env.SNIPER_WORKSPACE_ROOT = invalid;
    assert.throws(workspaceRoot, /absolute, non-root workspace/);
    assert.throws(listProjects, /absolute, non-root workspace/);
  }
  process.env.SNIPER_WORKSPACE_ROOT = root;
  assert.equal(workspaceRoot(), root);
  assert.deepEqual(listProjects(), []);
  upsertProject(path.join(root, "synthetic", "producer"), "Synthetic UI qualification");
  assert.equal(listProjects().length, 1);
  assert.equal(listProjects()[0].title, "Synthetic UI qualification");
  assert.ok(existsSync(path.join(root, ".project-sniper", "projects.json")));
  assert.deepEqual([readOptional(personalRegistry), readOptional(personalConfig)], before);
  delete process.env.SNIPER_WORKSPACE_ROOT;
  assert.equal(workspaceOverride(), null, "default config remains the historical source");
  const realExists = fs.existsSync;
  const missingConfig = mock.method(fs, "existsSync", (file: Parameters<typeof fs.existsSync>[0]) => file === personalConfig ? false : realExists(file));
  const mkdir = mock.method(fs, "mkdirSync", () => { throw new Error("Unexpected config directory write"); });
  const write = mock.method(fs, "writeFileSync", () => { throw new Error("Unexpected config write"); });
  try {
    assert.equal(workspaceRoot({ initialize: false }), path.join(os.homedir(), "ProjectSniper"));
    assert.equal(mkdir.mock.callCount(), 0);
    assert.equal(write.mock.callCount(), 0);
  } finally { missingConfig.mock.restore(); mkdir.mock.restore(); write.mock.restore(); }
} finally {
  if (previous === undefined) delete process.env.SNIPER_WORKSPACE_ROOT;
  else process.env.SNIPER_WORKSPACE_ROOT = previous;
  rmSync(root, { recursive: true, force: true });
}
console.log("workspace-isolation.test.ts: all assertions passed");
