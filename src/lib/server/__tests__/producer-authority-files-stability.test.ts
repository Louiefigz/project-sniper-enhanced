import assert from "node:assert/strict";
import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import os from "node:os";
import path from "node:path";
import { readAuthorityJsonSync } from "../producer-authority-files";

const root = fs.realpathSync(
  fs.mkdtempSync(path.join(os.tmpdir(), "sniper-authority-read-")),
);
const authority = path.join(root, "authority.json");
const original = path.join(root, "authority.original.json");
const originalRead = fs.readFileSync;

try {
  fs.writeFileSync(authority, "{\"value\":\"original\"}");
  assert.deepEqual(readAuthorityJsonSync(authority), { value: "original" });

  let swapped = false;
  fs.readFileSync = ((...args: unknown[]): unknown => {
    const bytes = Reflect.apply(originalRead, fs, args) as Buffer;
    if (!swapped && typeof args[0] === "number") {
      fs.renameSync(authority, original);
      fs.writeFileSync(authority, "{\"value\":\"replacement\"}");
      swapped = true;
    }
    return bytes;
  }) as unknown as typeof fs.readFileSync;
  syncBuiltinESMExports();

  assert.throws(
    () => readAuthorityJsonSync(authority),
    /authority record changed while read/,
  );
  assert.equal(swapped, true, "test must replace the name after descriptor read");
} finally {
  fs.readFileSync = originalRead;
  syncBuiltinESMExports();
  fs.rmSync(root, { recursive: true, force: true });
}

console.log("producer authority stable-read tests passed");
