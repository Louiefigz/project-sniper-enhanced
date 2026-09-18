import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { test } from "node:test";
import { decodeText, readBytes, readText } from "./files";

function fixture() {
  const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sniper-import-read-")));
  const file = path.join(dir, "source.html"); fs.writeFileSync(file, "valid source");
  return { dir, file, cleanup: () => fs.rmSync(dir, { recursive: true, force: true }) };
}

test("source reads reject invalid UTF-8, oversize, symlinks, hardlinks and FIFO without blocking", () => {
  const f = fixture();
  try {
    assert.equal(readText(f.file), "valid source");
    assert.throws(() => decodeText(Buffer.from([0xff])), /valid UTF-8/u);
    assert.throws(() => readBytes(f.file, 1), /bounded regular file/u);
    const link = path.join(f.dir, "link"); fs.symlinkSync(f.file, link);
    assert.throws(() => readBytes(link), /symlinks/u);
    const hard = path.join(f.dir, "hard"); fs.linkSync(f.file, hard);
    assert.throws(() => readBytes(f.file), /hardlinks/u);
    assert.throws(() => readBytes(hard), /hardlinks/u);
    const fifo = path.join(f.dir, "fifo"); execFileSync("mkfifo", [fifo]);
    const start = performance.now();
    assert.throws(() => readBytes(fifo), /regular file/u);
    assert.ok(performance.now() - start < 1_000);
  } finally { f.cleanup(); }
});

test("same-size file mutation and parent replacement during read fail the exact binding", () => {
  const f = fixture(); const originalRead = fs.readSync;
  try {
    fs.readSync = ((...args: Parameters<typeof fs.readSync>) => {
      const result = Reflect.apply(originalRead, fs, args);
      fs.writeFileSync(f.file, "other source");
      return result;
    }) as typeof fs.readSync;
    assert.throws(() => readBytes(f.file), /changed while reading/u);
  } finally { fs.readSync = originalRead; f.cleanup(); }
  const next = fixture();
  try {
    fs.readSync = ((...args: Parameters<typeof fs.readSync>) => {
      const result = Reflect.apply(originalRead, fs, args);
      fs.renameSync(next.dir, `${next.dir}-moved`); fs.mkdirSync(next.dir);
      fs.writeFileSync(next.file, "valid source");
      return result;
    }) as typeof fs.readSync;
    assert.throws(() => readBytes(next.file), /changed while reading/u);
  } finally {
    fs.readSync = originalRead; next.cleanup();
    fs.rmSync(`${next.dir}-moved`, { recursive: true, force: true });
  }
});
