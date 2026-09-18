import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { resolveProducerAuthorityHeadSync } from "../producer-revision-head";
import { materializeProducerCommitSync } from "../producer-revision-materialize";
import {
  reconcileProducerAuthoritySync,
  recoverProducerCommitSync,
} from "../producer-revision-recovery";
import { commitProducerRevisionSync } from "../producer-revision-store";
import {
  authorityKey,
  producerAuthorityPaths,
  readAuthorityJsonSync,
} from "../producer-authority-files";
import {
  bootstrapRevisionFixture as bootstrap,
  cleanRevisionFixture as clean,
  revisionCommitInput as commitInput,
} from "./_producer-revision-fixture";

function runWorker(workerPath: string, inputPath: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(
      process.execPath,
      ["--import", "tsx", workerPath, inputPath],
      { cwd: process.cwd(), stdio: ["ignore", "pipe", "pipe"] },
    );
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk: Buffer) => { stdout += chunk.toString(); });
    child.stderr.on("data", (chunk: Buffer) => { stderr += chunk.toString(); });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve(stdout.trim());
      else reject(new Error(`revision worker exited ${code}: ${stderr}`));
    });
  });
}

{
  const fixture = bootstrap();
  try {
    const input = commitInput(fixture.producer, fixture.genesis, "1");
    const first = commitProducerRevisionSync(input);
    assert.equal(first.status, "committed");
    assert.equal(resolveProducerAuthorityHeadSync(fixture.producer), first.childRevisionHash);
    const replay = commitProducerRevisionSync(input);
    assert.equal(replay.status, "replayed");
    assert.equal(replay.receiptHash, first.receiptHash);
    assert.throws(
      () => commitProducerRevisionSync({
        ...input,
        request: { ...input.request, rawIntent: "Different exact request." },
      }),
      /idempotency key/,
    );
    const stale = commitProducerRevisionSync(
      commitInput(fixture.producer, fixture.genesis, "2"),
    );
    assert.equal(stale.status, "aborted");
    assert.equal(resolveProducerAuthorityHeadSync(fixture.producer), first.childRevisionHash);
  } finally {
    clean(fixture.root);
  }
}

for (const boundary of [
  "after-materialized",
  "after-candidates-proved",
  "after-local-commit-intent",
  "after-advance",
  "after-head",
  "after-receipt",
] as const) {
  const fixture = bootstrap();
  try {
    const input = commitInput(fixture.producer, fixture.genesis, "3");
    assert.throws(
      () => commitProducerRevisionSync(input, {
        after: (current) => {
          if (current === boundary) throw new Error(`fault at ${boundary}`);
        },
      }),
      new RegExp(`fault at ${boundary}`),
    );
    const recovered = reconcileProducerAuthoritySync(fixture.producer);
    assert.equal(recovered.length, 1);
    assert.equal(recovered[0].status, "committed");
    assert.equal(
      resolveProducerAuthorityHeadSync(fixture.producer),
      recovered[0].childRevisionHash,
    );
    assert.equal(commitProducerRevisionSync(input).status, "replayed");
  } finally {
    clean(fixture.root);
  }
}

{
  const fixture = bootstrap();
  try {
    const input = commitInput(fixture.producer, fixture.genesis, "8");
    assert.throws(
      () => commitProducerRevisionSync(input, {
        after: (current) => {
          if (current === "after-committed") throw new Error("fault after committed");
        },
      }),
      /fault after committed/,
    );
    assert.deepEqual(reconcileProducerAuthoritySync(fixture.producer), []);
    assert.equal(commitProducerRevisionSync(input).status, "replayed");
  } finally {
    clean(fixture.root);
  }
}

{
  const fixture = bootstrap();
  try {
    const first = materializeProducerCommitSync(
      commitInput(fixture.producer, fixture.genesis, "4"),
    );
    const second = materializeProducerCommitSync(
      commitInput(fixture.producer, fixture.genesis, "5"),
    );
    assert.equal(
      recoverProducerCommitSync(fixture.producer, first.record.idempotencyKey).status,
      "committed",
    );
    assert.equal(
      recoverProducerCommitSync(fixture.producer, second.record.idempotencyKey).status,
      "aborted",
    );
    assert.equal(
      resolveProducerAuthorityHeadSync(fixture.producer),
      first.record.childRevisionHash,
    );
  } finally {
    clean(fixture.root);
  }
}

{
  const fixture = bootstrap();
  try {
    const staged = materializeProducerCommitSync(
      commitInput(fixture.producer, fixture.genesis, "6"),
    );
    const paths = producerAuthorityPaths(fixture.producer);
    fs.rmSync(path.join(
      paths.intents,
      `${authorityKey(staged.record.idempotencyKey)}.json`,
    ));
    const recovered = reconcileProducerAuthoritySync(fixture.producer);
    assert.equal(recovered[0].status, "committed");
  } finally {
    clean(fixture.root);
  }
}

{
  const fixture = bootstrap();
  try {
    const input = commitInput(fixture.producer, fixture.genesis, "a");
    const committed = commitProducerRevisionSync(input);
    assert.equal(committed.status, "committed");
    const paths = producerAuthorityPaths(fixture.producer);
    const intentPath = path.join(
      paths.intents,
      `${authorityKey(input.request.idempotencyKey)}.json`,
    );
    const intent = readAuthorityJsonSync(intentPath) as Record<string, unknown>;
    const staged = materializeProducerCommitSync(input);
    fs.writeFileSync(intentPath, JSON.stringify({
      ...intent,
      receiptHash: staged.record.artifactHashes.receiptDraft,
    }));
    assert.throws(
      () => commitProducerRevisionSync(input),
      /committed receipt does not match/,
    );
  } finally {
    clean(fixture.root);
  }
}

async function concurrentExactRequestConverges(): Promise<void> {
  const fixture = bootstrap();
  try {
    const input = commitInput(fixture.producer, fixture.genesis, "9");
    const inputPath = path.join(fixture.root, "same-request.json");
    fs.writeFileSync(inputPath, JSON.stringify(input));
    const workerPath = path.join(
      path.dirname(fileURLToPath(import.meta.url)),
      "helpers",
      "producer-revision-worker.ts",
    );
    const results = await Promise.all([
      runWorker(workerPath, inputPath),
      runWorker(workerPath, inputPath),
    ]);
    const outcomes = results.map((value) => JSON.parse(value) as {
      status: string;
      childRevisionHash: string;
      receiptHash: string;
    });
    assert.equal(new Set(outcomes.map((row) => row.childRevisionHash)).size, 1);
    assert.equal(new Set(outcomes.map((row) => row.receiptHash)).size, 1);
    assert.ok(outcomes.every((row) => ["committed", "replayed"].includes(row.status)));
  } finally {
    clean(fixture.root);
  }
}

concurrentExactRequestConverges()
  .then(() => console.log("producer-revision-store tests passed"))
  .catch((error: unknown) => {
    console.error(error);
    process.exitCode = 1;
  });
