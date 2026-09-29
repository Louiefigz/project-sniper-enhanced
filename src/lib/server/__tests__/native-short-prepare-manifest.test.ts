/** `native-short.ts prepare --manifest`: per-clip producer folders name the admitted manifest explicitly.
 * TEST-only synthetic bytes; nothing is rendered or reviewed. */
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { executeNativeShortCommand } from "../../../../scripts/producer/native-short";
import { fileSha256 } from "../auto-edit-hash";
import { prepareNativeShortRequest } from "../native-short-request";
import { nativeShortFixture } from "./_native-short-project-fixture";

/** A per-clip layout: job/source holds the manifest; production/<clip>/source is a link to it. */
function perClipLayout(t: { after: (fn: () => void) => void }) {
  const job = realpathSync(mkdtempSync(path.join(os.tmpdir(), "TEST-prepare-manifest-")));
  t.after(() => rmSync(job, { recursive: true, force: true }));
  const source = path.join(job, "source"), clip = path.join(job, "production", "F"), producerDir = path.join(clip, "producer");
  mkdirSync(source); mkdirSync(producerDir, { recursive: true });
  symlinkSync("../../source", path.join(clip, "source"));
  const plan = nativeShortFixture(source), asset = plan.assets[0];
  writeFileSync(path.join(clip, "project.json"), JSON.stringify({ origin: "raw", history: [],
    intent: { mode: "short", scope: "produced", lanes: {}, shortDirection: plan.request } }));
  const receipt = path.join(source, "seed.json");
  writeFileSync(receipt, JSON.stringify({ test: "TEST synthetic admission" }));
  const receiptPath = `.sniper-source-sets/${fileSha256(receipt)}.json`;
  mkdirSync(path.join(source, ".sniper-source-sets"));
  writeFileSync(path.join(source, receiptPath), readFileSync(receipt));
  writeFileSync(path.join(source, "transcript.json"), JSON.stringify({ words: ["Test", "words."] }));
  writeFileSync(path.join(source, "asset_manifest.json"), JSON.stringify({ sources: [{ id: "test", path: asset.path,
    sourceSha256: asset.sha256, duration: 2, resolution: [1920, 1080], fps: 25, transcriptPath: "transcript.json" }],
  broll: [], music: [], sourceSetAdmission: { schemaVersion: 1, receiptPath, receiptSha256: fileSha256(receipt),
    sourceSetDigest: "a".repeat(64), entryCount: 1 } }));
  return { job, clip, producerDir, manifest: path.join(source, "asset_manifest.json"), intent: plan.request };
}

test("a per-clip producer names its admitted manifest; the linked default and a linked explicit path stay refused", async t => {
  const f = perClipLayout(t);
  await assert.rejects(executeNativeShortCommand(["prepare", f.producerDir]), /manifest path must be canonical/);
  await assert.rejects(executeNativeShortCommand(["prepare", f.producerDir, "--manifest",
    path.join(f.clip, "source", "asset_manifest.json")]), /manifest path must be canonical/);
  const result = await executeNativeShortCommand(["prepare", f.producerDir, "--manifest", f.manifest]) as { directory: string };
  const direct = prepareNativeShortRequest({ producerDir: f.producerDir, intent: JSON.parse(readFileSync(path.join(f.clip,
    "project.json"), "utf8")).intent, repo: process.cwd(), manifestPath: f.manifest });
  assert.deepEqual(result, direct);
  assert.equal(JSON.parse(readFileSync(path.join(result.directory, "SHORT-REQUEST.json"), "utf8")).manifest.path, f.manifest);
  await assert.rejects(executeNativeShortCommand(["prepare", f.producerDir, "--manifesto", f.manifest]), /Usage/);
});
