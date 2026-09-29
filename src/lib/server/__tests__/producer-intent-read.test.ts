import assert from "node:assert/strict";
import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import path from "node:path";
import {
  authorityKey,
  writeMutableAuthorityJsonSync,
} from "../producer-authority-files";
import { materializeProducerCommitSync } from "../producer-revision-materialize";
import {
  recoverProducerCommitSync,
  unresolvedProducerIntentsSync,
} from "../producer-revision-recovery";
import {
  bootstrapRevisionFixture as bootstrap,
  cleanRevisionFixture as clean,
  revisionCommitInput as commitInput,
} from "./_producer-revision-fixture";

// M-061b (X94): two processes recovering one commit replace its intent by atomic rename (transitionIntent)
// while the other reads it. The replacement cases replace the target right after the reader opens it, so the
// reader's descriptor holds the old file and the path names the new one: the whole race, every time.
// Cases 1-4 fail on the base and with M-061a alone. Case 5 pins the single-link condition: a linked intent
// gets only M-061a's 24 waits, never an intent-level retry (624). Case 6: a replaced non-intent record
// is refused at once.
interface Replacement { target: string; times: number; replaced: number; waits: number }

function replacingOnOpen<T>(replacement: Replacement, action: () => T): T {
  const open = fs.openSync;
  const wait = Atomics.wait;
  const value: unknown = JSON.parse(fs.readFileSync(replacement.target, "utf8"));
  fs.openSync = ((...args: unknown[]) => {
    const descriptor = Reflect.apply(open, fs, args) as number;
    if (args[0] === replacement.target && replacement.replaced < replacement.times) {
      replacement.replaced += 1;
      writeMutableAuthorityJsonSync(replacement.target, value);
    }
    return descriptor;
  }) as unknown as typeof fs.openSync;
  Atomics.wait = ((...args: unknown[]) => {
    replacement.waits += 1;
    return Reflect.apply(wait, Atomics, args);
  }) as typeof Atomics.wait;
  syncBuiltinESMExports();
  try {
    return action();
  } finally {
    fs.openSync = open;
    Atomics.wait = wait;
    syncBuiltinESMExports();
  }
}

function staged(fixture: ReturnType<typeof bootstrap>, variant: string) {
  const input = commitInput(fixture.producer, fixture.genesis, variant);
  const { paths, record } = materializeProducerCommitSync(input);
  const file = (directory: string) => path.join(directory, `${authorityKey(record.idempotencyKey)}.json`);
  return { input, record, intent: file(paths.intents), idempotency: file(paths.idempotency) };
}

const REPLACED_READS: [string, (fixture: ReturnType<typeof bootstrap>) => void][] = [
  ["readIntent", (fixture) => {
    const { intent, record } = staged(fixture, "1");
    const replacement = { target: intent, times: 1, replaced: 0, waits: 0 };
    const outcome = replacingOnOpen(replacement,
      () => recoverProducerCommitSync(fixture.producer, record.idempotencyKey));
    assert.deepEqual([outcome.status, replacement.replaced], ["committed", 1]);
  }],
  ["unresolvedProducerIntentsSync", (fixture) => {
    const { intent, record } = staged(fixture, "2");
    const replacement = { target: intent, times: 1, replaced: 0, waits: 0 };
    const open = replacingOnOpen(replacement, () => unresolvedProducerIntentsSync(fixture.producer));
    assert.deepEqual([open.map((row) => row.idempotencyKey), replacement.replaced], [[record.idempotencyKey], 1]);
  }],
  ["materialize", (fixture) => {
    const { input, intent } = staged(fixture, "3");
    const replacement = { target: intent, times: 1, replaced: 0, waits: 0 };
    const again = replacingOnOpen(replacement, () => materializeProducerCommitSync(input));
    assert.deepEqual([again.replayed, again.intent.state, replacement.replaced], [true, "PREPARING", 1]);
  }],
  ["an intent replaced on every read is refused after the bounded wait", (fixture) => {
    const { intent, record } = staged(fixture, "4");
    const replacement = { target: intent, times: Infinity, replaced: 0, waits: 0 };
    assert.throws(() => replacingOnOpen(replacement,
      () => recoverProducerCommitSync(fixture.producer, record.idempotencyKey)), /authority record changed while/);
    assert.deepEqual([replacement.replaced, replacement.waits], [25, 24]);
  }],
  ["an intent with a lasting second link gets only the reader's 24 waits", (fixture) => {
    const { intent, record } = staged(fixture, "6");
    fs.linkSync(intent, path.join(path.dirname(intent), `.${path.basename(intent)}.held.tmp`));
    const replacement = { target: intent, times: 0, replaced: 0, waits: 0 };
    assert.throws(() => replacingOnOpen(replacement,
      () => recoverProducerCommitSync(fixture.producer, record.idempotencyKey)), /authority record changed while open/);
    assert.equal(replacement.waits, 24);
  }],
  ["a replaced idempotency record is refused at once", (fixture) => {
    const { idempotency, record } = staged(fixture, "5");
    const replacement = { target: idempotency, times: 1, replaced: 0, waits: 0 };
    assert.throws(() => replacingOnOpen(replacement,
      () => recoverProducerCommitSync(fixture.producer, record.idempotencyKey)), /authority record changed while/);
    assert.deepEqual([replacement.replaced, replacement.waits], [1, 0]);
  }],
];

const failures = REPLACED_READS.flatMap(([name, read]) => {
  const fixture = bootstrap();
  try {
    read(fixture);
    return [];
  } catch (error) {
    return [`${name}: ${error instanceof Error ? error.message : String(error)}`];
  } finally {
    clean(fixture.root);
  }
});
assert.deepEqual(failures, []);
console.log("producer intent read tests passed");
