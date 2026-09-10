import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { test } from "node:test";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { verifyOpeningApprovalMedia } from "../guided-opening-approval";

function fixture(bytes = Buffer.from("TEST bytes, not playable media")) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(tmpdir(), "sniper-approval-media-")));
  const file = path.join(root, "selected.mp4"); fs.writeFileSync(file, bytes);
  const row = { path: file, sizeBytes: bytes.length, mediaSha256: createHash("sha256").update(bytes).digest("hex") };
  return { root, file, bytes, row, cleanup: () => fs.rmSync(root, { recursive: true }) };
}

test("approval byte verification deduplicates files while checking both selected row identities", (context) => {
  const f = fixture(); let reads = 0;
  const original = fs.readSync;
  context.mock.method(fs, "readSync", (...args: Parameters<typeof fs.readSync>) => {
    reads++; return original(...args);
  });
  try {
    verifyOpeningApprovalMedia({ core: f.row, review: { ...f.row } }, () => {});
    assert.equal(reads, 1);
    for (const patch of [{ mediaSha256: "0".repeat(64) }, { sizeBytes: f.row.sizeBytes + 1 }]) {
      assert.throws(() => verifyOpeningApprovalMedia({ core: f.row, review: { ...f.row, ...patch } }, () => {}), /bytes or size changed/);
    }
  } finally { f.cleanup(); }
});

test("approval byte verification rejects symlinks, multiply linked files and wrong size/hash", () => {
  const f = fixture();
  try {
    const linked = path.join(f.root, "linked.mp4"); fs.symlinkSync(f.file, linked);
    assert.throws(() => verifyOpeningApprovalMedia({ core: { ...f.row, path: linked } }, () => {}));
    const hardlink = path.join(f.root, "hardlinked.mp4"); fs.linkSync(f.file, hardlink);
    assert.throws(() => verifyOpeningApprovalMedia({ core: f.row }, () => {}), /bounded regular file/);
    fs.unlinkSync(hardlink);
    for (const patch of [{ mediaSha256: "0".repeat(64) }, { sizeBytes: f.row.sizeBytes + 1 }]) {
      assert.throws(() => verifyOpeningApprovalMedia({ core: { ...f.row, ...patch } }, () => {}), /bytes or size changed/);
    }
  } finally { f.cleanup(); }
});

test("selected FIFO rejects in a bounded child without invoking approval, a provider or decoder", () => {
  const f = fixture();
  try {
    const fifo = path.join(f.root, "selected-fifo.mp4");
    const made = spawnSync("/usr/bin/mkfifo", [fifo], { timeout: 1000, encoding: "utf8" });
    assert.equal(made.status, 0, made.stderr);
    const script = "const {verifyOpeningApprovalMedia}=require('./src/lib/server/guided-opening-approval.ts');"
      + "try{verifyOpeningApprovalMedia({core:JSON.parse(process.env.SNIPER_APPROVAL_TEST_ROW)},()=>{});process.exitCode=2;}"
      + "catch(error){process.stdout.write(JSON.stringify({error:error.message}));}";
    const started = performance.now();
    const result = spawnSync(process.execPath, ["--import", "tsx", "-e", script], {
      cwd: process.cwd(), timeout: 5000, killSignal: "SIGKILL", encoding: "utf8",
      env: { ...process.env, TSX_DISABLE_CACHE: "1", SNIPER_APPROVAL_TEST_ROW: JSON.stringify({ ...f.row, path: fifo }) },
    });
    assert.equal(result.error, undefined); assert.equal(result.signal, null);
    assert.equal(result.status, 0, result.stderr); assert.match(result.stdout, /bounded regular file/);
    assert.ok(performance.now() - started < 5000);
  } finally { f.cleanup(); }
});

test("descriptor observation rejects same-sized path replacement during the read", () => {
  const f = fixture(); let checks = 0;
  try {
    assert.throws(() => observeCutPreviewFile(f.file, 1024, false, () => {
      if (++checks !== 2) return;
      fs.renameSync(f.file, path.join(f.root, "original.mp4")); fs.writeFileSync(f.file, f.bytes);
    }), /identity changed/);
  } finally { f.cleanup(); }
});

test("descriptor observation rejects in-place growth or truncation during the read", () => {
  for (const truncate of [true, false]) {
    const f = fixture(); let checks = 0;
    try {
      assert.throws(() => observeCutPreviewFile(f.file, 1024, false, () => {
        if (++checks !== 2) return;
        if (truncate) fs.truncateSync(f.file, 1); else fs.appendFileSync(f.file, "changed");
      }), /identity changed|truncated/);
    } finally { f.cleanup(); }
  }
});

test("guard runs before opening and its exact lease/clock failure propagates", () => {
  const stopped = new Error("TEST expired allowance or lost lease");
  assert.throws(() => observeCutPreviewFile("/TEST/missing/never-opened.mp4", 1024, false,
    () => { throw stopped; }), (error) => error === stopped);
});

test("mid-read guard stops before another chunk and closes the owned descriptor", (context) => {
  const f = fixture(Buffer.alloc(2 * 1024 * 1024 + 1, 31));
  const stopped = new Error("TEST lease revoked during hashing"); let checks = 0, closes = 0;
  const close = fs.closeSync; context.mock.method(fs, "closeSync", (fd: number) => { closes++; return close(fd); });
  try {
    assert.throws(() => observeCutPreviewFile(f.file, f.bytes.length, false, () => {
      if (++checks === 3) throw stopped;
    }), (error) => error === stopped);
    assert.equal(checks, 3); assert.equal(closes, 1);
  } finally { f.cleanup(); }
});

test("post-read guard failure cannot return a successful observation", () => {
  const f = fixture(); const stopped = new Error("TEST deadline reached after identity check"); let checks = 0;
  try {
    assert.throws(() => observeCutPreviewFile(f.file, 1024, false, () => {
      if (++checks === 3) throw stopped;
    }), (error) => error === stopped);
    assert.equal(checks, 3);
  } finally { f.cleanup(); }
});

test("approval helper forwards guard failures through each chunk and does not check another range", (context) => {
  const f = fixture(Buffer.alloc(2 * 1024 * 1024 + 1, 7)); let checks = 0, reads = 0;
  const stopped = new Error("TEST exact approval lease lost"), original = fs.readSync;
  context.mock.method(fs, "readSync", (...args: Parameters<typeof fs.readSync>) => {
    reads++; return original(...args);
  });
  try {
    assert.throws(() => verifyOpeningApprovalMedia({ core: f.row, review: { ...f.row, path: "/TEST/unopened" } }, () => {
      if (++checks === 4) throw stopped;
    }), (error) => error === stopped);
    assert.equal(reads, 1); assert.equal(checks, 4);
  } finally { f.cleanup(); }
});

test("guarded and default reader results remain identical, including retained bytes", () => {
  const f = fixture(); let checks = 0;
  try {
    const prior = observeCutPreviewFile(f.file, 1024, true);
    const guarded = observeCutPreviewFile(f.file, 1024, true, () => { checks++; });
    assert.deepEqual(guarded, prior); assert.deepEqual(guarded.bytes, f.bytes); assert.equal(checks, 3);
  } finally { f.cleanup(); }
});
