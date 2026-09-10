import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { atomicCreateJsonSync } from "@/lib/server/atomic-file";
import { SCRIPTS_DIR } from "../../_lib/spawn-python";
import type { SceneReviewInput } from "./request";
import {
  runSceneReviewProcess,
  type ProcessResult,
} from "./process";

const SCRIPT = path.join(
  SCRIPTS_DIR, "producer", "graphics", "scene_review_repair_cli.py",
);
const REVIEW_ROOT = "scene-reviews";
const CACHE_ROOT = "scene-cache";

export type SceneReviewExecutor = (
  args: string[],
  signal?: AbortSignal,
) => Promise<ProcessResult>;

export interface SceneReviewResult {
  reused: boolean;
  reviewPath: string;
  receiptPath: string;
  receipt: Record<string, unknown>;
}

function requestHash(input: SceneReviewInput): string {
  return crypto.createHash("sha256").update(JSON.stringify(input)).digest("hex");
}

function safeDirectory(dir: string): void {
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  const stat = fs.lstatSync(dir);
  if (!stat.isDirectory() || stat.isSymbolicLink()
      || fs.realpathSync(dir) !== path.resolve(dir)) {
    throw new Error(`unsafe scene-review directory: ${dir}`);
  }
}

function readObject(file: string): Record<string, unknown> {
  const stat = fs.lstatSync(file);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new Error(`scene-review authority is not a regular file: ${file}`);
  }
  const value: unknown = JSON.parse(fs.readFileSync(file, "utf8"));
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`scene-review authority is not an object: ${file}`);
  }
  return value as Record<string, unknown>;
}

function paths(input: SceneReviewInput) {
  const root = path.join(input.dir, REVIEW_ROOT);
  const attempt = path.join(root, input.requestId);
  return {
    root, attempt, cache: path.join(input.dir, CACHE_ROOT),
    review: path.join(attempt, "review.mov"),
    receipt: path.join(attempt, "receipt.json"),
    request: path.join(attempt, "request.json"),
    complete: path.join(attempt, "complete.json"),
  };
}

function verifiedReceipt(
  receiptPath: string,
  reviewPath: string,
): Record<string, unknown> {
  const receipt = readObject(receiptPath);
  const execution = receipt.execution as Record<string, unknown> | undefined;
  const promotion = receipt.promotion as Record<string, unknown> | undefined;
  const media = receipt.reviewMedia as Record<string, unknown> | undefined;
  const output = media?.output as Record<string, unknown> | undefined;
  const fanout = receipt.projectFanout as Record<string, unknown> | undefined;
  const sceneCount = Number(fanout?.sceneCount);
  const reviewStat = fs.lstatSync(reviewPath);
  if (receipt.kind !== "scene-unit-review-repair"
      || !/^[0-9a-f]{64}$/u.test(String(receipt.receiptHash))
      || execution?.fullBaseEncodeCount !== 0
      || execution?.fullDurationOutputCount !== 0
      || promotion?.status !== "private-review"
      || promotion?.activeMutationCount !== 0
      || promotion?.connectedPalmierMutationCount !== 0
      || !Number.isInteger(sceneCount) || sceneCount < 1
      || fanout?.dirtySceneCount !== 1
      || fanout?.reusedSceneCount !== sceneCount - 1
      || !Array.isArray(fanout?.dirtySceneIds)
      || fanout.dirtySceneIds.length !== 1
      || output?.path !== reviewPath
      || !reviewStat.isFile() || reviewStat.isSymbolicLink()) {
    throw new Error("scene-review CLI returned an unsafe or incomplete receipt");
  }
  return receipt;
}

function priorResult(
  input: SceneReviewInput,
  location: ReturnType<typeof paths>,
): SceneReviewResult | null {
  if (!fs.existsSync(location.attempt)) return null;
  const stat = fs.lstatSync(location.attempt);
  if (!stat.isDirectory() || stat.isSymbolicLink()
      || fs.realpathSync(location.attempt) !== path.resolve(location.attempt)) {
    throw new Error("scene-review request directory is unsafe");
  }
  if (fs.existsSync(location.complete)) {
    const complete = readObject(location.complete);
    if (complete.requestHash !== requestHash(input)) {
      throw new Error("requestId already belongs to a different scene review");
    }
    return {
      reused: true, reviewPath: location.review, receiptPath: location.receipt,
      receipt: verifiedReceipt(location.receipt, location.review),
    };
  }
  const quarantined = `${location.attempt}.incomplete-${randomUUID()}`;
  fs.renameSync(location.attempt, quarantined);
  return null;
}

function command(
  input: SceneReviewInput,
  location: ReturnType<typeof paths>,
): string[] {
  return [
    SCRIPT, input.previousPackage, input.currentPackage,
    "--previous-project-authority", input.previousProjectAuthority,
    "--current-project-authority", input.currentProjectAuthority,
    "--operation-receipt", input.operationReceipt,
    "--previous-render-receipt", input.previousRenderReceipt,
    "--base-channel-receipt", input.baseChannelReceipt,
    "--bundle-store", input.bundleStore,
    "--cache-dir", location.cache,
    "--base", input.base,
    "--review-out", location.review,
    "--receipt-out", location.receipt,
    "--workers", String(input.workers),
    "--sample-rate", "48000",
  ];
}

function compareStdout(stdout: string, receipt: Record<string, unknown>): void {
  const line = stdout.trim().split("\n").filter(Boolean).at(-1);
  const emitted = line ? JSON.parse(line) as Record<string, unknown> : null;
  if (!emitted || emitted.receiptHash !== receipt.receiptHash) {
    throw new Error("scene-review stdout and durable receipt disagree");
  }
}

/** Build and publish one create-once, private dirty-window review. */
export async function runSceneReview(
  input: SceneReviewInput,
  signal?: AbortSignal,
  execute: SceneReviewExecutor = runSceneReviewProcess,
): Promise<SceneReviewResult> {
  const location = paths(input);
  safeDirectory(location.root);
  safeDirectory(location.cache);
  const prior = priorResult(input, location);
  if (prior) return prior;
  fs.mkdirSync(location.attempt, { mode: 0o700 });
  atomicCreateJsonSync(location.request, {
    schemaVersion: 1, requestHash: requestHash(input), input,
  });
  try {
    const result = await execute(command(input, location), signal);
    const receipt = verifiedReceipt(location.receipt, location.review);
    compareStdout(result.stdout, receipt);
    atomicCreateJsonSync(location.complete, {
      schemaVersion: 1, requestHash: requestHash(input),
      receiptHash: receipt.receiptHash,
    });
    return {
      reused: false, reviewPath: location.review, receiptPath: location.receipt,
      receipt,
    };
  } catch (error) {
    const quarantined = `${location.attempt}.failed-${randomUUID()}`;
    if (fs.existsSync(location.attempt)) fs.renameSync(location.attempt, quarantined);
    throw error;
  }
}
