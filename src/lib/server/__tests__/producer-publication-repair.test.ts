import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import path from "node:path";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
  writeAuthorityObjectSync,
} from "../producer-authority-files";
import {
  repairPublicationLeftoversSync,
  type PublicationRepair,
} from "../producer-publication-repair";
import {
  initializeProducerAuthoritySync,
  resolveProducerAuthorityHeadSync,
} from "../producer-revision-head";
import { materializeProducerCommitSync } from "../producer-revision-materialize";
import { reconcileProducerAuthoritySync } from "../producer-revision-recovery";
import { stageRevision as stage, type RevisionFixture } from "./_authority-publication-hold";
import {
  bootstrapRevisionFixture as bootstrap,
  cleanRevisionFixture as clean,
  genesisRevision,
  GENESIS_PLAN,
} from "./_producer-revision-fixture";

// M-061c (X110): a publisher killed between its link and its unlink leaves `.<name>.<uuid>.tmp` on the same
// file as the published name. `crashed` recreates exactly that state. Each case shows the reader refusing the
// record, the sweep (or the store's open or recovery, which runs it) removing only that name, and the next
// read succeeding. Before M-061c nothing removed the name, so every repair case failed.

/** The state a publisher leaves if it dies between `linkSync` and `rmSync`: a same-inode temporary name. */
function crashed(published: string, stem = path.basename(published)): string {
  const temporary = path.join(path.dirname(published), `.${stem}.${randomUUID()}.tmp`);
  fs.linkSync(published, temporary);
  return temporary;
}

const REPAIRS: [string, (fixture: RevisionFixture) => void][] = [
  ["an object", (fixture) => {
    const { paths, record } = stage(fixture, "a");
    const hash = record.childRevisionHash;
    const leftover = crashed(path.join(paths.objects.revisions, `${hash}.json`), hash);
    assert.throws(() => assertObjectHashSync(paths.objects.revisions, hash), /changed while open/);
    assert.deepEqual(repairPublicationLeftoversSync(paths), { removed: [leftover], kept: [] });
    const child = assertObjectHashSync(paths.objects.revisions, hash) as { parentRevisionHash: unknown };
    assert.equal(child.parentRevisionHash, fixture.genesis);
  }],
  ["an advance", (fixture) => {
    const { advance, paths, record } = stage(fixture, "b");
    const leftover = crashed(advance());
    assert.throws(() => resolveProducerAuthorityHeadSync(fixture.producer), /changed while open/);
    assert.deepEqual(repairPublicationLeftoversSync(paths), { removed: [leftover], kept: [] });
    assert.equal(resolveProducerAuthorityHeadSync(fixture.producer), record.childRevisionHash);
  }],
  ["GENESIS, repaired where the store opens", (fixture) => {
    const leftover = crashed(path.join(producerAuthorityPaths(fixture.producer).advances, "GENESIS.json"));
    assert.throws(() => resolveProducerAuthorityHeadSync(fixture.producer), /changed while open/);
    const reopened = initializeProducerAuthoritySync(fixture.producer, genesisRevision(), GENESIS_PLAN);
    assert.deepEqual([reopened.revisionHash, reopened.reused, fs.existsSync(leftover)], [fixture.genesis, true, false]);
  }],
  ["an idempotency record", (fixture) => {
    const { idempotency, input, paths } = stage(fixture, "d");
    const leftover = crashed(idempotency);
    assert.throws(() => materializeProducerCommitSync(input), /changed while open/);
    assert.deepEqual(repairPublicationLeftoversSync(paths), { removed: [leftover], kept: [] });
    assert.equal(materializeProducerCommitSync(input).replayed, true);
  }],
  ["an advance, repaired where the store recovers", (fixture) => {
    const { advance, record } = stage(fixture, "e");
    const leftover = crashed(advance());
    const recovered = reconcileProducerAuthoritySync(fixture.producer);
    assert.deepEqual([recovered.map((row) => row.status), fs.existsSync(leftover)], [["committed"], false]);
    assert.equal(resolveProducerAuthorityHeadSync(fixture.producer), record.childRevisionHash);
  }],
  ["names that are not a crashed publication are left, and an outside link stays refused by name", (fixture) => {
    const { paths, record } = stage(fixture, "f");
    const objects = paths.objects.revisions;
    const published = path.join(objects, `${record.childRevisionHash}.json`);
    const unlinked = path.join(objects, `.${"f".repeat(64)}.${randomUUID()}.tmp`);
    fs.writeFileSync(unlinked, "{}");
    const copy = path.join(objects, `.${record.childRevisionHash}.${randomUUID()}.tmp`);
    fs.copyFileSync(published, copy);
    fs.linkSync(published, path.join(objects, "alias-of-child.json"));
    const repair = repairPublicationLeftoversSync(paths);
    assert.deepEqual([repair.removed, [...repair.kept].sort()], [[], [unlinked, copy].sort()]);
    assert.ok(fs.existsSync(unlinked) && fs.existsSync(copy));
    assert.throws(() => assertObjectHashSync(objects, record.childRevisionHash),
      new RegExp(`changed while open: .*${record.childRevisionHash}\\.json`));
  }],
  ["a live publisher swept inside its link window still succeeds", (fixture) => {
    const paths = producerAuthorityPaths(fixture.producer);
    const remove = fs.rmSync;
    let swept: PublicationRepair | undefined;
    let sweeping = false;
    fs.rmSync = ((...args: unknown[]) => {
      if (!sweeping && String(args[0]).endsWith(".tmp")) {
        sweeping = true;
        swept = repairPublicationLeftoversSync(paths);
      }
      return Reflect.apply(remove, fs, args);
    }) as typeof fs.rmSync;
    syncBuiltinESMExports();
    try {
      const written = writeAuthorityObjectSync(paths.objects.requests, { live: "publisher" });
      assert.equal(written.reused, false);
      assert.deepEqual(swept?.removed.map((name) => path.basename(name).split(".")[1]), [written.hash]);
      assertObjectHashSync(paths.objects.requests, written.hash);
    } finally {
      fs.rmSync = remove;
      syncBuiltinESMExports();
    }
  }],
];

const failures = REPAIRS.flatMap(([name, repair]) => {
  const fixture = bootstrap();
  try {
    repair(fixture);
    return [];
  } catch (error) {
    return [`${name}: ${error instanceof Error ? error.message : String(error)}`];
  } finally {
    clean(fixture.root);
  }
});
assert.deepEqual(failures, []);
console.log("producer publication repair tests passed");
