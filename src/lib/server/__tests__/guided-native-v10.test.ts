/** V10 requirements and inventory must not become invented asset-use or execution authority. */
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { test } from "node:test";
import { parseTreatmentProposalV10 } from "@/lib/producer/contracts/treatment-proposal-v10";
import { parseTreatmentProposalV9 } from "@/lib/producer/contracts/treatment-proposal-v9";
import { buildCodexArgs } from "@/app/api/_lib/codex-cli";
import { buildNativeTreatmentCandidate } from "../guided-native-candidate";
import { assertNativeSupportingPolicy, buildNativeSupportingPolicy, nativeProposalPreparationAllowed } from "../guided-native-supporting";
import { buildProposalPrompt } from "../guided-proposal-compiler";
import { buildProposalReadinessPacket, proposalReadinessAuthority } from "../guided-proposal-review-packet";
import { buildOpeningAuthority } from "../guided-opening-authority";
import { assertFullProgramMediaMetadata } from "../guided-opening-media-input";
import { nativeV10Fixture } from "./_guided-native-v10-fixture";

function withFixture(run: (fixture: ReturnType<typeof nativeV10Fixture>) => void): void {
  const fixture = nativeV10Fixture();
  try { run(fixture); } finally { fixture.cleanup(); }
}

test("supplied PNG yields typed pending requirements without fabricated asset decisions", () => withFixture(f => {
  const result = buildNativeTreatmentCandidate(f);
  assert.deepEqual(result.blockers, []);
  assert.deepEqual(result.pendingRequirements, [{ sceneId: "show-image", assetId: "supplied-image",
    startFrame: 0, endFrameExclusive: 50, occurrenceIds: [0, 1], quote: "Test words." }]);
  assert.deepEqual((result.candidate!.nativeDirection as { assetRequirements: unknown }).assetRequirements, result.pendingRequirements);
  assert.equal(nativeProposalPreparationAllowed(result), true);
  assert.equal("assetUse" in result.candidate!, false);
  assert.deepEqual(buildNativeTreatmentCandidate({ ...f, output: JSON.parse(JSON.stringify(f.output)) }), result);
}));

test("supporting scenes cannot reuse presenter/message semantics or incomplete holds", () => withFixture(f => {
  const changes: Array<(scene: Record<string, unknown>) => void> = [scene => { scene.view = "presenter"; },
    scene => { scene.requiredAssetIds = []; }, scene => { scene.requiredAssetIds = ["supplied-image", "supplied-image"]; },
    scene => { scene.before = ["fake message"]; }, scene => { scene.readingHoldFrames = 0; },
    scene => { scene.mechanism = "presenter-hold"; scene.view = "presenter"; }, scene => { scene.mechanism = ["supporting-asset"]; }];
  for (const change of changes) {
    const value = structuredClone(f.output); change(value.operations[0].scene as unknown as Record<string, unknown>);
    assert.throws(() => parseTreatmentProposalV10(value));
  }
}));

test("unknown IDs, style-reference IDs and unsupported video remain blockers", () => withFixture(f => {
  for (const id of ["missing", "TEST-STYLE", "supplied-video"]) {
    const output = structuredClone(f.output); output.operations[0].scene.requiredAssetIds = [id];
    const result = buildNativeTreatmentCandidate({ ...f, output });
    assert.equal(result.candidate, null); assert.ok(result.blockers.length);
    assert.equal(nativeProposalPreparationAllowed(result), false);
  }
}));

test("disabled placement or B-roll ownership prevents the pending-assets state", () => withFixture(f => {
  for (const mode of ["off", "operator", "placement-off"]) {
    const evidence = structuredClone(f.evidence), policy = evidence.nativeSupportingPolicy!;
    if (mode === "placement-off") policy.policy.placement = "off";
    else policy.brollEnabled = false;
    const result = buildNativeTreatmentCandidate({ ...f, evidence });
    assert.equal(result.candidate, null); assert.match(result.blockers[0].reason, /ownership and placement/);
    assert.equal(nativeProposalPreparationAllowed(result), false);
  }
}));

test("unrelated unsupported clauses and changed speech cannot masquerade as pending assets", () => withFixture(f => {
  const output = structuredClone(f.output); output.clauses[0].disposition = "unsupported"; output.clauses[0].operationIndices = [];
  output.operations = [];
  assert.equal(nativeProposalPreparationAllowed(buildNativeTreatmentCandidate({ ...f, output })), false);
  const changed = structuredClone(f.output); changed.operations[0].scene.quote = "Invented proof";
  const result = buildNativeTreatmentCandidate({ ...f, output: changed });
  assert.equal(result.candidate, null); assert.match(result.blockers[0].reason, /reproduce contiguous/);
  const ready = buildNativeTreatmentCandidate(f); ready.pendingRequirements = [];
  assert.equal(nativeProposalPreparationAllowed(ready), false);
}));

