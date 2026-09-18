/** Local route and checkpoint-lease tests; no Director/provider/media execution. */
import assert from "node:assert/strict";
import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { NextRequest } from "next/server";
import { POST } from "@/app/api/producer/native-short/route";
import { POST as saveIntent } from "@/app/api/producer/intent/route";
import { readProjectJson } from "@/app/api/_lib/workspace";
import { guardProjectMutation } from "@/app/api/_lib/project-mutation";
import { resolveLanes, type ProjectIntent } from "@/lib/producer/intent-presets";
import type { ShortDirectionRequest } from "@/lib/producer/short-direction";
import { prepareNativeShortAppRequest } from "../native-short-app-preparation";
import { assertNativeShortIntent } from "../native-short-project";
import { prepareGuidedNativeShortRequest } from "../guided-native-authority";
import { acquireProjectMutationLease } from "../project-mutation-lease";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { nativeShortAppFixture, nativeProposalObservation, readNativeAppPacket } from "./_native-short-app-fixture";
import { nativeShortFixture } from "./_native-short-project-fixture";

function request(body: unknown, route = "native-short") {
  return new NextRequest(`http://127.0.0.1:3327/api/producer/${route}`, { method: "POST",
    headers: { host: "127.0.0.1:3327", origin: "http://127.0.0.1:3327", "sec-fetch-site": "same-origin",
      "content-type": "application/json" }, body: JSON.stringify(body) });
}

function guided(f: ReturnType<typeof nativeShortAppFixture>, inspect?: () => void) {
  return (dir: string) => prepareGuidedNativeShortRequest(dir, { readProposal: () => {
    inspect?.(); return nativeProposalObservation(f);
  } });
}

function assertLeaseReleased(root: string) {
  const next = acquireProjectMutationLease(root, "TEST prove release"); assert.ok(next.lease); next.lease.release();
}

function withoutSeparateBroll(f: ReturnType<typeof nativeShortAppFixture>): void {
  rmSync(f.jobPath);
  const manifest = JSON.parse(readFileSync(f.manifestPath, "utf8"));
  manifest.broll = []; manifest.sourceSetAdmission.entryCount = 1;
  writeFileSync(f.manifestPath, JSON.stringify(manifest));
}

/** Only the saved-intent admission gate is exercised here, not media or creative qualification. */
function assertScoutedSourceAdmitted(directory: string, intent: ProjectIntent): void {
  const input = nativeShortFixture(directory);
  input.request = intent.shortDirection!;
  input.strategy.supportingSearch.candidates = [{ assetFile: input.canvas.sourceFile,
    sourceStart: 0, sourceEnd: 1, observed: "TEST source-first candidate", role: "explanation",
    claimLimit: "TEST illustrated context only", selected: true, reason: "TEST saved lane authority",
    visibleId: "support", startFrame: 0, endFrame: 25 }];
  assertNativeShortIntent(input, intent);
}

const scoutingDirections: ShortDirectionRequest[] = [
  { selection: "auto", supportingVideo: "source-first" },
  ...(["provided-only", "local-only", "public-web"] as const).map(sources => ({
    selection: "requested" as const, request: "Show the actual process", supportingVideo: "source-first" as const,
    mediaPolicy: { placement: "auto" as const, sources },
  })),
];

for (const shortDirection of scoutingDirections) {
  test(`actual intent save preserves ${shortDirection.mediaPolicy?.sources ?? "default local"} scouting in native preparation`, async () => {
    const f = nativeShortAppFixture();
    try {
      withoutSeparateBroll(f);
      const intent = { ...readProjectJson(f.root)!.intent!, lanes: {}, shortDirection };
      const saved = await saveIntent(request({ dir: f.dir, intent }, "intent")), savedBody = await saved.json();
      assert.equal(saved.status, 200, JSON.stringify(savedBody));
      assert.deepEqual(savedBody.intentDecisions, []);
      const stored = readProjectJson(f.root)!;
      assert.deepEqual(stored.requestedIntent, intent);
      assert.deepEqual(stored.resolvedIntent, intent);
      const response = await POST(request({ dir: f.dir })), result = await response.json();
      assert.equal(response.status, 200, JSON.stringify(result));
      const packet = readNativeAppPacket(result.directory);
      assert.deepEqual(packet.intent, intent);
      assert.deepEqual(packet.availableSupportingAssets, []);
      assert.equal(packet.sources.length, 1);
      assert.equal(packet.sources[0].searchScope, "entire-admitted-source-including-outside-dialogue-cuts");
      assert.equal(resolveLanes(packet.intent.scope, packet.intent.lanes).broll, "auto");
      assertScoutedSourceAdmitted(f.workspace, packet.intent);
      assert.equal(packet.providerCalls, 0); assertLeaseReleased(f.root);
    } finally { f.cleanup(); }
  });
}

