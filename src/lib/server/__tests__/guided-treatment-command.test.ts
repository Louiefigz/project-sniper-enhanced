import assert from "node:assert/strict";
import { test, type TestContext } from "node:test";
import { spawnSync } from "node:child_process";
import { linkSync, mkdtempSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { executeTreatmentCommand, treatmentCommandServices as services } from "../../../../scripts/producer/guided-treatment";
import { readTreatmentCommandStatus, treatmentStatusReaders as readers } from "../../../../scripts/producer/guided-treatment-status";

const H = "a".repeat(64), ID = "01234567-1234-4123-8123-123456789012";
const common = { expectedToken: "TEST-token", expectedJournalHash: H, idempotencyKey: ID };
const submissions = {
  "accept-cut": { ...common, schemaVersion: 2, operation: "accept-cut-await-treatment", requestHash: H,
    executionKey: H, receiptHash: H, mediaSha256: H,
    attestation: { watched: true, listened: true, acceptsExactCut: true, understandsTreatmentPending: true } },
  admit: { ...common, schemaVersion: 1, operation: "propose-post-cut-treatment", requestId: ID,
    cutDecisionHash: H, parentRevisionHash: H, rawIntent: "TEST only: preserve the exact accepted cut." },
  revise: { ...common, schemaVersion: 1, operation: "revise-post-cut-treatment", requestId: ID,
    cutDecisionHash: H, parentRevisionHash: H, rawIntent: "TEST only: complete replacement brief.",
    supersession: "replace-complete-prior-brief", parentAdmissionHash: H, supersedesRequestHash: H },
  "reconcile-revision": { ...common, schemaVersion: 1, operation: "revise-post-cut-treatment", requestId: ID,
    cutDecisionHash: H, parentRevisionHash: H, rawIntent: "TEST only: complete replacement brief.",
    supersession: "replace-complete-prior-brief", parentAdmissionHash: H, supersedesRequestHash: H },
  compile: { ...common, schemaVersion: 1, operation: "compile-post-cut-proposal", treatmentAdmissionHash: H },
  review: { ...common, schemaVersion: 1, operation: "review-post-cut-proposal", proposalHash: H },
};
type Command = keyof typeof submissions;
const serviceName = { "accept-cut": "accept", admit: "admit", revise: "revise", "reconcile-revision": "reconcileRevision", compile: "compile", review: "review" } as const;

function fixture(t: TestContext) {
  const root = realpathSync(mkdtempSync(path.join(tmpdir(), "TEST-treatment $() ")));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const file = path.join(root, "request's.json"), calls: Array<{ name: string; input: unknown }> = [];
  t.mock.method(services, "canonicalDir", (dir: string) => dir);
  for (const name of ["accept", "admit", "revise", "reconcileRevision", "compile", "review", "status"] as const) {
    t.mock.method(services, name, (input: unknown) => { calls.push({ name, input }); throw new Error("TEST unexpected service"); });
  }
  const write = (value: unknown) => writeFileSync(file, JSON.stringify(value));
  return { root, file, calls, write };
}

function result(replayed = false) {
  return { replayed, job: { token: "TEST-next-token", status: "treatment_admitted",
    guidedHandoffV2: { cutDecisionHash: H, pictureLockedRevisionHash: H, treatmentAdmissionHash: H } },
    generationStartedAt: "2026-09-07T12:00:00.000Z", proposalHash: H, readinessHash: H,
    treatmentAdmissionHash: H, superseded: false, sourceFreshness: "not-requalified-by-revision",
    pointer: { treatmentDraftRevisionHash: null } };
}

for (const command of Object.keys(submissions) as Command[]) {
  test(`${command} dispatches only its exact closed submission, preserving UUID and replay`, async (t) => {
    const f = fixture(t); f.write(submissions[command]);
    const seen: unknown[] = [];
    t.mock.method(services, serviceName[command], async (input: unknown) => { seen.push(input); return result(seen.length > 1); });
    for (const replayed of [false, true]) {
      const out = await executeTreatmentCommand([command, f.root, f.file]);
      assert.equal("replayed" in out && out.replayed, replayed);
      assert.equal("idempotencyKey" in out && out.idempotencyKey, ID);
      assert.equal("deliveryApprovalGranted" in out && out.deliveryApprovalGranted, false);
      assert.equal("subjectiveListening" in out && out.subjectiveListening, "not-performed-by-system");
      if (replayed) assert.match(JSON.stringify(out), /no-fresh-source-verification/);
    }
    assert.deepEqual(seen, [1, 2].map(() => ({ dir: f.root, submission: submissions[command] })));
    assert.deepEqual(f.calls, []);
  });
}

test("cut command rejects missing, false or fabricated-type attestations without service dispatch", async (t) => {
  const f = fixture(t), original = submissions["accept-cut"];
  for (const flag of Object.keys(original.attestation)) {
    for (const value of [false, "true", 1, null, undefined]) {
      f.write({ ...original, attestation: { ...original.attestation, [flag]: value } });
      await assert.rejects(executeTreatmentCommand(["accept-cut", f.root, f.file]));
    }
  }
  f.write({ ...original, attestation: undefined });
  await assert.rejects(executeTreatmentCommand(["accept-cut", f.root, f.file]));
  assert.deepEqual(f.calls, []);
});

test("all operations reject cross-operation, extra authority and malformed identity fields", async (t) => {
  const f = fixture(t);
  for (const command of Object.keys(submissions) as Command[]) {
    const patches = [{ schemaVersion: 99 }, { operation: "accept" }, { expectedJournalHash: "bad" },
      { idempotencyKey: "../escape" }, { deadlineMs: 60000 }, { provider: "TEST" }, { approve: true }];
    for (const patch of patches) {
      f.write({ ...submissions[command], ...patch });
      await assert.rejects(executeTreatmentCommand([command, f.root, f.file]));
    }
  }
  assert.deepEqual(f.calls, []);
});

test("raw intent stays data and supports the existing maximum even with escaped JSON units", async (t) => {
  const f = fixture(t), rawIntent = "a".repeat(20000), seen: unknown[] = [];
  const request = { ...submissions.admit, rawIntent };
  const text = JSON.stringify({ ...request, rawIntent: "PLACEHOLDER" }).replace("PLACEHOLDER", "\\u0061".repeat(20000));
  assert.ok(Buffer.byteLength(text) < 128 * 1024); writeFileSync(f.file, text);
  t.mock.method(services, "admit", async (input: unknown) => { seen.push(input); return result(); });
  await executeTreatmentCommand(["admit", f.root, f.file]);
  assert.deepEqual(seen, [{ dir: f.root, submission: request }]);
  f.write({ ...request, rawIntent: "a".repeat(20001) });
  await assert.rejects(executeTreatmentCommand(["admit", f.root, f.file]));
  assert.equal(seen.length, 1);
});

test("bounded transport rejects empty, malformed, extra NDJSON, invalid UTF8 and oversize before project reads", async (t) => {
  const f = fixture(t); let reads = 0;
  t.mock.method(services, "canonicalDir", () => { reads++; return f.root; });
  for (const bytes of ["", "{broken", "{}\n{}", Buffer.from([0xff]), Buffer.alloc(128 * 1024 + 1, 32)]) {
    writeFileSync(f.file, bytes);
    await assert.rejects(executeTreatmentCommand(["compile", f.root, f.file]));
  }
  assert.equal(reads, 0); assert.deepEqual(f.calls, []);
});

test("ambiguous attestation and bounded JSON failures never read a project or invoke a service", async (t) => {
  const f = fixture(t); let reads = 0;
  t.mock.method(services, "canonicalDir", () => { reads++; return f.root; });
  const exact = JSON.stringify(submissions["accept-cut"]);
  const inputs = [exact.replace('"watched":true', '"watched":false,"watched":true'),
    exact.replace('"watched":true', '"watched":false,"\\u0077atched":true'),
    exact.replace('"attestation":{', '"attestation":null,"attestation":{'),
    '{"nested":[{"listened":false,"listened":true}]}', '{"number":1e400}',
    "[".repeat(17) + "0" + "]".repeat(17)];
  for (const text of inputs) {
    writeFileSync(f.file, text);
    await assert.rejects(executeTreatmentCommand(["accept-cut", f.root, f.file]));
  }
  assert.equal(reads, 0); assert.deepEqual(f.calls, []);
});

test("request rejects symlink, hardlink, directory, missing file and FIFO without blocking", async (t) => {
  const f = fixture(t); f.write(submissions.compile);
  const symlink = path.join(f.root, "symlink.json"), hardlink = path.join(f.root, "hardlink.json");
  symlinkSync(f.file, symlink); linkSync(f.file, hardlink);
  const fifo = path.join(f.root, "fifo.json");
  const made = spawnSync("mkfifo", [fifo], { timeout: 2000, encoding: "utf8" });
  assert.equal(made.status, 0, made.stderr);
  for (const file of [symlink, hardlink, f.file, f.root, fifo, path.join(f.root, "missing.json")]) {
    await assert.rejects(executeTreatmentCommand(["compile", f.root, file]));
  }
  assert.deepEqual(f.calls, []);
});

test("service errors are not retried, turned into status success or used to refresh request fields", async (t) => {
  const f = fixture(t); f.write(submissions.review);
  await assert.rejects(executeTreatmentCommand(["review", f.root, f.file]), /TEST unexpected service/);
  assert.deepEqual(f.calls, [{ name: "review", input: { dir: f.root, submission: submissions.review } }]);
});

test("help and invalid grammar do not resolve projects or dispatch services", async (t) => {
  const f = fixture(t); let reads = 0;
  t.mock.method(services, "canonicalDir", () => { reads++; return f.root; });
  for (const argv of [[], ["init", f.root], ["accept-cut", f.root], ["status", f.root, "extra"],
    ["compile", f.root, f.file, "--provider=TEST"], ["status", "bad\npath"], ["status", "a".repeat(4097)]]) {
    await assert.rejects(executeTreatmentCommand(argv));
  }
  assert.match(JSON.stringify(await executeTreatmentCommand(["--help"])), /bootstrap is not provided/);
  assert.equal(reads, 0); assert.deepEqual(f.calls, []);
});

function statusFixture(t: TestContext, pointer: Record<string, unknown> | undefined) {
  const f = fixture(t), before = { sha256: H, job: { token: common.expectedToken, guidedHandoffV2: pointer } };
  t.mock.method(readers, "journal", () => before);
  t.mock.method(readers, "briefs", () => ({ pendingRevision: null, history: [], currentBrief: null }));
  t.mock.method(readers, "briefCurrent", () => {});
  const calls: string[] = [];
  for (const name of ["pending", "cut", "admission", "proposal", "readiness"] as const) {
    t.mock.method(readers, name, () => { calls.push(name); throw new Error("TEST strongest reader rejected"); });
  }
  return { ...f, before, readerCalls: calls };
}

test("pending status exposes only held bindings, no UUID, human attestations or inferred acceptance", (t) => {
  const f = statusFixture(t, undefined);
  t.mock.method(readers, "pending", () => ({ ...f.before, job: { ...f.before.job, status: "awaiting_cut_approval" },
    request: { requestHash: H, planHash: H }, receipt: { executionKey: H, receiptHash: H, media: { sha256: H } } }));
  const value = readTreatmentCommandStatus(f.root);
  assert.equal(value.nextCommand, "accept-cut"); assert.equal(value.facts.humanCutAccepted, false);
  assert.deepEqual(value.requestBindings, { expectedToken: common.expectedToken, expectedJournalHash: H,
    requestHash: H, executionKey: H, receiptHash: H, mediaSha256: H });
  assert.equal(value.approvalGranted, false); assert.equal(value.requestBindingsIncludeConsent, false);
  assert.deepEqual(f.calls, []);
});

test("each later status uses its existing strong reader without inferring opening eligibility", (t) => {
  const f = statusFixture(t, {});
  const branches = [
    { pointer: {}, name: "cut", next: "admit", fields: { job: { ...f.before.job, status: "awaiting_treatment_brief" },
      pointer: { cutDecisionHash: H, pictureLockedRevisionHash: H } } },
    { pointer: { treatmentAdmissionHash: H }, name: "admission", next: "compile", fields: {
      pointer: { treatmentAdmissionHash: H }, generationStartedAt: "TEST-origin" } },
    { pointer: { treatmentProposalHash: H }, name: "proposal", next: "review", fields: {
      proposalHash: H, result: { candidate: {}, blockers: [] }, generationStartedAt: "TEST-origin" } },
    { pointer: { proposalReadinessHash: H }, name: "readiness", next: "guided-opening launch-status", fields: {
      pointer: { treatmentDraftRevisionHash: H }, readinessHash: H, readiness: { verdict: "clean" }, draftRevision: {}, generationStartedAt: "TEST-origin" } },
  ] as const;
  for (const branch of branches) {
    f.before.job.guidedHandoffV2 = branch.pointer;
    t.mock.method(readers, branch.name, () => ({ ...f.before, ...branch.fields }));
    const value = readTreatmentCommandStatus(f.root);
    assert.equal(value.nextCommand, branch.next);
    assert.equal(value.sourceFreshness, "not-requalified-by-status");
    if (branch.name === "readiness") assert.equal(value.requestBindings, null);
  }
  assert.deepEqual(f.calls, []);
});

test("blocked proposal/readiness expose no action and corrupt highest stage never falls back", (t) => {
  const f = statusFixture(t, { treatmentProposalHash: H });
  t.mock.method(readers, "proposal", () => ({ ...f.before, proposalHash: H,
    result: { candidate: null, blockers: ["TEST unresolved"] }, generationStartedAt: "TEST-origin" }));
  assert.equal(readTreatmentCommandStatus(f.root).nextCommand, null);
  f.before.job.guidedHandoffV2 = { proposalReadinessHash: H };
  assert.throws(() => readTreatmentCommandStatus(f.root), /strongest reader rejected/);
  assert.deepEqual(f.readerCalls, ["readiness"]);
  t.mock.method(readers, "readiness", () => ({ ...f.before, pointer: {}, readinessHash: H,
    readiness: { verdict: "blocked" }, draftRevision: null, generationStartedAt: "TEST-origin" }));
  assert.equal(readTreatmentCommandStatus(f.root).requestBindings, null);
});

test("status rejects initial/strong/final journal mismatches instead of publishing mixed bindings", (t) => {
  const f = statusFixture(t, { treatmentAdmissionHash: H });
  t.mock.method(readers, "admission", () => ({ ...f.before, sha256: "b".repeat(64),
    pointer: { treatmentAdmissionHash: H }, generationStartedAt: "TEST-origin" }));
  assert.throws(() => readTreatmentCommandStatus(f.root), /journal changed/);
  t.mock.method(readers, "admission", () => ({ ...f.before, pointer: { treatmentAdmissionHash: H }, generationStartedAt: "TEST-origin" }));
  let reads = 0;
  t.mock.method(readers, "journal", () => ({ ...f.before, sha256: ++reads === 1 ? H : "c".repeat(64) }));
  assert.throws(() => readTreatmentCommandStatus(f.root), /journal changed/);
});

test("accepted cut cannot project an intake action from an inconsistent later status", (t) => {
  const f = statusFixture(t, { cutDecisionHash: H });
  t.mock.method(readers, "cut", () => ({ ...f.before, job: { ...f.before.job, status: "treatment_admitted" },
    pointer: { cutDecisionHash: H, pictureLockedRevisionHash: H } }));
  assert.throws(() => readTreatmentCommandStatus(f.root), /consistent treatment-intake/);
  assert.deepEqual(f.calls, []);
});

test("pending revision status exposes exact recovery identity without an old-brief compile/readiness action", (t) => {
  const f = statusFixture(t, { treatmentAdmissionHash: H, proposalReadinessHash: H });
  t.mock.method(readers, "briefs", () => ({ generationStartedAt: "TEST-original-clock", currentBrief: { rawIntent: "TEST original" },
    history: [], pendingRevision: { idempotencyKey: ID, requestHash: H, parentAdmissionHash: H } }));
  const result = readTreatmentCommandStatus(f.root);
  assert.equal(result.stage, "revision-reconciliation-required"); assert.equal(result.nextCommand, null);
  assert.equal(result.requestBindings, null); assert.equal(result.briefs!.pendingRevision!.idempotencyKey, ID);
  assert.deepEqual(f.readerCalls, []); assert.equal(result.approvalGranted, false);
});

test("actual CLI help and grammar failures need no server, provider or project", () => {
  const cli = path.resolve("scripts/producer/guided-treatment.ts");
  for (const [args, expected] of [[["--help"], 0], [["accept-cut", "/TEST"], 1]] as const) {
    const result = spawnSync(process.execPath, ["--import", "tsx", cli, ...args], {
      cwd: process.cwd(), env: { ...process.env, TSX_DISABLE_CACHE: "1" }, timeout: 10000, encoding: "utf8" });
    assert.equal(result.status, expected, result.stderr);
    assert.doesNotThrow(() => JSON.parse(expected ? result.stderr : result.stdout));
    assert.equal(expected ? result.stdout : result.stderr, "");
  }
});
