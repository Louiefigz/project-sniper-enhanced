import assert from "node:assert/strict";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  AiEditInvalidationError,
  invalidateAiEditAuthority,
} from "../../../app/api/producer/ai-edit/authority";

async function main(): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-ai-edit-invalidation-"));
  try {
  const approval = path.join(root, ".sniper-qc-approved.json");
  writeFileSync(approval, "approved");
  let release!: () => void;
  let action = "";
  const pending = invalidateAiEditAuthority(root, {
    invalidatePreview: () => rmSync(approval, { force: true }),
    palmierStateExists: () => true,
    invalidatePalmier: async (_dir, requested) => {
      action = requested;
      await new Promise<void>((resolve) => { release = resolve; });
      return { code: 0, verdict: { ok: true, action: "invalidate", ownership: "sniper" } };
    },
  });
  assert.equal(existsSync(approval), false,
    "disk preview approval must be revoked synchronously before awaiting Palmier");
  assert.equal(action, "invalidate");
  release();
  await pending;

  writeFileSync(approval, "approved-again");
  let called = false;
  await invalidateAiEditAuthority(root, {
    invalidatePreview: () => rmSync(approval, { force: true }),
    palmierStateExists: () => false,
    invalidatePalmier: async () => {
      called = true;
      return { code: 0, verdict: { ok: true } };
    },
  });
  assert.equal(called, false, "projects without Palmier state need no sidecar mutation");
  assert.equal(existsSync(approval), false);

  writeFileSync(approval, "approved-third-time");
  await assert.rejects(
    invalidateAiEditAuthority(root, {
      invalidatePreview: () => rmSync(approval, { force: true }),
      palmierStateExists: () => true,
      invalidatePalmier: async () => ({
        code: 75, verdict: { ok: false, error: "sync active" },
      }),
    }),
    (error: unknown) => error instanceof AiEditInvalidationError && error.retryable,
  );
  assert.equal(existsSync(approval), false,
    "a Palmier lock race must remain fail-closed for preview authority");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("ai-edit-authority-invalidation.test.ts: all assertions passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
