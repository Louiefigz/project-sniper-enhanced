import assert from "node:assert/strict";
import {
  isWordSafeCutRepairIntent,
  parseCutRepairDirective,
} from "@/app/api/producer/ai-edit/cut-repair-route-policy";

const TARGET = {
  phrase: "the exact clipped phrase",
  occurrence: 1,
};

function directive(
  mode: "analyze" | "reopen" | "prepare" | "review" | "approve" | "execute",
) {
  return {
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    mode,
    target: TARGET,
  };
}

function reopenModeIsClosed(): void {
  const parsed = parseCutRepairDirective({
    ...directive("reopen"),
    idempotencyKey: "70000000-0000-4000-8000-000000000001",
    requestedAt: "2026-07-30T12:00:00.000Z",
  });
  assert.equal(parsed?.mode, "reopen");
  assert.equal(parsed?.packageHash, undefined);
  assert.throws(
    () => parseCutRepairDirective(directive("reopen")),
    /reopen requires a canonical UUID/,
  );
  assert.throws(
    () => parseCutRepairDirective({
      ...directive("reopen"),
      idempotencyKey: "70000000-0000-4000-8000-000000000001",
      requestedAt: "2026-07-30T12:00:00.000Z",
      packageHash: "a".repeat(64),
    }),
    /reopen cannot select an execution package/,
  );
}

function approvalModeIsClosed(): void {
  const preparationHash = "a".repeat(64);
  const audition = {
    schemaVersion: 1,
    kind: "cut-repair-operator-audition-attestation",
    preparationHash,
    candidateDescriptorHash: "b".repeat(64),
    candidateSha256: "c".repeat(64),
    operatorReceiptId: "operator-session-1",
    reviewedAt: "2026-07-29T12:01:00.000Z",
    decision: "approved",
    reportedDamageResolved: true,
  };
  const parsed = parseCutRepairDirective({
    ...directive("approve"),
    packageHash: preparationHash,
    idempotencyKey: "72000000-0000-4000-8000-000000000001",
    requestedAt: "2026-07-29T12:02:00.000Z",
    audition,
  });
  assert.equal(parsed?.mode, "approve");
  assert.deepEqual(parsed?.audition, audition);
  assert.equal(
    parseCutRepairDirective({
      ...directive("review"),
      packageHash: preparationHash,
    })?.mode,
    "review",
  );
  assert.throws(
    () => parseCutRepairDirective({
      ...directive("approve"),
      packageHash: preparationHash,
      idempotencyKey: "72000000-0000-4000-8000-000000000001",
      requestedAt: "2026-07-29T12:02:00.000Z",
    }),
    /approve requires operator audition/,
  );
  assert.throws(
    () => parseCutRepairDirective({
      ...directive("review"),
      packageHash: preparationHash,
      audition,
    }),
    /audition is only valid for approve/,
  );
  assert.throws(
    () => parseCutRepairDirective({
      ...directive("approve"),
      packageHash: preparationHash,
      idempotencyKey: "72000000-0000-4000-8000-000000000001",
      requestedAt: "2026-07-29T12:02:00.000Z",
      audition: { ...audition, callerReceiptHash: "d".repeat(64) },
    }),
    /unsupported or missing fields/,
  );
}

function prepareModeIsClosed(): void {
  const alternateTake = {
    schemaVersion: 1,
    kind: "cut-repair-alternate-take-request",
    visualSpeechRegion: {
      xPpm: 250_000,
      yPpm: 420_000,
      widthPpm: 500_000,
      heightPpm: 300_000,
    },
  };
  const parsed = parseCutRepairDirective({
    ...directive("prepare"),
    idempotencyKey: "71000000-0000-4000-8000-000000000001",
    requestedAt: "2026-07-29T12:00:00.000Z",
    alternateTake,
  });
  assert.equal(parsed?.mode, "prepare");
  assert.equal(
    parsed?.idempotencyKey,
    "71000000-0000-4000-8000-000000000001",
  );
  assert.equal(parsed?.packageHash, undefined);
  assert.deepEqual(parsed?.alternateTake, alternateTake);
  assert.throws(
    () => parseCutRepairDirective(directive("prepare")),
    /prepare requires a canonical UUID/,
  );
  assert.throws(
    () => parseCutRepairDirective({
      ...directive("prepare"),
      idempotencyKey: "71000000-0000-4000-8000-000000000001",
    }),
    /prepare requires requestedAt/,
  );
  assert.throws(
    () => parseCutRepairDirective({
      ...directive("prepare"),
      idempotencyKey: "71000000-0000-4000-8000-000000000001",
      requestedAt: "2026-07-29T12:00:00.000Z",
      packageHash: "a".repeat(64),
    }),
    /prepare cannot promote a package/,
  );
  assert.throws(
    () => parseCutRepairDirective({
      ...directive("prepare"),
      idempotencyKey: "71000000-0000-4000-8000-000000000001",
      requestedAt: "2026-07-29T12:00:00.000Z",
      alternateTake: { ...alternateTake, retakeId: 0 },
    }),
    /unsupported or missing fields/,
  );
  assert.throws(
    () => parseCutRepairDirective({
      ...directive("analyze"),
      alternateTake,
    }),
    /alternateTake is only valid for prepare/,
  );
  assert.throws(
    () => parseCutRepairDirective({
      ...directive("prepare"),
      idempotencyKey: "71000000-0000-4000-8000-000000000001",
      requestedAt: "2026-07-29T12:00:00.000Z",
      alternateTake: {
        ...alternateTake,
        visualSpeechRegion: {
          ...alternateTake.visualSpeechRegion,
          widthPpm: 800_000,
        },
      },
    }),
    /escapes the normalized frame/,
  );
}

function promotionIdentityCannotLeakAcrossModes(): void {
  assert.throws(
    () => parseCutRepairDirective({
      ...directive("analyze"),
      idempotencyKey: "71000000-0000-4000-8000-000000000001",
    }),
    /request identity is only valid for reopen, prepare, or approve/,
  );
  assert.throws(
    () => parseCutRepairDirective({
      ...directive("execute"),
      packageHash: "a".repeat(64),
      requestedAt: "2026-07-29T12:00:00.000Z",
    }),
    /request identity is only valid for reopen, prepare, or approve/,
  );
  assert.throws(
    () => parseCutRepairDirective(directive("execute")),
    /execute requires packageHash/,
  );
  assert.throws(
    () => parseCutRepairDirective({
      ...directive("analyze"),
      packageHash: "a".repeat(64),
    }),
    /analyze cannot select an execution package/,
  );
}

function damagedSpeechDetectionRemainsConservative(): void {
  assert.equal(
    isWordSafeCutRepairIntent("You stepped on one of my words here."),
    true,
  );
  assert.equal(
    isWordSafeCutRepairIntent("Trim the dead air after this section."),
    false,
  );
  assert.equal(parseCutRepairDirective({
    schemaVersion: 1,
    operation: "SetGraphicTextV1",
  }), null);
}

prepareModeIsClosed();
reopenModeIsClosed();
approvalModeIsClosed();
promotionIdentityCannotLeakAcrossModes();
damagedSpeechDetectionRemainsConservative();
console.log("p2-cut-repair-route-policy tests passed");
