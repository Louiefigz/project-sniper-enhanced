import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { NextRequest } from "next/server";
import { cutAcceptanceInput } from "@/app/api/producer/cut-review/accept-request";

const decision = { schemaVersion: 1, operation: "accept", idempotencyKey: "12345678-1234-4234-8234-123456789abc",
  expectedToken: "current-paused-job", requestHash: "1".repeat(64), executionKey: "2".repeat(64),
  receiptHash: "3".repeat(64), mediaSha256: "4".repeat(64),
  attestation: { watched: true, listened: true, acceptsExactCut: true, acknowledgesUnfinished: true } };

function request(body: unknown, query = ""): NextRequest {
  return new NextRequest(`http://localhost/api/producer/cut-review/accept${query}`, {
    method: "POST", headers: { host: "localhost", "content-type": "application/json" }, body: JSON.stringify(body) });
}

test("closed acceptance and continuation envelopes resolve only the configured producer directory", async () => {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-cut-accept-request-")));
  const previous = process.env.SNIPER_WORKSPACE_ROOT;
  process.env.SNIPER_WORKSPACE_ROOT = root;
  const project = path.join(root, "project"), dir = path.join(project, "producer");
  mkdirSync(dir, { recursive: true }); writeFileSync(path.join(project, "project.json"), "{}");
  try {
    const body = { dir, submission: decision };
    assert.deepEqual(await cutAcceptanceInput(request(body)), body);
    const retry = { schemaVersion: 1, operation: "retry-continuation", requestHash: decision.requestHash, acceptanceHash: "5".repeat(64) };
    assert.deepEqual(await cutAcceptanceInput(request({ dir, submission: retry })), { dir, submission: retry });
    for (const changed of [{ ...body, plan: {} }, { ...body, submittedAt: new Date().toISOString() },
      { ...body, dir: root }, { ...body, dir: project }, { ...body, dir: "relative" },
      { ...body, submission: { ...decision, force: true } },
      { ...body, submission: { ...decision, attestation: { ...decision.attestation, listened: false } } },
      { ...body, submission: { ...retry, expectedToken: "new" } }]) {
      await assert.rejects(cutAcceptanceInput(request(changed)));
    }
    await assert.rejects(cutAcceptanceInput(request(body, "?force=true")), /query parameters/);
    assert.equal(readFileSync(path.join(project, "project.json"), "utf8"), "{}", "parser does not mutate project authority");
  } finally {
    if (previous === undefined) delete process.env.SNIPER_WORKSPACE_ROOT;
    else process.env.SNIPER_WORKSPACE_ROOT = previous;
    rmSync(root, { recursive: true, force: true });
  }
});

test("request size, UTF-8/JSON and cancellation fail before reading project files", async () => {
  await assert.rejects(cutAcceptanceInput(request({ text: "x".repeat(20_000) })), /too large/);
  for (const bytes of [new Uint8Array([0xc3, 0x28]), new TextEncoder().encode("{broken")]) {
    await assert.rejects(cutAcceptanceInput(new NextRequest("http://localhost/api/producer/cut-review/accept", {
      method: "POST", body: bytes })), /UTF-8 JSON/);
  }
  const controller = new AbortController();
  let canceled = false;
  const body = new ReadableStream({ cancel() { canceled = true; } });
  const init = { method: "POST", body, signal: controller.signal, duplex: "half" as const };
  const pending = cutAcceptanceInput(new NextRequest("http://localhost/api/producer/cut-review/accept", init));
  controller.abort(); await assert.rejects(pending, { name: "AbortError" });
  assert.equal(canceled, true); assert.equal(body.locked, false);
});
