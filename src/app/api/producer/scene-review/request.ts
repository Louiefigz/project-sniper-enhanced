import fs from "node:fs";
import path from "node:path";
import { canonicalProducerDir } from "../../_lib/workspace";

export interface SceneReviewInput {
  dir: string;
  requestId: string;
  previousPackage: string;
  currentPackage: string;
  previousProjectAuthority: string;
  currentProjectAuthority: string;
  operationReceipt: string;
  previousRenderReceipt: string;
  baseChannelReceipt: string;
  bundleStore: string;
  base: string;
  workers: number;
}

const PATH_FIELDS = [
  "previousPackage",
  "currentPackage",
  "previousProjectAuthority",
  "currentProjectAuthority",
  "operationReceipt",
  "previousRenderReceipt",
  "baseChannelReceipt",
  "bundleStore",
  "base",
] as const;

function requestId(value: unknown): string {
  if (typeof value !== "string"
      || !/^[a-zA-Z0-9][a-zA-Z0-9._-]{7,79}$/u.test(value)) {
    throw new Error(
      "requestId must be 8-80 letters, numbers, dots, underscores, or hyphens",
    );
  }
  return value;
}

function relativePath(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0 || value.length > 2_048
      || path.isAbsolute(value) || value.includes("\\")
      || value.split("/").some((part) => part === "" || part === "." || part === "..")) {
    throw new Error(`${label} must be a normalized project-relative path`);
  }
  return value;
}

function containedRealPath(dir: string, value: unknown, label: string): string {
  const relative = relativePath(value, label);
  let resolved: string;
  try { resolved = fs.realpathSync(path.join(dir, relative)); } catch {
    throw new Error(`${label} was not found in this Producer project`);
  }
  const child = path.relative(dir, resolved);
  if (!child || child.startsWith("..") || path.isAbsolute(child)) {
    throw new Error(`${label} must stay inside this Producer project`);
  }
  return resolved;
}

function workers(value: unknown): number {
  const resolved = value === undefined ? 2 : value;
  if (!Number.isInteger(resolved) || Number(resolved) < 1 || Number(resolved) > 4) {
    throw new Error("workers must be an integer from 1 through 4");
  }
  return Number(resolved);
}

function assertPathKinds(input: SceneReviewInput): void {
  for (const field of PATH_FIELDS) {
    const stat = fs.statSync(input[field]);
    const directory = field === "bundleStore";
    if (directory ? !stat.isDirectory() : !stat.isFile()) {
      throw new Error(`${field} must be a ${directory ? "directory" : "regular file"}`);
    }
  }
}

/** Resolve an exact, project-confined scene-review request. */
export function prepareSceneReviewRequest(
  body: Record<string, unknown>,
  canonicalize: (value: unknown) => string = canonicalProducerDir,
): SceneReviewInput {
  const dir = canonicalize(body.dir);
  const input = {
    dir,
    requestId: requestId(body.requestId),
    previousPackage: containedRealPath(
      dir, body.previousPackage, "previousPackage",
    ),
    currentPackage: containedRealPath(dir, body.currentPackage, "currentPackage"),
    previousProjectAuthority: containedRealPath(
      dir, body.previousProjectAuthority, "previousProjectAuthority",
    ),
    currentProjectAuthority: containedRealPath(
      dir, body.currentProjectAuthority, "currentProjectAuthority",
    ),
    operationReceipt: containedRealPath(
      dir, body.operationReceipt, "operationReceipt",
    ),
    previousRenderReceipt: containedRealPath(
      dir, body.previousRenderReceipt, "previousRenderReceipt",
    ),
    baseChannelReceipt: containedRealPath(
      dir, body.baseChannelReceipt, "baseChannelReceipt",
    ),
    bundleStore: containedRealPath(dir, body.bundleStore, "bundleStore"),
    base: containedRealPath(dir, body.base, "base"),
    workers: workers(body.workers),
  };
  assertPathKinds(input);
  return input;
}
