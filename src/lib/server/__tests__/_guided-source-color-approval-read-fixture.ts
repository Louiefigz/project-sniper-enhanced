/** Actual persisted TEST attestation, readback and approval CAS. No real operator approval or native replay. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { readSelectedOpeningMedia } from "../guided-opening-selection";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { readGuidedObject } from "../guided-cut-v2-store";
import { readSourceColorOpeningApproval, type SourceColorOpeningApprovalInput } from "../guided-source-color-approval-read";
import { sourceColorApprovalFixture } from "./_guided-source-color-approval-fixture";

/** One explicit TEST metadata read allowance starts after the separate, completed TEST approval transaction. */
export async function sourceColorApprovalReadFixture(t: TestContext) {
  const f = await sourceColorApprovalFixture(t), approved = await f.approve(), current = observeHumanCutJob(f.input.dir);
  const selected = readSelectedOpeningMedia(f.input.dir), fact = readGuidedObject(f.input.dir, approved.approvalHash);
  const row = fact.requalification as Record<string, unknown>;
  const directory = path.join(path.dirname(selected.held.claimPath), "readback-attempts", String(row.readbackDirectory));
  const callbacks = { guard: () => {} }, calls = { guard: 0 }, end = performance.now() + 30_000;
  const input: SourceColorOpeningApprovalInput = { dir: f.input.dir, current, selected, guard: () => {
    calls.guard++; callbacks.guard(); if (performance.now() >= end) throw new Error("TEST original metadata allowance expired");
  } };
  const files = { fact: path.join(f.input.dir, ".sniper-authority-v1/objects/receipts", `${approved.approvalHash}.json`),
    before: path.join(f.input.dir, "human-cut-job-snapshots", `${fact.beforeJournalHash}.json`),
    start: path.join(directory, "start.json"), output: path.join(directory, "output.json"), verified: path.join(directory, "verified.json"),
    published: path.join(directory, "approval.json") };
  const nativeCalls = f.calls.native;
  const read = () => {
    const result = readSourceColorOpeningApproval(input);
    assert.equal(f.calls.native, nativeCalls, "cold metadata cannot invoke another native verification leaf"); return result;
  };
  return { original: f, approved, input, files, callbacks, calls, root: f.staging.root, read };
}
export type SourceColorApprovalReadFixture = Awaited<ReturnType<typeof sourceColorApprovalReadFixture>>;
export type ApprovalReadRole = keyof SourceColorApprovalReadFixture["files"];

/** No inferred dependency target: exactly one named original TEST approval record, canonical and single-link. */
export function approvalReadFixtureFile(f: SourceColorApprovalReadFixture, role: ApprovalReadRole): string {
  const file = f.files[role], root = fs.realpathSync(f.root); assert(file.startsWith(root + path.sep));
  assert.equal(fs.realpathSync(file), file); assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!()); return file;
}

/** Equal bytes still substitute the original inode; only this explicit TEMP file can be replaced. */
export function replaceApprovalReadFixtureFile(f: SourceColorApprovalReadFixture, role: ApprovalReadRole): void {
  const file = approvalReadFixtureFile(f, role), temporary = path.join(path.dirname(file), `TEST-approval-read-${randomUUID()}.json`);
  fs.writeFileSync(temporary, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}

/** Counted reads/metadata mutations target inert published bytes, never installed sources or tools. */
export function rewriteApprovalReadFixtureFile(f: SourceColorApprovalReadFixture, role: ApprovalReadRole, value: string): void {
  fs.writeFileSync(approvalReadFixtureFile(f, role), value);
}
