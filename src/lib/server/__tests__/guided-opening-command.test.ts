import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import { canonicalProducerDir } from "../../../app/api/producer/auto-edit/request";
import { createHash } from "node:crypto";
import { executeOpeningCommand, openingCommandServices, readOpeningCommandRequest, readOpeningApprovalCommandRequest }
  from "../../../../scripts/producer/guided-opening";

const request = { schemaVersion: 1, operation: "prepare-guided-opening",
  idempotencyKey: "01234567-1234-4123-8123-123456789012", expectedToken: "TEST-only",
  expectedJournalHash: "a".repeat(64), proposalReadinessHash: "b".repeat(64),
  treatmentDraftRevisionHash: "c".repeat(64) };
const approval = { schemaVersion: 1, operation: "approve-guided-opening", idempotencyKey: request.idempotencyKey,
  expectedToken: request.expectedToken, expectedJournalHash: request.expectedJournalHash,
  selectionHash: "d".repeat(64), coreMediaSha256: "e".repeat(64), reviewMediaSha256: "f".repeat(64),
  attestation: { watchedOpening: true, watchedBodyTransition: true, listened: true,
    approvesOpening: true, understandsBodyPending: true } };

function fixture() {
  const root = realpathSync(mkdtempSync(path.join(tmpdir(), "opening command $() ")));
  const file = path.join(root, "request's.json"); writeFileSync(file, JSON.stringify(request));
  const calls: string[] = [], inputs: unknown[] = [];
  const services = {
    ...openingCommandServices,
    canonicalDir: (dir: string) => { calls.push("canonical"); return dir; },
    status: () => { calls.push("status"); return { state: "unavailable", openingApproved: false }; },
    launchStatus: () => { calls.push("launch-status"); return { state: "eligible", request }; },
    launch: async (input: unknown) => { calls.push("launch"); inputs.push(input); return { state: "launch-recorded" }; },
    approve: async (input: unknown) => { calls.push("approve"); inputs.push(input);
      return { ok: true, replayed: false, approvalHash: "9".repeat(64) }; },
  } as unknown as typeof openingCommandServices;
  return { root, file, calls, inputs, services, cleanup: () => rmSync(root, { recursive: true }) };
}

test("direct status commands never start, approve, mutate or retry media", async () => {
  const f = fixture(); try {
    await executeOpeningCommand(["status", f.root], f.services);
    await executeOpeningCommand(["launch-status", f.root], f.services);
    assert.deepEqual(f.calls, ["canonical", "status", "canonical", "launch-status"]);
    assert.equal(f.inputs.length, 0);
  } finally { f.cleanup(); }
});

test("review-files checks selected bytes once per file without approval or rendering", async () => {
  const f = fixture(); try {
    const file = path.join(f.root, "TEST-not-real-media.mp4"), bytes = Buffer.from("TEST ONLY");
    writeFileSync(file, bytes);
    const row = { path: file, sizeBytes: bytes.length,
      mediaSha256: createHash("sha256").update(bytes).digest("hex") };
    const selected = { selectionHash: "d".repeat(64), rows: { core: row, review: row },
      sourceFreshness: "not-rechecked-by-status", observed: { sha256: "e".repeat(64) } };
    // TEST-only partial metadata; never supplied to production admission.
    f.services.selected = (() => selected) as unknown as typeof f.services.selected;
    let observations = 0; const observe = f.services.observeFile;
    f.services.observeFile = (...args) => { observations++; return observe(...args); };
    const result = await executeOpeningCommand(["review-files", f.root], f.services);
    assert.equal(observations, 1);
    assert.equal("deliveryApproved" in result && result.deliveryApproved, false);
    assert.equal("sourceFreshness" in result && result.sourceFreshness, "not-rechecked-by-status");
    writeFileSync(file, "CORRUPTED");
    await assert.rejects(executeOpeningCommand(["review-files", f.root], f.services), /bytes changed/);
    assert.equal(f.inputs.length, 0);
  } finally { f.cleanup(); }
});

