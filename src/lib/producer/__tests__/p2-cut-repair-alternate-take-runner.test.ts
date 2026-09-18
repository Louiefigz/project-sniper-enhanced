import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  ensureAlternateTakeSelection,
  type AlternateTakeRunnerServices,
} from "@/app/api/producer/ai-edit/cut-repair-alternate-take-runner";

const preparationHash = "a".repeat(64);
const request = {
  schemaVersion: 1,
  kind: "cut-repair-alternate-take-request",
  visualSpeechRegion: {
    xPpm: 250_000,
    yPpm: 420_000,
    widthPpm: 500_000,
    heightPpm: 300_000,
  },
} as const;

function result(value: Record<string, unknown>) {
  return {
    code: 0,
    stdout: JSON.stringify(value),
    stderr: "",
  };
}

function selectionServices(): AlternateTakeRunnerServices {
  return {
    run: async (script, args) => {
      assert.match(script, /alternate_take_controller\.py$/u);
      assert.deepEqual(args.slice(0, 3), [
        "/producer", preparationHash, "/producer/manifest.json",
      ]);
      const input = JSON.parse(readFileSync(args[3], "utf8"));
      assert.deepEqual(input, {
        schemaVersion: 1,
        kind: "cut-repair-alternate-take-controller-input",
        alternateTake: request,
      });
      return result({
        ok: true,
        status: "selection-published",
        preparationHash,
        selectionReceiptHash: "b".repeat(64),
        selectionHash: "c".repeat(64),
        selectionReceiptPath:
          "/producer/.sniper-cut-repair-staging/attempt/alternate-take-selection.json",
        candidateSetHash: "d".repeat(64),
        selectedCandidateId: "take-" + "e".repeat(24),
        visualSpeechRegion: {
          heightPpm: request.visualSpeechRegion.heightPpm,
          widthPpm: request.visualSpeechRegion.widthPpm,
          yPpm: request.visualSpeechRegion.yPpm,
          xPpm: request.visualSpeechRegion.xPpm,
        },
      });
    },
  };
}

async function pictureSelectionUsesControllerOwnedIdentity(): Promise<void> {
  const selected = await ensureAlternateTakeSelection({
    producerDir: "/producer",
    preparationHash,
    manifestPath: "/producer/manifest.json",
    request,
  }, selectionServices());
  assert.equal(selected.status, "selection-published");
  assert.equal(
    selected.selectedCandidateId, "take-" + "e".repeat(24));
}

async function audioOnlyReplayHasNoVisualRequest(): Promise<void> {
  const services: AlternateTakeRunnerServices = {
    run: async (_script, args) => {
      const input = JSON.parse(readFileSync(args[3], "utf8"));
      assert.equal(input.alternateTake, null);
      return result({
        ok: true,
        status: "not-applicable-audio-only",
        preparationHash,
      });
    },
  };
  const selected = await ensureAlternateTakeSelection({
    producerDir: "/producer",
    preparationHash,
    manifestPath: "/producer/manifest.json",
  }, services);
  assert.equal(selected.status, "not-applicable-audio-only");
}

async function staleControllerOutputIsRejected(): Promise<void> {
  const services = selectionServices();
  const stale: AlternateTakeRunnerServices = {
    run: async (...args) => {
      const value = await services.run(...args);
      const row = JSON.parse(value.stdout);
      row.preparationHash = "f".repeat(64);
      return result(row);
    },
  };
  await assert.rejects(
    ensureAlternateTakeSelection({
      producerDir: "/producer",
      preparationHash,
      manifestPath: "/producer/manifest.json",
      request,
    }, stale),
    /result is stale/,
  );
}

async function main(): Promise<void> {
  await pictureSelectionUsesControllerOwnedIdentity();
  await audioOnlyReplayHasNoVisualRequest();
  await staleControllerOutputIsRejected();
  console.log("p2-cut-repair-alternate-take-runner tests passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
