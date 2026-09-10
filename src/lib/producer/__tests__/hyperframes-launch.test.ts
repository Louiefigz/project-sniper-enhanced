import assert from "node:assert/strict";
import { launchAutoEditFromHyperframes } from "../../../components/producer/use-editor-runtime";

const previous = globalThis.fetch;
const calls: { url: string; init?: RequestInit }[] = [];
globalThis.fetch = async (url, init) => {
  calls.push({ url: String(url), init });
  return new Response("data: {}\n\n", { status: 200 });
};

async function main(): Promise<void> {
try {
  for (const request of [{ scope: "produced" }, { reviewSavedPlan: true }, { resume: true }]) {
    const signal = new AbortController().signal;
    const result = await launchAutoEditFromHyperframes({ dir: "/workspace/project/producer", request, signal });
    assert.equal(result.status, 200);
    const call = calls.at(-1)!;
    assert.equal(call.url, "/api/producer/auto-edit");
    assert.equal(call.init?.signal, signal);
    assert.deepEqual(JSON.parse(String(call.init?.body)), {
      ...request, dir: "/workspace/project/producer", deliveryPolicy: "mp4-only",
    });
    assert.equal("deliveryPolicy" in request, false, "caller request is not mutated");
  }
  assert.equal(calls.length, 3, "no Palmier or Studio startup required before a base exists");
  const aborted = new AbortController();
  aborted.abort();
  await assert.rejects(launchAutoEditFromHyperframes({ dir: "/p", request: {}, signal: aborted.signal }),
    { name: "AbortError" });
  await assert.rejects(launchAutoEditFromHyperframes({ dir: "/p", request: { deliveryPolicy: "palmier-hybrid" } }),
    /existing Palmier runs keep their original policy/);
  assert.equal(calls.length, 3, "invalid or canceled launches never start work");
  globalThis.fetch = async () => new Response(JSON.stringify({ error: "checkpoint mismatch" }), { status: 409 });
  const conflict = await launchAutoEditFromHyperframes({ dir: "/p", request: { resume: true } });
  assert.equal(conflict.status, 409, "conflicting checkpoints are not retried as a fresh run");
} finally {
  globalThis.fetch = previous;
}
console.log("hyperframes-launch.test.ts: all assertions passed");
}
void main().catch((error) => { console.error(error); process.exitCode = 1; });