test("review-files rejects selection changes during the byte check", async () => {
  const f = fixture(); try {
    const row = { path: f.file, sizeBytes: 1, mediaSha256: "a".repeat(64) };
    let reads = 0;
    f.services.selected = (() => ({ selectionHash: String(++reads).repeat(64),
      rows: { core: row, review: row }, observed: { sha256: "b".repeat(64) } })) as unknown as typeof f.services.selected;
    f.services.observeFile = () => ({ sha256: row.mediaSha256, sizeBytes: 1, bytes: Buffer.alloc(0) });
    await assert.rejects(executeOpeningCommand(["review-files", f.root], f.services), /selection changed/);
    assert.equal(f.inputs.length, 0);
  } finally { f.cleanup(); }
});

test("explicit launch keeps the exact persisted request and idempotency across retries", async () => {
  const f = fixture(); try {
    for (let index = 0; index < 2; index++) await executeOpeningCommand(["launch", f.root, f.file], f.services);
    assert.deepEqual(f.inputs, [{ dir: f.root, submission: request }, { dir: f.root, submission: request }]);
    assert.deepEqual(f.calls, ["canonical", "launch", "canonical", "launch"]);
  } finally { f.cleanup(); }
});

test("ambiguous launch error propagates without retry or status-as-success", async () => {
  const f = fixture(); try {
    f.services.launch = async () => { f.calls.push("launch"); throw new Error("TEST unknown launch ownership"); };
    await assert.rejects(executeOpeningCommand(["launch", f.root, f.file], f.services), /unknown launch ownership/);
    assert.deepEqual(f.calls, ["canonical", "launch"]);
  } finally { f.cleanup(); }
});

test("explicit approval preserves one exact decision and never launches or approves the body", async () => {
  const f = fixture(); try {
    writeFileSync(f.file, JSON.stringify(approval));
    for (let index = 0; index < 2; index++) {
      const result = await executeOpeningCommand(["approve", f.root, f.file], f.services);
      assert.equal("openingApproved" in result && result.openingApproved, true);
      assert.equal("bodyGenerated" in result && result.bodyGenerated, false);
      assert.equal("deliveryApproved" in result && result.deliveryApproved, false);
    }
    assert.deepEqual(f.inputs, [{ dir: f.root, submission: approval }, { dir: f.root, submission: approval }]);
    assert.deepEqual(f.calls, ["canonical", "approve", "canonical", "approve"]);
  } finally { f.cleanup(); }
});

test("approval never infers missing human attestations or accepts launch/delivery authority", async () => {
  const f = fixture(); try {
    const cases: unknown[] = [request, { ...approval, bodyApproved: true }, { ...approval, deadlineMs: 1 }];
    for (const flag of Object.keys(approval.attestation)) {
      for (const value of [false, "true", 1, null, undefined]) {
        cases.push({ ...approval, attestation: { ...approval.attestation, [flag]: value } });
      }
    }
    for (const value of cases) {
      writeFileSync(f.file, JSON.stringify(value));
      await assert.rejects(executeOpeningCommand(["approve", f.root, f.file], f.services));
    }
    assert.equal(f.inputs.length, 0);
    writeFileSync(f.file, JSON.stringify(approval));
    assert.throws(() => readOpeningCommandRequest(f.file));
  } finally { f.cleanup(); }
});

test("approval uses the same bounded no-follow request reader and never retries failure", async () => {
  const f = fixture(); try {
    writeFileSync(f.file, JSON.stringify(approval));
    const alias = path.join(f.root, "approval-link.json"); symlinkSync(f.file, alias);
    assert.throws(() => readOpeningApprovalCommandRequest(alias));
    f.services.approve = async () => { f.calls.push("approve"); throw new Error("TEST stale or ambiguous approval"); };
    await assert.rejects(executeOpeningCommand(["approve", f.root, f.file], f.services), /stale or ambiguous/);
    assert.deepEqual(f.calls, ["canonical", "approve"]);
    for (const bytes of [Buffer.from([0xff]), Buffer.alloc(16_385, 32)]) {
      writeFileSync(f.file, bytes); assert.throws(() => readOpeningApprovalCommandRequest(f.file));
    }
  } finally { f.cleanup(); }
});

