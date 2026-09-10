import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  prepareSceneReviewRequest,
  type SceneReviewInput,
} from "../../../app/api/producer/scene-review/request";
import {
  runSceneReview,
  type SceneReviewExecutor,
} from "../../../app/api/producer/scene-review/runner";
import { runSceneReviewProcess } from
  "../../../app/api/producer/scene-review/process";

interface Fixture {
  root: string;
  producer: string;
  body: Record<string, unknown>;
}

function fixture(): Fixture {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "sniper-scene-review-route-"));
  const producer = path.join(root, "producer");
  fs.mkdirSync(path.join(producer, "authority"), { recursive: true });
  fs.mkdirSync(path.join(producer, "bundle-store"));
  const names = [
    "previous-package.json", "current-package.json", "operation.json",
    "previous-project.json", "current-project.json",
    "previous-render.json", "channel.json", "base.mov",
  ];
  for (const name of names) {
    fs.writeFileSync(path.join(producer, "authority", name), "{}\n");
  }
  return {
    root,
    producer,
    body: {
      dir: producer,
      requestId: "repair-0001",
      previousPackage: "authority/previous-package.json",
      currentPackage: "authority/current-package.json",
      previousProjectAuthority: "authority/previous-project.json",
      currentProjectAuthority: "authority/current-project.json",
      operationReceipt: "authority/operation.json",
      previousRenderReceipt: "authority/previous-render.json",
      baseChannelReceipt: "authority/channel.json",
      bundleStore: "bundle-store",
      base: "authority/base.mov",
      workers: 2,
    },
  };
}

function prepare(value: Fixture): SceneReviewInput {
  return prepareSceneReviewRequest(value.body, () => fs.realpathSync(value.producer));
}

function option(args: string[], flag: string): string {
  const index = args.indexOf(flag);
  assert.notEqual(index, -1, `missing ${flag}`);
  return args[index + 1];
}

function receipt(reviewPath: string): Record<string, unknown> {
  return {
    schemaVersion: 1,
    kind: "scene-unit-review-repair",
    receiptHash: "a".repeat(64),
    reviewMedia: { output: { path: reviewPath } },
    execution: {
      fullBaseEncodeCount: 0,
      fullDurationOutputCount: 0,
      reviewFragmentEncodeCount: 1,
    },
    projectFanout: {
      sceneCount: 50,
      dirtySceneCount: 1,
      reusedSceneCount: 49,
      dirtySceneIds: ["scene-045"],
    },
    promotion: {
      status: "private-review",
      activeMutationCount: 0,
      connectedPalmierMutationCount: 0,
    },
  };
}

function successfulExecutor(
  counter: { calls: number; args?: string[] },
): SceneReviewExecutor {
  return async (args) => {
    counter.calls += 1;
    counter.args = args;
    const reviewPath = option(args, "--review-out");
    const receiptPath = option(args, "--receipt-out");
    fs.writeFileSync(reviewPath, "real-review-media");
    const value = receipt(reviewPath);
    fs.writeFileSync(receiptPath, `${JSON.stringify(value)}\n`);
    return { stdout: `${JSON.stringify(value)}\n`, stderr: "" };
  };
}

async function requestBoundaryCases(): Promise<void> {
  const value = fixture();
  try {
    const canonical = () => fs.realpathSync(value.producer);
    const input = prepare(value);
    assert.equal(input.dir, fs.realpathSync(value.producer));
    assert.equal(input.workers, 2);
    assert.equal(input.bundleStore, path.join(input.dir, "bundle-store"));

    assert.throws(() => prepareSceneReviewRequest({
      ...value.body, previousPackage: "../outside.json",
    }, canonical), /project-relative/);
    assert.throws(() => prepareSceneReviewRequest({
      ...value.body, currentPackage: path.join(value.producer, "authority/current-package.json"),
    }, canonical), /project-relative/);
    assert.throws(() => prepareSceneReviewRequest({
      ...value.body, workers: 5,
    }, canonical), /1 through 4/);

    const outside = path.join(value.root, "outside.json");
    fs.writeFileSync(outside, "{}\n");
    fs.symlinkSync(outside, path.join(value.producer, "authority", "escape.json"));
    assert.throws(() => prepareSceneReviewRequest({
      ...value.body, operationReceipt: "authority/escape.json",
    }, canonical), /stay inside/);
  } finally {
    fs.rmSync(value.root, { recursive: true, force: true });
  }
}

async function publicationAndReplay(): Promise<void> {
  const value = fixture();
  try {
    const input = prepare(value);
    const counter: { calls: number; args?: string[] } = { calls: 0 };
    const first = await runSceneReview(input, undefined, successfulExecutor(counter));
    assert.equal(first.reused, false);
    assert.equal(counter.calls, 1);
    assert.equal(
      option(counter.args ?? [], "--previous-project-authority"),
      input.previousProjectAuthority,
    );
    assert.equal(
      option(counter.args ?? [], "--current-project-authority"),
      input.currentProjectAuthority,
    );
    assert.equal(first.reviewPath, path.join(
      input.dir, "scene-reviews", "repair-0001", "review.mov",
    ));
    assert.equal(fs.existsSync(first.receiptPath), true);

    const replay = await runSceneReview(
      input,
      undefined,
      async () => { throw new Error("executor must not run on exact replay"); },
    );
    assert.equal(replay.reused, true);
    assert.equal(replay.receipt.receiptHash, first.receipt.receiptHash);

    await assert.rejects(runSceneReview(
      { ...input, workers: 3 },
      undefined,
      successfulExecutor(counter),
    ), /different scene review/);
  } finally {
    fs.rmSync(value.root, { recursive: true, force: true });
  }
}

async function failureQuarantine(): Promise<void> {
  const value = fixture();
  try {
    const input = prepare(value);
    await assert.rejects(runSceneReview(
      input,
      undefined,
      async () => { throw new Error("injected render failure"); },
    ), /injected render failure/);
    const root = path.join(input.dir, "scene-reviews");
    assert.equal(fs.existsSync(path.join(root, input.requestId)), false);
    assert.equal(
      fs.readdirSync(root).filter((name) =>
        name.startsWith(`${input.requestId}.failed-`)).length,
      1,
    );
  } finally {
    fs.rmSync(value.root, { recursive: true, force: true });
  }
}

async function processCancellation(): Promise<void> {
  const controller = new AbortController();
  const running = runSceneReviewProcess([
    "-c", "import time; time.sleep(60)",
  ], controller.signal);
  setTimeout(() => controller.abort(), 50);
  await assert.rejects(running, /canceled/);
}

async function main(): Promise<void> {
  await requestBoundaryCases();
  await publicationAndReplay();
  await failureQuarantine();
  await processCancellation();
  console.log("scene-review-route.test.ts: all assertions passed");
}

void main();
