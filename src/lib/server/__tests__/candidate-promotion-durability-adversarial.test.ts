import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {
  recoverCandidatePromotionSync,
  runRecoverablePromotionSync,
  type PromotionTopology,
} from "../candidate-promotion-transaction";
import { ensureDurableDirectory } from "../candidate-promotion-fs";
import {
  crash,
  marker,
  terminalPath,
  withFixture,
  type PromotionFixture,
} from "./helpers/candidate-promotion-adversarial-fixture";

type UnsafeCase = {
  name: string;
  change: (item: PromotionFixture) => PromotionTopology;
  error: RegExp;
};

const UNSAFE_CASES: UnsafeCase[] = [
  {
    name: "same-path",
    change: (item) => ({
      ...item.topology,
      moves: [{
        source: path.join(item.producer, "candidate.mp4"),
        destination: path.join(item.producer, "candidate.mp4"),
      }],
    }),
    error: /overlap is unsafe/,
  },
  {
    name: "cross-alias",
    change: (item) => ({
      ...item.topology,
      copies: [{
        source: path.join(item.producer, "final.mp4"),
        destination: path.join(item.producer, "audit.json"),
      }],
    }),
    error: /overlap is unsafe/,
  },
  {
    name: "source-contains-destination",
    change: (item) => ({
      ...item.topology,
      moves: [{
        source: path.join(item.producer, "nested"),
        destination: path.join(item.producer, "nested", "final.mp4"),
      }],
    }),
    error: /overlap is unsafe/,
  },
  {
    name: "destination-contains-source",
    change: (item) => ({
      ...item.topology,
      moves: [{
        source: path.join(item.producer, "nested", "candidate.mp4"),
        destination: path.join(item.producer, "nested"),
      }],
    }),
    error: /overlap is unsafe/,
  },
  {
    name: "nested-destination",
    change: (item) => ({
      ...item.topology,
      moves: [{
        source: path.join(item.producer, "candidate.mp4"),
        destination: path.join(item.producer, "nested"),
      }],
      copies: [{
        source: path.join(item.producer, "candidate-audit.json"),
        destination: path.join(item.producer, "nested", "audit.json"),
      }],
    }),
    error: /cannot be nested/,
  },
  {
    name: "root-recovery",
    change: (item) => ({
      ...item.topology,
      recoveryRoot: item.producer,
    }),
    error: /must be a descendant/,
  },
  {
    name: "recovery-payload",
    change: (item) => ({
      ...item.topology,
      recoveryRoot: path.join(item.producer, "final.mp4", "recovery"),
    }),
    error: /overlap payload/,
  },
  {
    name: "reconciliation-payload",
    change: (item) => ({
      ...item.topology,
      reconciliationPath: path.join(item.producer, "final.mp4"),
    }),
    error: /overlap payload/,
  },
  {
    name: "terminal-payload",
    change: (item) => ({
      ...item.topology,
      moves: [{
        source: path.join(item.producer, "candidate.mp4"),
        destination: terminalPath(item),
      }],
    }),
    error: /overlap payload/,
  },
];

function durableAncestorCreationIsOrderedAndResumable(): void {
  withFixture("durable-ancestors", (item) => {
    const one = path.join(item.producer, "one");
    const two = path.join(one, "two");
    const target = path.join(two, "three");
    const observed: string[] = [];
    ensureDurableDirectory(target, item.producer, {
      afterDirectorySync: (directory) => observed.push(directory),
    });
    assert.deepEqual(observed, [
      item.producer, one, item.producer, two, one, target, two,
    ]);
    const fault = path.join(item.producer, "fault");
    const child = path.join(fault, "child");
    let syncs = 0;
    assert.throws(() => ensureDurableDirectory(child, item.producer, {
      afterDirectorySync: () => {
        syncs += 1;
        if (syncs === 3) throw new Error("injected ancestor sync fault");
      },
    }), /injected ancestor sync fault/);
    assert.equal(fs.existsSync(fault), true);
    assert.equal(fs.existsSync(child), false);
    const replayed: string[] = [];
    assert.doesNotThrow(() => ensureDurableDirectory(
      child,
      item.producer,
      { afterDirectorySync: (directory) => replayed.push(directory) },
    ));
    assert.deepEqual(replayed, [
      item.producer, fault, item.producer, child, fault,
    ]);
  });
}

function exactTerminalReplayRequiresSyncBarrier(): void {
  withFixture("terminal-sync", (item) => {
    crash(item, "after-intent-removed");
    const observed: string[] = [];
    assert.equal(recoverCandidatePromotionSync(item.topology, {
      durabilityHooks: {
        afterFileSync: (filePath) => observed.push(filePath),
        afterDirectorySync: (directory) => observed.push(directory),
      },
    }), "recovered-new");
    assert.deepEqual(observed, [
      terminalPath(item), path.dirname(terminalPath(item)),
    ]);
  });
  withFixture("terminal-sync-fault", (item) => {
    crash(item, "after-intent-removed");
    assert.throws(() => recoverCandidatePromotionSync(item.topology, {
      durabilityHooks: {
        afterFileSync: () => {
          throw new Error("injected exact terminal sync fault");
        },
      },
    }), /requires reconciliation/);
    assert.equal(marker(item).phase, "reconciliation-required");
    assert.equal(fs.readFileSync(
      path.join(item.producer, "final.mp4"), "utf8"), "new-media");
  });
}

function tornTerminalCannotAuthorizeReplay(): void {
  withFixture("torn-terminal", (item) => {
    crash(item, "after-intent-removed");
    fs.writeFileSync(terminalPath(item), "{torn-terminal");
    assert.throws(
      () => recoverCandidatePromotionSync(item.topology),
      /torn or malformed/,
    );
    assert.equal(fs.readFileSync(
      path.join(item.producer, "final.mp4"), "utf8"), "new-media");
    assert.equal(fs.existsSync(item.topology.reconciliationPath), false);
  });
}

function foreignTerminalLiveStateBlocks(): void {
  withFixture("foreign-terminal", (item) => {
    crash(item, "after-intent-removed");
    fs.writeFileSync(path.join(item.producer, "final.mp4"), "foreign-media");
    assert.throws(
      () => recoverCandidatePromotionSync(item.topology),
      /requires reconciliation/,
    );
    assert.equal(fs.readFileSync(
      path.join(item.producer, "final.mp4"), "utf8"), "foreign-media");
    assert.equal(marker(item).phase, "reconciliation-required");
  });
}

function unsafeTopologyTable(): void {
  for (const row of UNSAFE_CASES) {
    withFixture(`topology-${row.name}`, (item) => {
      assert.throws(
        () => runRecoverablePromotionSync({
          ...row.change(item),
          commit: () => undefined,
        }),
        row.error,
      );
      assert.equal(fs.readFileSync(
        path.join(item.producer, "final.mp4"), "utf8"), "old-media");
      assert.equal(fs.existsSync(item.topology.reconciliationPath), false);
    });
  }
}

durableAncestorCreationIsOrderedAndResumable();
exactTerminalReplayRequiresSyncBarrier();
tornTerminalCannotAuthorizeReplay();
foreignTerminalLiveStateBlocks();
unsafeTopologyTable();
console.log("candidate promotion durability adversarial tests passed");
