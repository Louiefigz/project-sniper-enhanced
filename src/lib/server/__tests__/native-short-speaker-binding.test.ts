/** X228/X229 rules for a plan's shared-evidence binding on synthetic TEST inputs (no child process; `evidenceCheck.run`
 * is replaced): its shape, currency judged at admission and only reported to readers, and agreement with the record the
 * prebuild review's role packet bound. */
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { test, type TestContext } from "node:test";
import { fileSha256 } from "../auto-edit-hash";
import { NativeCheckError } from "../native-check-error";
import { evidenceCheck } from "../native-review-shared-evidence";
import type { NativeShortProjectInput } from "../native-short-project";
import { assertCurrentSharedEvidence, assertSharedEvidenceAdmitted, assertSharedEvidenceBound, nativeSharedEvidenceBinding,
  nativeSharedEvidenceStatus, reviewedSharedEvidence } from "../native-short-speaker-binding";

const RECORD = { path: "/TEST/evidence/shared-evidence-v3.json", sha256: "a".repeat(64), contentSha256: "b".repeat(64), version: 3 };
const OTHER = { ...RECORD, path: "/TEST/evidence/shared-evidence-v4.json", sha256: "c".repeat(64), version: 4 };
const plan = (extra: Record<string, unknown> = {}) => ({ canvas: { totalFrames: 300 }, ...extra }) as unknown as NativeShortProjectInput;
const current = (row = RECORD) => () => ({ status: "shared-evidence-current", ...row });
const coded = (code: string, text?: RegExp) => (error: unknown) => error instanceof NativeCheckError && error.code === code
  && (!text || text.test(error.message));

/** A TEST prebuild receipt whose role packet bound `sharedEvidence` (or nothing), under a temporary folder. */
function reviewed(t: TestContext, sharedEvidence: Record<string, unknown> | null, schemaVersion = 2) {
  const root = realpathSync(mkdtempSync(path.join(tmpdir(), "TEST-speaker-binding-")));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  mkdirSync(path.join(root, "records"));
  const write = (file: string, value: unknown) => { writeFileSync(file, typeof value === "string" ? value : JSON.stringify(value)); return file; };
  const instruction = write(path.join(root, "TEST-INSTRUCTIONS.md"), "# TEST instructions\n");
  const packet = write(path.join(root, "records", "plan-critic-PACKET.json"), { schemaVersion: 1, kind: "sniper-role-packet",
    role: "plan-critic", route: "native-short", resolvedAt: new Date().toISOString(), repository: root, authorSessionIds: ["TEST-author"],
    subject: {}, artifacts: [{ key: "TEST-0", path: instruction, sha256: fileSha256(instruction) }],
    instructions: [{ path: instruction, sha256: fileSha256(instruction) }], declaredMedia: [], ...(sharedEvidence ? { sharedEvidence } : {}) });
  const receipt = write(path.join(root, "TEST-prebuild.json"), { schemaVersion,
    submission: { rolePacket: { path: packet, sha256: fileSha256(packet) } } });
  return { path: receipt, sha256: fileSha256(receipt)!, packet };
}

test("the binding has exactly its four checked fields", () => {
  assert.equal(nativeSharedEvidenceBinding(plan()), undefined);
  assert.deepEqual(nativeSharedEvidenceBinding(plan({ sharedEvidence: RECORD })), RECORD);
  const bad: Array<[Record<string, unknown>, RegExp]> = [[{ ...RECORD, extra: 1 }, /unsupported fields: extra/u],
    [{ ...RECORD, version: 0 }, /record version/u], [{ ...RECORD, version: 1.5 }, /record version/u],
    [{ ...RECORD, sha256: "A".repeat(64) }, /sha256 must be a lowercase SHA-256/u], [{ path: RECORD.path, sha256: RECORD.sha256, version: 3 }, /missing fields: contentSha256/u],
    [{ ...RECORD, path: "" }, /path must be a non-empty string/u]];
  for (const [row, text] of bad) assert.throws(() => nativeSharedEvidenceBinding(plan({ sharedEvidence: row })), text);
});

