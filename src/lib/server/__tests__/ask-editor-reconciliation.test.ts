import assert from "node:assert/strict";
import { mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  assertNoPromotionReconciliation,
  QC_PROMOTION_RECONCILIATION_FILE,
  SURGICAL_RECONCILIATION_CANDIDATE_FILE,
  SURGICAL_RECONCILIATION_FILE,
} from "../ask-editor-reconciliation";

const dir = mkdtempSync(path.join(os.tmpdir(), "sniper-reconciliation-node-"));
try {
  const evidence = path.join(dir, SURGICAL_RECONCILIATION_FILE);
  const candidate = path.join(dir, SURGICAL_RECONCILIATION_CANDIDATE_FILE);
  symlinkSync(path.join(dir, "missing-evidence"), evidence);
  assert.throws(
    () => assertNoPromotionReconciliation(dir),
    /incomplete|unreadable/,
    "a dangling evidence symlink must not look absent",
  );
  rmSync(evidence);
  symlinkSync(path.join(dir, "missing-candidate"), candidate);
  assert.throws(
    () => assertNoPromotionReconciliation(dir),
    /incomplete|unreadable/,
    "a dangling candidate symlink must not look absent",
  );
  rmSync(candidate);
  writeFileSync(
    path.join(dir, QC_PROMOTION_RECONCILIATION_FILE),
    '{"status":"reconciliation-required"}\n',
  );
  assert.throws(
    () => assertNoPromotionReconciliation(dir),
    /QC promotion has unresolved/,
  );
} finally {
  rmSync(dir, { recursive: true, force: true });
}

console.log("ask-editor-reconciliation.test.ts: passed");
