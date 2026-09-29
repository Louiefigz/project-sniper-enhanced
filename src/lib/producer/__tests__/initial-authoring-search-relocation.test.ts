import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import {
  captureVisualSearchAuthority,
} from "@/app/api/producer/auto-edit/initial-authoring-search-relocation";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";

function sha(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

interface SearchFixture {
  root: string;
  authoring: string;
  resultPath: string;
  queryPath: string;
  visual: Record<string, unknown>;
}

function fixture(): SearchFixture {
  const root = mkdtempSync(path.join(os.tmpdir(), "search-relocation-test-"));
  const authoring = path.join(root, "authoring"), producer = path.join(root, "producer");
  mkdirSync(authoring); mkdirSync(producer);
  const queryPath = path.join(authoring, "VISUAL-SEARCH.json");
  const query = Buffer.from('{"queries":[]}\n');
  writeFileSync(queryPath, query);
  const core = {
    schemaVersion: 1,
    scope: "frozen-catalog-semantic-search-not-execution-approval",
    catalog: { path: path.join(authoring, "CATALOG-AUTHORITY.json"),
      sha256: "a".repeat(64), total: 372 },
    query: { path: queryPath, sha256: sha(query), count: 0 },
    provenance: {}, searches: [],
  };
  const result = { ...core, digest: canonicalJsonSha256(core) };
  const resultBytes = Buffer.from(`${JSON.stringify(result)}\n`);
  const resultPath = path.join(authoring, "VISUAL-SEARCH-RESULTS.json");
  writeFileSync(resultPath, resultBytes);
  const visual = { searchAuthority: { schemaVersion: 1, path: resultPath,
    sha256: sha(resultBytes), digest: result.digest } };
  void producer;
  return { root, authoring, resultPath, queryPath, visual };
}

function planBytes(visual: Record<string, unknown>): Buffer {
  return Buffer.from(JSON.stringify(visual));
}

test("search relocation rejects staged result hash drift", () => {
  const item = fixture();
  try {
    const pin = item.visual.searchAuthority as Record<string, unknown>;
    pin.sha256 = "0".repeat(64);
    assert.throws(() => captureVisualSearchAuthority(
      item.authoring, planBytes(item.visual)), /SHA-256 differs/);
  } finally { rmSync(item.root, { recursive: true, force: true }); }
});

test("search relocation rejects staged digest drift", () => {
  const item = fixture();
  try {
    const pin = item.visual.searchAuthority as Record<string, unknown>;
    pin.digest = "0".repeat(64);
    assert.throws(() => captureVisualSearchAuthority(
      item.authoring, planBytes(item.visual)), /digest differs/);
  } finally { rmSync(item.root, { recursive: true, force: true }); }
});

test("search relocation rejects staged query byte drift", () => {
  const item = fixture();
  try {
    writeFileSync(item.queryPath, '{"queries":[{"forged":true}]}\n');
    assert.throws(() => captureVisualSearchAuthority(
      item.authoring, planBytes(item.visual)), /query SHA-256 differs/);
  } finally { rmSync(item.root, { recursive: true, force: true }); }
});

test("search relocation rejects an authority outside disposable staging", () => {
  const item = fixture();
  try {
    const outside = path.join(item.root, "outside-result.json");
    writeFileSync(outside, "{}\n");
    const pin = item.visual.searchAuthority as Record<string, unknown>;
    pin.path = outside; pin.sha256 = sha(Buffer.from("{}\n"));
    assert.throws(() => captureVisualSearchAuthority(
      item.authoring, planBytes(item.visual)), /inside disposable authoring/);
  } finally { rmSync(item.root, { recursive: true, force: true }); }
});

test("captured search bytes survive staged pathname replacement", () => {
  const item = fixture();
  try {
    const captured = captureVisualSearchAuthority(
      item.authoring, planBytes(item.visual));
    writeFileSync(item.queryPath, '{"forged":true}\n');
    writeFileSync(item.resultPath, '{"forged":true}\n');
    assert.equal(captured.query.toString(), '{"queries":[]}\n');
    assert.notEqual(captured.result.toString(), '{"forged":true}\n');
  } finally { rmSync(item.root, { recursive: true, force: true }); }
});