test("actual intent save and native preparation preserve disabled supporting placement", async () => {
  const f = nativeShortAppFixture();
  try {
    withoutSeparateBroll(f);
    const shortDirection = { selection: "auto", supportingVideo: "source-first",
      mediaPolicy: { placement: "off", sources: "public-web" } } satisfies ShortDirectionRequest;
    const intent = { ...readProjectJson(f.root)!.intent!, lanes: {}, shortDirection };
    const saved = await saveIntent(request({ dir: f.dir, intent }, "intent"));
    assert.equal(saved.status, 200, JSON.stringify(await saved.json()));
    const response = await POST(request({ dir: f.dir })), result = await response.json();
    assert.equal(response.status, 200, JSON.stringify(result));
    const packet = readNativeAppPacket(result.directory);
    assert.equal(packet.intent.lanes.broll, "off");
    assert.deepEqual(packet.intent.shortDirection, shortDirection);
    assert.throws(() => assertScoutedSourceAdmitted(f.workspace, packet.intent), /broll lane ownership/);
    assertLeaseReleased(f.root);
  } finally { f.cleanup(); }
});

test("ordinary POST preparation preserves the default manifest and stored project intent", async () => {
  const f = nativeShortAppFixture();
  try {
    rmSync(f.jobPath);
    const response = await POST(request({ dir: f.dir })), result = await response.json();
    assert.equal(response.status, 200, JSON.stringify(result));
    const packet = readNativeAppPacket(result.directory);
    assert.equal(packet.manifest.path, f.manifestPath);
    assert.equal(packet.intent.shortDirection.mediaPolicy.sources, "public-web");
    assert.equal(packet.providerCalls, 0); assertLeaseReleased(f.root);
  } finally { f.cleanup(); }
});

test("guided preparation uses nondefault bootstrap manifest and narrow stored intent under actual lease", async () => {
  const f = nativeShortAppFixture(true), journal = readFileSync(f.jobPath);
  try {
    let observations = 0;
    const response = prepareNativeShortAppRequest(f, { guided: guided(f, () => {
      observations++; const competing = acquireProjectMutationLease(f.root, "TEST concurrent mutation");
      assert.equal(competing.lease, undefined, "stored proposal must be read under the actual lease");
    }) });
    const result = await response.json(); assert.equal(response.status, 200, JSON.stringify(result));
    assert.equal(observations, 2);
    const packet = readNativeAppPacket(result.directory);
    assert.equal(packet.manifest.path, f.manifestPath);
    assert.equal(packet.sources[0].path, f.source); assert.equal(packet.availableSupportingAssets[0].path, f.picture);
    assert.equal(packet.intent.shortDirection.mediaPolicy.sources, "provided-only");
    assert.equal(packet.guidedProposal.evidenceHash, canonicalJsonSha256(nativeProposalObservation(f).evidence));
    assert.equal(result.proposalHash, "a".repeat(64)); assert.equal(packet.providerCalls, 0);
    assert.deepEqual(readFileSync(f.jobPath), journal); assertLeaseReleased(f.root);
  } finally { f.cleanup(); }
});

