import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { execFileSync } from "node:child_process";
import { prepareImport, applyImport } from "./service";
import { hasImportedPlan } from "./chain";
import { sha } from "./files";
import type { ImportPrepared } from "./model";
import { patchCopy, realFixture } from "./fixture_test";

test("real Python generator/strict diff/gates and ordinary save support repeated copy/timing; retain original host, manifest and final", async () => {
  const f = realFixture();
  try {
    const index = path.join(f.dir, "studio/index.html"); const originalHost = fs.readFileSync(index, "utf8");
    const manifest = fs.readFileSync(path.join(f.dir, "studio/studio.manifest.json"));
    const final = fs.readFileSync(path.join(f.dir, "final.mp4"));
    assert.equal((await prepareImport(f.dir) as ImportPrepared).state, "unchanged");
    patchCopy(f.dir, "Make the *system* clear");
    const first = await prepareImport(f.dir) as ImportPrepared;
    assert.equal(first.state, "ready", JSON.stringify(first.blockers));
    await applyImport(f.dir, { proposalId: first.proposalId!, expectedPlanHash: first.expectedPlanHash, expectedPlanVersion: first.expectedPlanVersion });
    assert.equal(await hasImportedPlan(f.dir), true);
    const editedHost = fs.readFileSync(index, "utf8");
    fs.writeFileSync(index, editedHost.replace('data-start="1" data-duration="3"', 'data-start="1.2" data-duration="2.8"'));
    const second = await prepareImport(f.dir) as ImportPrepared;
    assert.equal(second.state, "ready", JSON.stringify(second.blockers));
    assert.ok(second.changes.some((row) => row.field === "outStart"));
    const acceptedHost = fs.readFileSync(index);
    await applyImport(f.dir, { proposalId: second.proposalId!, expectedPlanHash: second.expectedPlanHash, expectedPlanVersion: second.expectedPlanVersion });
    assert.deepEqual(fs.readFileSync(index), acceptedHost);
    fs.writeFileSync(index, originalHost);
    const undo = await prepareImport(f.dir) as ImportPrepared;
    assert.equal(undo.state, "ready"); assert.ok(undo.changes.length);
    assert.deepEqual(fs.readFileSync(path.join(f.dir, "studio/studio.manifest.json")), manifest);
    assert.deepEqual(fs.readFileSync(path.join(f.dir, "final.mp4")), final);
  } finally { fs.rmSync(f.root, { recursive: true, force: true }); }
});

test("unchanged index plus unknown sidecar, and combined timing/code/spatial/audio/duplicate changes block", async () => {
  const f = realFixture();
  try {
    await prepareImport(f.dir);
    const index = path.join(f.dir, "studio/index.html"); const original = fs.readFileSync(index, "utf8");
    const beforePlan = sha(fs.readFileSync(path.join(f.dir, "edit_plan.json")));
    fs.writeFileSync(path.join(f.dir, "studio/unknown.txt"), "human edit");
    assert.equal((await prepareImport(f.dir) as ImportPrepared).state, "blocked");
    fs.unlinkSync(path.join(f.dir, "studio/unknown.txt"));
    for (const changed of [original.replace("paused: true", "paused: false"), original.replace("z-index: 10", "z-index: 11"),
      original.replace("muted playsinline", 'muted playsinline data-volume="0.5"'), original.replace('id="review-root"', 'id="review-root" id="other"'),
      original.replace('data-track-index="1"', 'data-track-index="9"'), `${original}<?unknown code?>`]) {
      fs.writeFileSync(index, changed.replace('data-start="1" data-duration="3"', 'data-start="1.1" data-duration="2.9"'));
      assert.equal((await prepareImport(f.dir) as ImportPrepared).state, "blocked");
    }
    fs.writeFileSync(index, Buffer.concat([Buffer.from(original), Buffer.from([0xff])]));
    await assert.rejects(prepareImport(f.dir), /valid UTF-8/u);
    assert.equal(sha(fs.readFileSync(path.join(f.dir, "edit_plan.json"))), beforePlan);
  } finally { fs.rmSync(f.root, { recursive: true, force: true }); }
});

test("strict parser preserves script string whitespace but accepts serializer quote/entity/attribute order", () => {
  const script = String.raw`
import sys
sys.path.insert(0,sys.argv[1])
from remainder import prove_host
entry=[{'slot':'slot','kind':'statement-card'}]
before='''<html><head><script>let text="a  b";</script></head><body><div id="review-root" data-duration="12"><div id="slot" data-hf-id="a" data-start="1" data-duration="2" data-variable-values='{"text":"a","variant":"classic"}'></div></div></body></html>'''
after=before.replace('data-start="1" data-duration="2"','data-duration="2.0" data-start="1.0"').replace("data-variable-values='",'data-variable-values="').replace('"text":"a","variant":"classic"}', '&quot;text&quot;:&quot;a&quot;,&quot;variant&quot;:&quot;classic&quot;}').replace("}'",'}"')
prove_host(before,after,entry)
try: prove_host(before,before.replace('a  b','a b'),entry)
except ValueError: print('passed')
else: raise AssertionError('script whitespace was discarded')
`;
  const result = execFileSync(path.join(process.cwd(), ".venv/bin/python"), ["-c", script, path.join(process.cwd(), "src/app/api/producer/studio/import")], { encoding: "utf8" });
  assert.match(result, /passed/u);
});