test("identical approval replay acknowledges history without claiming fresh verification", async () => {
  const f = fixture(); try {
    writeFileSync(f.file, JSON.stringify(approval));
    f.services.approve = async () => ({ ok: true, replayed: true, approvalHash: "9".repeat(64),
      approvedAt: "2026-09-07T01:00:00.000Z", selectionHash: approval.selectionHash });
    const result = await executeOpeningCommand(["approve", f.root, f.file], f.services);
    assert.equal("verificationScope" in result && result.verificationScope,
      "recorded-decision-acknowledgment-no-fresh-readback");
    assert.equal("deliveryApproved" in result && result.deliveryApproved, false);
  } finally { f.cleanup(); }
});

test("request reader rejects malformed, extra authority, invalid UTF8, empty and oversized bytes", () => {
  const f = fixture(); try {
    const cases = ["", "{broken", "{}", JSON.stringify({ ...request, openingApproved: true }),
      JSON.stringify({ ...request, deadlineMs: 120000 }), "x".repeat(16_385), Buffer.from([0xff])];
    for (const value of cases) {
      writeFileSync(f.file, value); assert.throws(() => readOpeningCommandRequest(f.file));
    }
  } finally { f.cleanup(); }
});

test("request cannot be a symlink, directory or missing file", () => {
  const f = fixture(); try {
    const linked = path.join(f.root, "link.json"); symlinkSync(f.file, linked);
    for (const file of [linked, f.root, path.join(f.root, "absent.json")]) {
      assert.throws(() => readOpeningCommandRequest(file));
    }
  } finally { f.cleanup(); }
});

test("invalid command grammar and help perform no project reads", async () => {
  const f = fixture(); try {
    for (const args of [[], ["approve", f.root], ["launch", f.root], ["status", f.root, "--force"],
      ["launch", f.root, f.file, "--reset-deadline"], ["status", "bad\npath"]]) {
      await assert.rejects(executeOpeningCommand(args, f.services));
    }
    const help = await executeOpeningCommand(["--help"], f.services);
    assert.match(JSON.stringify(help), /Status never renders/); assert.deepEqual(f.calls, []);
  } finally { f.cleanup(); }
});

test("actual local CLI help and invalid grammar work without a dev server or media", () => {
  const cli = path.resolve("scripts/producer/guided-opening.ts");
  for (const [args, status] of [[["--help"], 0], [["approve", "/TEST"], 1]] as const) {
    const result = spawnSync(process.execPath, ["--import", "tsx", cli, ...args], {
      cwd: process.cwd(), env: { ...process.env, TSX_DISABLE_CACHE: "1" }, timeout: 10_000, encoding: "utf8" });
    assert.equal(result.status, status, result.stderr);
    assert.match(status === 0 ? result.stdout : result.stderr, /guided-opening.ts/);
  }
});

test("canonical directory validation does not initialize missing personal config", (context) => {
  const previous = process.env.SNIPER_WORKSPACE_ROOT;
  delete process.env.SNIPER_WORKSPACE_ROOT;
  let writes = 0;
  const exists = fs.existsSync;
  context.mock.method(fs, "existsSync", (file: fs.PathLike) =>
    String(file).endsWith("/.project-sniper/config.json") ? false : exists(file));
  context.mock.method(fs, "mkdirSync", () => { writes++; throw new Error("TEST unexpected config write"); });
  context.mock.method(fs, "writeFileSync", () => { writes++; throw new Error("TEST unexpected config write"); });
  try {
    assert.throws(() => canonicalProducerDir(process.cwd()));
    assert.equal(writes, 0);
  } finally {
    if (previous === undefined) delete process.env.SNIPER_WORKSPACE_ROOT;
    else process.env.SNIPER_WORKSPACE_ROOT = previous;
  }
});
