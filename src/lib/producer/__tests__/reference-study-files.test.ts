import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { backupStudyOutputs, finishStudyBackup } from "../../../app/api/_lib/reference-study-files";

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "reference-study-backup-"));
try {
  const deep = path.join(dir, "deep_study.json");
  fs.writeFileSync(deep, "old-good");
  const backup = backupStudyOutputs(dir);
  fs.writeFileSync(deep, "partial-new");
  finishStudyBackup(dir, backup, false);
  assert.equal(fs.readFileSync(deep, "utf8"), "old-good");

  const next = backupStudyOutputs(dir);
  fs.writeFileSync(deep, "new-good");
  finishStudyBackup(dir, next, true);
  assert.equal(fs.readFileSync(deep, "utf8"), "new-good");
  assert.equal(fs.existsSync(next), false);
} finally {
  fs.rmSync(dir, { recursive: true, force: true });
}

console.log("reference-study-files.test.ts: all assertions passed");
