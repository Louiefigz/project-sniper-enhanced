import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { approvedFinal } from "../../../app/api/producer/project-status/route";
import {
  invalidateApprovedPreview,
  previewAuthorityInvalidated,
} from "../../server/auto-edit-quality-artifacts";
import { markLegacyQualityPolicy } from "../../server/auto-edit-quality-policy";

const root = mkdtempSync(path.join(os.tmpdir(), "sniper-preview-stale-reload-"));
try {
  const producer = path.join(root, "producer");
  mkdirSync(producer);
  writeFileSync(path.join(producer, "final.mp4"), "previous-approved-video");
  markLegacyQualityPolicy(producer, "fixture predates managed QC");
  assert.equal(approvedFinal(producer), true);
  invalidateApprovedPreview(producer, "ask-ai-edit");
  assert.equal(previewAuthorityInvalidated(producer), true);
  assert.equal(approvedFinal(producer), false,
    "a reload must keep the previous video hidden even for explicit legacy state");
} finally {
  rmSync(root, { recursive: true, force: true });
}

console.log("preview-stale-reload.test.ts: all assertions passed");
