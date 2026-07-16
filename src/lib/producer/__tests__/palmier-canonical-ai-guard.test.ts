import assert from "node:assert/strict";
import {
  guardPalmierCanonicalForAiEdit,
  PalmierCanonicalError,
} from "../../../app/api/producer/ai-edit/palmier-canonical";
import { guardPalmierForAutoEditLaunch } from "../../../app/api/producer/auto-edit/route";

async function main(): Promise<void> {
  let called = false;
  await guardPalmierCanonicalForAiEdit("/project/producer", {
    stateExists: () => false,
    run: async () => {
      called = true;
      return { code: 0, verdict: { ok: true } };
    },
  });
  assert.equal(called, false, "projects without Palmier state remain plan-first");

  await guardPalmierCanonicalForAiEdit("/project/producer", {
    stateExists: () => true,
    run: async () => ({ code: 0, verdict: {
      ok: true, authority: "palmier", timelineId: "current",
    } }),
  });

  await assert.rejects(
    guardPalmierCanonicalForAiEdit("/project/producer", {
      stateExists: () => true,
      run: async () => ({ code: 65, verdict: {
        ok: false, status: "manual-baseline",
        error: "manual Palmier revision preserved",
      } }),
    }),
    (error: unknown) => error instanceof PalmierCanonicalError
      && error.statusCode === 409
      && error.message.includes("preserved"),
  );

  let legacyCalls = 0;
  await guardPalmierForAutoEditLaunch("/project/producer", {
    classify: () => ({ state: "managed" }),
    legacyGuard: async () => { legacyCalls += 1; },
  });
  assert.equal(legacyCalls, 0,
    "a managed Palmier worker must reconcile the manual baseline itself");

  await guardPalmierForAutoEditLaunch("/project/producer", {
    classify: () => ({ state: "absent" }),
    legacyGuard: async () => { legacyCalls += 1; },
  });
  assert.equal(legacyCalls, 1, "plan-first projects retain the legacy guard");

  await assert.rejects(
    guardPalmierForAutoEditLaunch("/project/producer", {
      classify: () => ({ state: "invalid", error: "Palmier state is unreadable." }),
      legacyGuard: async () => { legacyCalls += 1; },
    }),
    (error: unknown) => error instanceof PalmierCanonicalError
      && error.statusCode === 409
      && error.message.includes("unprovable Palmier working head"),
  );
  assert.equal(legacyCalls, 1, "invalid managed state fails before either writer starts");

  await assert.rejects(
    guardPalmierCanonicalForAiEdit("/project/producer", {
      stateExists: () => true,
      run: async () => ({ code: 69, verdict: {
        ok: false, status: "unavailable", error: "Palmier is closed",
      } }),
    }),
    (error: unknown) => error instanceof PalmierCanonicalError
      && error.statusCode === 503,
  );
  console.log("palmier-canonical-ai-guard.test.ts: all assertions passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