test("stale journal before lease acquisition cannot invoke native preparation", async () => {
  const f = nativeShortAppFixture(); let calls = 0;
  try {
    const response = prepareNativeShortAppRequest(f, { guided: guided(f, () => { calls++; }), guard: input => {
      writeFileSync(f.jobPath, `${readFileSync(f.jobPath, "utf8")}\n`);
      return guardProjectMutation(input);
    } });
    assert.equal(response.status, 409, JSON.stringify(await response.json()));
    assert.equal(calls, 0); assert.equal(existsSync(f.requests), false); assertLeaseReleased(f.root);
  } finally { f.cleanup(); }
});

test("journal changes after acquisition and during publication never return readiness", async () => {
  for (const point of ["after-acquire", "during-prepare"]) {
    const f = nativeShortAppFixture(); let observations = 0;
    try {
      const mutate = () => writeFileSync(f.jobPath, `${readFileSync(f.jobPath, "utf8")}\n`);
      const response = prepareNativeShortAppRequest(f, { guard: input => {
        const held = guardProjectMutation(input); if (point === "after-acquire") mutate(); return held;
      }, guided: guided(f, () => { observations++; if (point === "during-prepare" && observations === 2) mutate(); }) });
      const result = await response.json(); assert.equal(response.status, 409); assert.equal(result.code, "NATIVE_SHORT_CHECKPOINT_CHANGED");
      if (point === "after-acquire") assert.equal(observations, 0);
      assertLeaseReleased(f.root);
    } finally { f.cleanup(); }
  }
});

test("a concurrent writer blocks the actual POST before any packet write", async () => {
  const f = nativeShortAppFixture(), held = acquireProjectMutationLease(f.root, "TEST active writer"); assert.ok(held.lease);
  try {
    const response = await POST(request({ dir: f.dir })); assert.equal(response.status, 409);
    assert.equal(existsSync(f.requests), false);
  } finally { held.lease.release(); f.cleanup(); }
});

test("changed admitted source or supplied inventory bytes fail actual packet validation", () => {
  for (const asset of ["source", "picture"] as const) {
    const f = nativeShortAppFixture(true);
    try {
      writeFileSync(f[asset], "TEST changed after admission");
      assert.throws(() => prepareNativeShortAppRequest(f, { guided: guided(f) }), /changed since ingest/);
      assert.equal(existsSync(f.requests), false); assertLeaseReleased(f.root);
    } finally { f.cleanup(); }
  }
});

test("POST refuses source-policy widening, submitted packets and client lease capabilities", async () => {
  const f = nativeShortAppFixture(true);
  try {
    for (const extra of [{ intent: { shortDirection: { mediaPolicy: { sources: "public-web" } } } },
      { requestPacket: { path: "/tmp/submitted.json", sha256: "a".repeat(64) } }, { manifestPath: f.manifestPath },
      { checkpointVerification: { expectedToken: f.job.token } }, { readProposal: {} }]) {
      const response = await POST(request({ dir: f.dir, ...extra }));
      assert.equal(response.status, 400); assert.equal(existsSync(f.requests), false);
    }
  } finally { f.cleanup(); }
});

test("malformed or wrong-stage guided journals never fall back to the ordinary source folder", async () => {
  const f = nativeShortAppFixture();
  try {
    const source = readFileSync(f.jobPath, "utf8");
    for (const journal of ["{}", JSON.stringify({ ...JSON.parse(source), status: "failed" })]) {
      writeFileSync(f.jobPath, journal);
      const response = await POST(request({ dir: f.dir })); assert.ok([400, 409].includes(response.status));
      assert.equal(existsSync(f.requests), false);
    }
    assertLeaseReleased(f.root);
  } finally { f.cleanup(); }
});

test("app canonical directory and closed local request policy remain enforced", async () => {
  const f = nativeShortAppFixture();
  try {
    assert.equal((await POST(request({ dir: path.dirname(f.dir) }))).status, 400);
    const foreign = new NextRequest("http://127.0.0.1:3327/api/producer/native-short", { method: "POST",
      headers: { host: "127.0.0.1:3327", origin: "https://foreign.test", "content-type": "application/json" },
      body: JSON.stringify({ dir: f.dir }) });
    assert.equal((await POST(foreign)).status, 403); assert.equal(existsSync(f.requests), false);
  } finally { f.cleanup(); }
});
