import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { planContentHash } from "../auto-edit-authority";

const root = mkdtempSync(path.join(os.tmpdir(), "sniper-authority-hash-"));
try {
  const planPath = path.join(root, "edit_plan.json");
  writeFileSync(planPath, JSON.stringify({
    planVersion: 2,
    _private: "ignored",
    title: "Café",
    graphicsTrack: [{ id: "g1", text: "A", x: 30.0 }],
    cutTrack: [],
  }));
  assert.equal(
    planContentHash(planPath),
    "db7bebe2a120cdcf84e01030226daa7fed66ddc3baa9150b2a95331bcff043c1",
    "TypeScript canonical hashing must match fingerprints.py",
  );
  console.log("auto-edit-authority.test.ts: all assertions passed");
} finally {
  rmSync(root, { recursive: true, force: true });
}
