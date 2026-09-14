/** Persistence/replay contracts only: synthetic bytes and injected lineage, no real acceptance or render. */
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, renameSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { canonicalJson, canonicalJsonSha256, fileSha256 } from "../auto-edit-hash";
import { assertGuidedNativeBinding } from "../guided-native-binding";
import { prepareGuidedNativeShortRequest } from "../guided-native-authority";
import { readNativeShortProject, writeNativeShortProject } from "../native-short-project";
import { writeGuidedNativeProject } from "../guided-native-project-store";
import { buildNativeShortProjectFiles } from "../guided-native-project";
import { guidedNativeSourceMedia } from "../guided-native-geometry";
import { guidedBindingFixture } from "./_guided-native-binding-fixture";
import { refreshNativePacingFixture } from "./_native-short-project-fixture";

type Fixture = ReturnType<typeof guidedBindingFixture>;
function withFixture(run: (f: Fixture) => void, version: 9 | 10 = 10): void {
  const f = guidedBindingFixture(version);
  try { run(f); } finally { f.cleanup(); }
}
function write(f: Fixture) {
  f.bind(); return writeNativeShortProject(f.input, path.join(f.directory, "built"), f.dependencies);
}
function rehashProject(directory: string, change: (input: Fixture["input"]) => void, omit?: string): void {
  const file = path.join(directory, "SHORT-PROJECT.json"), input = JSON.parse(readFileSync(file, "utf8"));
  change(input); writeFileSync(file, canonicalJson(input));
  const manifestPath = path.join(directory, "PROJECT-MANIFEST.json"), manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  manifest.projectHash = canonicalJsonSha256(input);
  manifest.files = manifest.files.filter((row: { file: string }) => row.file !== omit)
    .map((row: { file: string }) => ({ ...row, sha256: fileSha256(path.join(directory, row.file)) }));
  writeFileSync(manifestPath, canonicalJson(manifest));
}

test("V10 guided preparation retains pending work but cannot publish it unresolved", () => withFixture(f => {
  assert.equal(f.prepared.providerCalls, 0); assert.equal(f.prepared.pendingRequirements?.length, 1);
  const packet = JSON.parse(readFileSync(f.input.requestPacket!.path, "utf8"));
  assert.equal(packet.guidedProposal.proposalHash, f.proposal.proposalHash);
  assert.throws(() => buildNativeShortProjectFiles(f.proposal.result.candidate!,
    guidedNativeSourceMedia(f.input, f.proposal.manifest.value.sources), f.input.canvas.captionGroups,
    { candidateHash: canonicalJsonSha256(f.proposal.result.candidate), project: f.input }), /resolved persistent guided binding/);
  assert.throws(() => writeNativeShortProject(f.input, path.join(f.directory, "bad"), f.dependencies), /required persistent proposal binding/);
  f.mappings.length = 0;
  assert.throws(f.bind, /exact complete resolution coverage/);
  assert.equal(existsSync(path.join(f.directory, "bad")), false);
}));

test("V10 supplied image binding is a hashed shared project input and cold replays", () => withFixture(f => {
  const built = write(f), sidecar = path.join(built.directory, "GUIDED-PROPOSAL.json");
  assert.equal(built.manifest.files.find(row => row.file === "GUIDED-PROPOSAL.json")?.sha256, fileSha256(sidecar));
  assert.deepEqual(JSON.parse(readFileSync(sidecar, "utf8")), f.input.guidedBinding);
  assert.deepEqual(readNativeShortProject(built.directory, f.dependencies), f.input);
  assert.equal(f.input.guidedBinding?.resolutions[0].assetId, "supplied-image");
  assert.equal(built.manifest.pixelChecks, "not-run"); assert.equal(built.manifest.humanApproved, false);
}));

test("new V9 guided packets persist lineage without adopting V10 requirements", () => withFixture(f => {
  assert.equal(f.prepared.pendingRequirements, undefined);
  const built = write(f), reopened = readNativeShortProject(built.directory, f.dependencies);
  assert.equal(reopened.guidedBinding?.proposalVersion, 9);
  assert.deepEqual(reopened.guidedBinding?.resolutions, []);
}, 9));

test("changing the current proposal or its evidence invalidates cold replay even with unchanged candidate", () => {
  for (const change of [(f: Fixture) => { f.proposal.proposalHash = "d".repeat(64); },
    (f: Fixture) => { f.proposal.evidence.graphicsAdvice = { rawRevision: "TEST superseded brief" }; }]) {
    withFixture(f => {
      const built = write(f); change(f);
      assert.throws(() => readNativeShortProject(built.directory, f.dependencies), /current guided-marked prepared packet/);
    });
  }
});

test("cold read calls actual immutable reader by default and propagates superseded-admission errors", () => withFixture(f => {
  const built = write(f);
  assert.throws(() => readNativeShortProject(built.directory));
  assert.throws(() => readNativeShortProject(built.directory, { readGuidedProposal: () => {
    throw new Error("TEST raw admission was superseded");
  } }), /raw admission was superseded/);
}));

test("stripping guided binding plus its hashed file row cannot downgrade a guided packet", () => withFixture(f => {
  const built = write(f);
  rmSync(path.join(built.directory, "GUIDED-PROPOSAL.json"));
  rehashProject(built.directory, input => { delete input.guidedBinding; }, "GUIDED-PROPOSAL.json");
  assert.throws(() => readNativeShortProject(built.directory, f.dependencies), /required persistent proposal binding/);
}));

