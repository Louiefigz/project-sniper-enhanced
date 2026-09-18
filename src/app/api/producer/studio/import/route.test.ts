import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { NextRequest } from "next/server";
import { POST } from "./route";
import { emptyFixture } from "./fixture_test";
import { readSession } from "./files";

function request(body: unknown, headers: Record<string, string> = {}) {
  return new NextRequest("http://127.0.0.1:3327/api/producer/studio/import", {
    method: "POST", headers: { host: "127.0.0.1:3327", origin: "http://127.0.0.1:3327",
      "sec-fetch-site": "same-origin", "content-type": "application/json", ...headers }, body: JSON.stringify(body),
  });
}

test("import rejects cross-origin/opaque requests, wrong content-type, large bodies and traversal before private writes", async () => {
  const f = emptyFixture();
  try {
    for (const origin of ["null", "https://foreign.test", "http://127.0.0.1:3990"]) {
      assert.equal((await POST(request({ dir: f.dir, action: "prepare" }, { origin }))).status, 403);
    }
    assert.equal((await POST(request({}, { "content-type": "text/plain" }))).status, 415);
    assert.equal((await POST(request({ padding: "x".repeat(20_000) }))).status, 413);
    assert.equal((await POST(request({}, { "content-length": "20000" }))).status, 413);
    assert.equal((await POST(request({ dir: `${f.dir}/../producer`, action: "prepare" }))).status, 400);
    assert.equal(readSession(f.dir), null);
  } finally { fs.rmSync(f.root, { recursive: true, force: true }); }
});

test("closed import schema refuses arbitrary plans, force/render/apply identity errors", async () => {
  const f = emptyFixture(); const previous = process.env.SNIPER_WORKSPACE_ROOT;
  process.env.SNIPER_WORKSPACE_ROOT = path.dirname(f.root);
  try {
    for (const extra of [{ force: true }, { render: true }, { plan: {} }, { path: "/private/file" }]) {
      assert.equal((await POST(request({ dir: f.dir, action: "prepare", ...extra }))).status, 400);
    }
    for (const proposalId of ["../session", "not-a-uuid", "a".repeat(64)]) {
      assert.equal((await POST(request({ dir: f.dir, action: "apply", proposalId, expectedPlanHash: "a".repeat(64), expectedPlanVersion: 1 }))).status, 400);
    }
    assert.equal((await POST(request({ dir: f.dir, action: "render" }))).status, 400);
    assert.equal((await POST(request({ dir: f.dir, action: "apply", proposalId: "00000000-0000-4000-8000-000000000000", expectedPlanHash: "a".repeat(64), expectedPlanVersion: -1 }))).status, 400);
    assert.equal(readSession(f.dir), null);
  } finally {
    if (previous === undefined) delete process.env.SNIPER_WORKSPACE_ROOT; else process.env.SNIPER_WORKSPACE_ROOT = previous;
    fs.rmSync(f.root, { recursive: true, force: true });
  }
});
