import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import test from "node:test";
import { applyImport, prepareImport } from "./service";
import type { ImportPrepared } from "./model";

/** Real legal synthetic UI plan and generator; no models, graphics render or approval. */
function fixture(): { root: string; dir: string } {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sniper-native-copy-")));
  const script = String.raw`
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from tests.fixtures.create_studio_ui_fixture import create
from studio.studio_project import GenerateRequest, generate_project
row=create(Path(sys.argv[2])); d=Path(row["producerDir"])
generate_project(GenerateRequest(str(d/"edit_plan.json"),str(d/"base_final.mp4"),str(d/"studio")))
`;
  try {
    execFileSync(path.join(process.cwd(), ".venv/bin/python"),
      ["-c", script, path.join(process.cwd(), "scripts/producer"), root], { timeout: 30_000 });
    return { root, dir: path.join(root, "studio-ui-synthetic/producer") };
  } catch (error) { fs.rmSync(root, { recursive: true, force: true }); throw error; }
}

function changeLeaf(original: string, copy: string): string {
  const safe = copy.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  const changed = original.replace(/(<div id="te-text"[^>]*>)[\s\S]*?(<\/div>)/u,
    (_match, opening: string, closing: string) => opening + safe + closing);
  assert.notEqual(changed, original);
  return changed;
}

test("native leaf edits import repeatedly and undo through real Python gates without changing host, cut or final", async () => {
  const f = fixture();
  try {
    const comp = path.join(f.dir, "studio/compositions/gfx-01-text-element.html");
    const original = fs.readFileSync(comp, "utf8");
    const host = fs.readFileSync(path.join(f.dir, "studio/index.html"));
    const manifest = fs.readFileSync(path.join(f.dir, "studio/studio.manifest.json"));
    const planPath = path.join(f.dir, "edit_plan.json");
    const originalPlan = JSON.parse(fs.readFileSync(planPath, "utf8"));
    assert.equal((await prepareImport(f.dir) as ImportPrepared).state, "unchanged");
    for (const [index, copy] of ["Review timing clearly", "Use <safe> & clear copy", "Review the system"].entries()) {
      fs.writeFileSync(comp, copy === "Review the system" ? original : changeLeaf(original, copy));
      const proposal = await prepareImport(f.dir) as ImportPrepared;
      assert.equal(proposal.state, "ready", JSON.stringify(proposal.blockers));
      await applyImport(f.dir, { proposalId: proposal.proposalId!,
        expectedPlanHash: proposal.expectedPlanHash, expectedPlanVersion: proposal.expectedPlanVersion });
      const plan = JSON.parse(fs.readFileSync(planPath, "utf8"));
      assert.equal(plan.graphicsTrack[0].spec.text, copy);
      assert.equal(plan.planVersion, index + 2);
      assert.deepEqual(plan.cutTrack, originalPlan.cutTrack);
      assert.deepEqual(fs.readFileSync(path.join(f.dir, "studio/index.html")), host);
      assert.deepEqual(fs.readFileSync(path.join(f.dir, "studio/studio.manifest.json")), manifest);
      assert.equal(fs.existsSync(path.join(f.dir, "final.mp4")), false);
    }
    assert.equal((await prepareImport(f.dir) as ImportPrepared).state, "unchanged");
  } finally { fs.rmSync(f.root, { recursive: true, force: true }); }
});