test("reserved V10 location rejects stripping every editable guided pointer and rehashing local metadata", () => withFixture(f => {
  f.bind(); const parent = path.join(f.producerDir, "native-development"); mkdirSync(parent);
  const built = writeNativeShortProject(f.input, path.join(parent, f.proposal.proposalHash), f.dependencies);
  rmSync(path.join(built.directory, "GUIDED-PROPOSAL.json"));
  rehashProject(built.directory, input => { delete input.guidedBinding; delete input.requestPacket; }, "GUIDED-PROPOSAL.json");
  assert.throws(() => readNativeShortProject(built.directory, f.dependencies), /Reserved guided native project lost/);
  const alias = path.join(f.directory, "plain-native-alias"); symlinkSync(built.directory, alias);
  assert.throws(() => readNativeShortProject(alias, f.dependencies), /Reserved guided native project lost/);
}));

test("historical V9 metadata without guided pointers stays readable at a verified reserved location", () => withFixture(f => {
  delete f.input.requestPacket; refreshNativePacingFixture(f.input);
  const built = writeNativeShortProject(f.input, path.join(f.directory, "old-shape"));
  const parent = path.join(f.producerDir, "native-development"); mkdirSync(parent);
  const destination = path.join(parent, f.proposal.proposalHash); renameSync(built.directory, destination);
  assert.equal(readNativeShortProject(destination, f.dependencies).guidedBinding, undefined);
  f.proposal.proposalHash = "e".repeat(64);
  assert.throws(() => readNativeShortProject(destination, f.dependencies), /superseded guided proposal/);
}, 9));

test("reserved location cannot adopt a packet from another proposal directory", () => withFixture(f => {
  f.bind(); const parent = path.join(f.producerDir, "native-development"); mkdirSync(parent);
  assert.throws(() => writeNativeShortProject(f.input, path.join(parent, "f".repeat(64)), f.dependencies), /another reserved proposal directory/);
}));

test("rehashing a modified sidecar cannot detach it from the native input", () => withFixture(f => {
  const built = write(f), file = path.join(built.directory, "GUIDED-PROPOSAL.json");
  writeFileSync(file, canonicalJson({ ...f.input.guidedBinding, resolutions: [] }));
  rehashProject(built.directory, () => {});
  assert.throws(() => readNativeShortProject(built.directory, f.dependencies), /sidecar differs/);
}));

test("rehashing modified claim, crop or audio decisions does not rewrite the saved guided binding", () => {
  for (const change of [(input: Fixture["input"]) => { input.strategy.assetUse!.decisions[0].claimLimit = "TEST fabricated result"; },
    (input: Fixture["input"]) => { input.strategy.assetUse!.decisions[0].selection!.essentialRegion = [0, 0, 1, 0.5]; },
    (input: Fixture["input"]) => { input.strategy.assetUse!.decisions[0].selection!.audio = "muted"; }]) {
    withFixture(f => {
      const built = write(f); rehashProject(built.directory, change);
      assert.throws(() => readNativeShortProject(built.directory, f.dependencies), /binding changed|without source audio/);
    });
  }
});

test("packet marker cannot be removed, replaced or malformed while a guided binding remains", () => {
  for (const change of [(packet: Record<string, unknown>) => { delete packet.guidedProposal; },
    (packet: Record<string, unknown>) => { packet.guidedProposal = null; },
    (packet: Record<string, unknown>) => { (packet.guidedProposal as Record<string, unknown>).proposalHash = "x"; }]) {
    withFixture(f => {
      f.bind(); const ref = f.input.requestPacket!, packet = JSON.parse(readFileSync(ref.path, "utf8"));
      change(packet); writeFileSync(ref.path, canonicalJson(packet)); ref.sha256 = fileSha256(ref.path)!;
      assert.throws(() => assertGuidedNativeBinding(f.input, f.dependencies));
    });
  }
});

test("source bytes and admitted image evidence remain live dependencies of cold replay", () => {
  for (const file of ["source", "image", "admission", "origin"] as const) withFixture(f => {
    const built = write(f), selected = f.input.assets.find(asset => asset.role === "image")!;
    const target = { source: f.input.assets[0].path, image: f.image, admission: f.receiptPath, origin: selected.origin!.path }[file];
    writeFileSync(target, "TEST changed external dependency");
    assert.throws(() => readNativeShortProject(built.directory, f.dependencies));
  });
});

test("preparation notices proposal-only revision changes during its second read", () => withFixture(f => {
  let reads = 0;
  assert.throws(() => prepareGuidedNativeShortRequest(f.producerDir, { readProposal: () => {
    if (++reads === 2) return { ...f.proposal, proposalHash: "e".repeat(64) };
    return f.proposal;
  } }), /changed during native request preparation/);
}));

test("guided adapter uses shared persistence and retained caption groups through internal structural seam", async () => {
  const f = guidedBindingFixture();
  try {
    const built = await writeGuidedNativeProject(f.producerDir, () => 10_000,
      { candidateHash: canonicalJsonSha256(f.proposal.result.candidate), project: f.input, assetResolutions: f.mappings },
      { ...f.dependencies, prepareCaptionGroups: async () => f.input.canvas.captionGroups });
    assert.equal(readNativeShortProject(built.directory, f.dependencies).guidedBinding?.proposalVersion, 10);
  } finally { f.cleanup(); }
});

test("guided adapter rejects proposal supersession on its final publication read", async () => {
  const f = guidedBindingFixture(); let reads = 0;
  try {
    await assert.rejects(writeGuidedNativeProject(f.producerDir, () => 10_000,
      { candidateHash: canonicalJsonSha256(f.proposal.result.candidate), project: f.input, assetResolutions: f.mappings },
      { readGuidedProposal: () => ++reads === 5 ? { ...f.proposal, proposalHash: "e".repeat(64) } : f.proposal,
        prepareCaptionGroups: async () => f.input.canvas.captionGroups }), /changed during publication/);
  } finally { f.cleanup(); }
});
