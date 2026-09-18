import assert from "node:assert/strict";
import {
  runCutRepairPreparation,
  type CutRepairPreparationServices,
} from "@/app/api/producer/ai-edit/cut-repair-prepare-runner";
import type { CutRepairDirectiveV1 } from
  "@/app/api/producer/ai-edit/cut-repair-route-policy";

const preparationHash = "a".repeat(64);
const directive: CutRepairDirectiveV1 = {
  schemaVersion: 1,
  operation: "cut.restoreSpeech",
  mode: "prepare",
  idempotencyKey: "71000000-0000-4000-8000-000000000001",
  requestedAt: "2026-07-30T12:00:00.000Z",
  target: { phrase: "restore this phrase", occurrence: 1 },
  alternateTake: {
    schemaVersion: 1,
    kind: "cut-repair-alternate-take-request",
    visualSpeechRegion: {
      xPpm: 250_000,
      yPpm: 420_000,
      widthPpm: 500_000,
      heightPpm: 300_000,
    },
  },
};

function services(existing: boolean) {
  let prepared = 0;
  let attached = 0;
  const value: CutRepairPreparationServices = {
    existing: () => existing ? {
      preparationHash,
      replayed: true,
    } : null,
    prepareNew: async () => {
      prepared += 1;
      return { preparationHash, replayed: false };
    },
    attachSelection: async (
      producerDir,
      manifestPath,
      observedDirective,
      response,
    ) => {
      attached += 1;
      assert.equal(producerDir, "/producer");
      assert.equal(manifestPath, "/producer/manifest.json");
      assert.equal(observedDirective.alternateTake, directive.alternateTake);
      assert.equal(response.preparationHash, preparationHash);
      return {
        ...response,
        alternateTakeSelection: { status: "selection-published" },
      };
    },
  };
  return {
    value,
    counts: () => ({ prepared, attached }),
  };
}

async function assertPath(existing: boolean): Promise<void> {
  const fixture = services(existing);
  const result = await runCutRepairPreparation(
    "/producer", "/producer/manifest.json", directive, fixture.value);
  assert.deepEqual(result.alternateTakeSelection, {
    status: "selection-published",
  });
  assert.deepEqual(fixture.counts(), {
    prepared: existing ? 0 : 1,
    attached: 1,
  });
}

async function main(): Promise<void> {
  await assertPath(false);
  await assertPath(true);
  console.log(
    "p2-cut-repair-alternate-take-prepare-wiring tests passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