test("currency refuses by name at admission and is only reported to readers", (t) => {
  t.mock.method(evidenceCheck, "run", current());
  assert.doesNotThrow(() => assertCurrentSharedEvidence(RECORD));
  assert.deepEqual(nativeSharedEvidenceStatus(plan({ sharedEvidence: RECORD })), { status: "current", path: RECORD.path, version: 3 });
  assert.equal(nativeSharedEvidenceStatus(plan()), null);
  const resealed = "Shared evidence re-check failed: /TEST/evidence/shared-evidence-v3.json is superseded by ['shared-evidence-v4.json']; bind the current version";
  t.mock.method(evidenceCheck, "run", () => { throw new Error(resealed); });
  assert.deepEqual(nativeSharedEvidenceStatus(plan({ sharedEvidence: RECORD })), { status: "stale-evidence", path: RECORD.path, version: 3, reason: resealed });
  assert.throws(() => assertCurrentSharedEvidence(RECORD), coded("stale-evidence", /superseded by .* Rebind the plan's sharedEvidence to the current sealed record and obtain a fresh plan review; projects already built from this binding stay readable$/u));
  t.mock.method(evidenceCheck, "run", current(OTHER));
  assert.equal(nativeSharedEvidenceStatus(plan({ sharedEvidence: RECORD }))?.status, "stale-evidence", "the check reports another record");
  for (const field of ["path", "sha256", "contentSha256", "version", "status"] as const) {
    t.mock.method(evidenceCheck, "run", () => ({ status: "shared-evidence-current", ...RECORD, [field]: field === "version" ? 4 : "0".repeat(64) }));
    assert.equal(nativeSharedEvidenceStatus(plan({ sharedEvidence: RECORD }))?.status, "stale-evidence", field);
  }
  const spawn = Object.assign(new Error("TEST spawnSync python ETIMEDOUT"), { code: "ETIMEDOUT" });
  t.mock.method(evidenceCheck, "run", () => { throw spawn; });
  assert.throws(() => nativeSharedEvidenceStatus(plan({ sharedEvidence: RECORD })), (error: unknown) => error === spawn, "a process failure is not staleness");
  t.mock.method(evidenceCheck, "run", () => { throw new SyntaxError("TEST unparsable report"); });
  assert.throws(() => nativeSharedEvidenceStatus(plan({ sharedEvidence: RECORD })), SyntaxError);
});

test("the review packet's record is read at its recorded hashes", (t) => {
  assert.equal(reviewedSharedEvidence(plan()), null, "no review");
  const none = reviewed(t, null);
  assert.equal(reviewedSharedEvidence(plan({ prebuildReview: { path: none.path, sha256: none.sha256 } })), null);
  const bound = reviewed(t, { path: RECORD.path, sha256: RECORD.sha256, version: 3 });
  assert.deepEqual(reviewedSharedEvidence(plan({ prebuildReview: { path: bound.path, sha256: bound.sha256 } })), { path: RECORD.path, sha256: RECORD.sha256 });
  const historical = reviewed(t, { path: RECORD.path, sha256: RECORD.sha256 }, 1);
  assert.equal(reviewedSharedEvidence(plan({ prebuildReview: { path: historical.path, sha256: historical.sha256 } })), null, "schema 1 has no packet");
  assert.throws(() => reviewedSharedEvidence(plan({ prebuildReview: { path: bound.path, sha256: "0".repeat(64) } })), /receipt changed/u);
  const packet = JSON.parse(readFileSync(bound.packet, "utf8")) as Record<string, unknown>;
  writeFileSync(bound.packet, JSON.stringify({ ...packet, sharedEvidence: { path: OTHER.path, sha256: OTHER.sha256, version: 4 } }));
  assert.throws(() => reviewedSharedEvidence(plan({ prebuildReview: { path: bound.path, sha256: bound.sha256 } })),
    /The prebuild review's role packet changed since the review/u, "a well-formed packet edited after the review");
});

test("X229: an unbound or different binding is refused by name, and a review-pending plan may omit it", (t) => {
  t.mock.method(evidenceCheck, "run", current());
  const packetBound = reviewed(t, { path: RECORD.path, sha256: RECORD.sha256, version: 3 });
  const review = { path: packetBound.path, sha256: packetBound.sha256 };
  assert.throws(() => assertSharedEvidenceBound(plan({ prebuildReview: review })), coded("shared-evidence-unbound",
    new RegExp(`^\\[shared-evidence-unbound\\] plan binds no shared evidence, but its prebuild review packet bound ${RECORD.path} \\(aaaaaaaaaaaa\\), whose sealed speaker facts P2-08 must check: set the plan's sharedEvidence to that record and obtain a fresh plan review$`, "u")));
  assert.throws(() => assertSharedEvidenceBound(plan({ prebuildReview: review, sharedEvidence: OTHER })), coded("shared-evidence-unbound",
    /plan binds \/TEST\/evidence\/shared-evidence-v4\.json \(cccccccccccc\), but its prebuild review packet bound \/TEST\/evidence\/shared-evidence-v3\.json \(aaaaaaaaaaaa\): bind the record the critic reviewed/u));
  assert.throws(() => assertSharedEvidenceBound(plan({ prebuildReview: review, sharedEvidence: { ...RECORD, path: "/TEST/elsewhere/shared-evidence-v3.json" } })),
    coded("shared-evidence-unbound"), "same bytes at another path is another binding");
  assert.doesNotThrow(() => assertSharedEvidenceBound(plan({ prebuildReview: review, sharedEvidence: RECORD })));
  assert.throws(() => assertSharedEvidenceBound(plan({ speakerPictureDecisions: [] })), coded("shared-evidence-unbound",
    /plan carries speakerPictureDecisions but binds no shared evidence: bind the sealed record they answer \(sharedEvidence\), or remove the decisions$/u));
  assert.doesNotThrow(() => assertSharedEvidenceBound(plan()), "review pending, no decisions: P2-08's (b) is the owner's decision (X229)");
  const unreviewed = reviewed(t, null);
  assert.doesNotThrow(() => assertSharedEvidenceBound(plan({ prebuildReview: { path: unreviewed.path, sha256: unreviewed.sha256 } })));
  assert.doesNotThrow(() => assertSharedEvidenceBound(plan({ prebuildReview: { path: unreviewed.path, sha256: unreviewed.sha256 }, sharedEvidence: RECORD })));
  t.mock.method(evidenceCheck, "run", () => { throw new Error("Shared evidence re-check failed: TEST superseded"); });
  assert.throws(() => assertSharedEvidenceAdmitted(plan({ sharedEvidence: RECORD })), coded("stale-evidence"));
  assert.throws(() => assertSharedEvidenceAdmitted(plan({ prebuildReview: review })), coded("shared-evidence-unbound"), "agreement is judged first");
  assert.doesNotThrow(() => assertSharedEvidenceAdmitted(plan()), "nothing bound: no check runs");
});