test("inventory retains unsupported files, current admission hashes and effective policy", () => withFixture(f => {
  const policy = buildNativeSupportingPolicy(f.authority);
  assert.equal(policy.assets.length, 2);
  assert.equal(policy.assets[0].mime, "image/png"); assert.equal(policy.assets[0].eligible, true);
  assert.equal(policy.assets[1].eligible, false); assert.match(policy.assets[1].ineligibilityReason!, /Only supplied/);
  assert.deepEqual(policy.policy, { placement: "auto", sources: "provided-only" });
  for (const owner of ["off", "operator"]) {
    const authority = structuredClone(f.authority); authority.intent.lanes = { broll: owner };
    assert.equal(buildNativeSupportingPolicy(authority).brollEnabled, false);
  }
  const wider = structuredClone(policy); wider.policy.sources = "public-web";
  assert.throws(() => assertNativeSupportingPolicy(wider, policy), /stored authority/);
  const stripped = structuredClone(policy); stripped.assets.pop();
  assert.throws(() => assertNativeSupportingPolicy(stripped, policy), /stored authority/);
}));

test("changed supplied file, changed receipt or duplicate manifest ID rejects inventory", () => withFixture(f => {
  const duplicate = structuredClone(f.authority); duplicate.manifest.broll[1].id = "supplied-image";
  assert.throws(() => buildNativeSupportingPolicy(duplicate), /duplicate IDs/);
  const receipt = readFileSync(f.receiptPath); writeFileSync(f.receiptPath, '{"changed":true}');
  assert.throws(() => buildNativeSupportingPolicy(f.authority), /receipt changed/);
  writeFileSync(f.receiptPath, receipt); writeFileSync(f.image, "changed supplied image");
  assert.throws(() => buildNativeSupportingPolicy(f.authority), /changed since ingest/);
}));

test("V9 still blocks external dependencies and has no V10 pending fields", () => withFixture(f => {
  const evidence = { ...f.evidence, schemaVersion: 9 as const }; delete evidence.nativeSupportingPolicy;
  const scene = { ...f.output.operations[0].scene, mechanism: "presenter-hold", view: "presenter" };
  const output = parseTreatmentProposalV9({ ...f.output, schemaVersion: 9, operations: [{ ...f.output.operations[0], scene }] });
  const blocked = buildNativeTreatmentCandidate({ ...f, evidence, output });
  assert.equal(blocked.candidate, null); assert.match(blocked.blockers[0].reason, /Required story assets/);
  assert.equal("pendingRequirements" in blocked, false);
  output.operations[0].scene.requiredAssetIds = [];
  const result = buildNativeTreatmentCandidate({ ...f, evidence, output });
  assert.deepEqual(result.blockers, []); assert.equal("pendingRequirements" in result, false);
  assert.equal("assetRequirements" in (result.candidate!.nativeDirection as object), false);
  assert.equal(nativeProposalPreparationAllowed(result), true);
  assert.match(buildProposalPrompt(f.rawIntent, evidence), /Required assets stay named.*block their scene/);
}));

test("V10 schema and prompt expose the new view without claiming acquired or selected media", () => withFixture(f => {
  const schema = JSON.parse(readFileSync("schemas/producer/treatment-proposal-v10.schema.json", "utf8"));
  assert.equal(schema.properties.schemaVersion.const, 10);
  assert.ok(schema.$defs.operation.properties.scene.properties.mechanism.enum.includes("supporting-asset"));
  assert.equal(schema.$defs.operation.properties.scene.properties.requiredAssetIds.uniqueItems, true);
  const args = buildCodexArgs({ schema: "producer-treatment-proposal-v10", sandbox: "read-only", tools: "none", timeoutMs: 1000 });
  assert.ok(args.some(arg => arg.endsWith("treatment-proposal-v10.schema.json")));
  const prompt = buildProposalPrompt(f.rawIntent, f.evidence);
  assert.match(prompt, /typed pending requirements/); assert.match(prompt, /No-insert cannot fulfill/);
  assert.equal(JSON.parse(prompt.split("INPUT_DATA_JSON\n")[1]).evidence.nativeSupportingPolicy.assets.length, 2);
}));

test("V10 cannot enter legacy readiness or opening execution", () => withFixture(f => {
  const result = buildNativeTreatmentCandidate(f);
  const held = { result } as Parameters<typeof buildProposalReadinessPacket>[0];
  assert.throws(() => buildProposalReadinessPacket(held), /native audiovisual review/);
  assert.throws(() => proposalReadinessAuthority(held), /native audiovisual review/);
  assert.throws(() => buildOpeningAuthority(held as unknown as Parameters<typeof buildOpeningAuthority>[0]), /no legacy opening/);
  assert.throws(() => assertFullProgramMediaMetadata({ plan: result.candidate!, proposal: f.output, bindings: null }), /legacy opening\/body/);
}));
