import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { writeContentAddressedJsonSync } from "../content-addressed-json";

const root = mkdtempSync(path.join(os.tmpdir(), "sniper-content-json-"));

try {
  const directory = path.join(root, "objects");
  const first = writeContentAddressedJsonSync(directory, {
    z: 3, nested: { beta: true, alpha: "value" },
  });
  const bytes = readFileSync(first.path);
  assert.equal(
    createHash("sha256").update(bytes).digest("hex"),
    first.hash,
  );
  assert.equal(first.reused, false);

  const repeated = writeContentAddressedJsonSync(directory, {
    nested: { alpha: "value", beta: true }, z: 3,
  });
  assert.equal(repeated.hash, first.hash);
  assert.equal(repeated.path, first.path);
  assert.equal(repeated.reused, true);

  writeFileSync(first.path, "tampered");
  assert.throws(
    () => writeContentAddressedJsonSync(directory, {
      z: 3, nested: { beta: true, alpha: "value" },
    }),
    /bytes conflict/,
  );

  const outside = path.join(root, "outside");
  const linked = path.join(root, "linked-objects");
  mkdirSync(outside);
  symlinkSync(outside, linked, "dir");
  assert.throws(
    () => writeContentAddressedJsonSync(linked, { escape: true }),
    /must be a real directory/,
  );
  assert.throws(
    () => writeContentAddressedJsonSync(
      path.join(linked, "nested"), { parentEscape: true },
    ),
    /parent must be a real directory/,
  );
  assert.deepEqual(readdirSync(outside), []);
} finally {
  rmSync(root, { recursive: true, force: true });
}

console.log("content-addressed JSON tests passed");
