import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import test from "node:test";
import { NextRequest } from "next/server";
import { GET, POST } from "../../../app/api/producer/color-diagnostic/route";
import { boundedBody, parseStart, validateContexts } from "../../../app/api/producer/color-diagnostic/request";
import { descriptor, readRequest } from "../../../app/api/producer/color-diagnostic/files";
import { jobStatus, startDiagnostic } from "../../../app/api/producer/color-diagnostic/service";
import { unknownColorContext } from "../../producer/color-diagnostic";
import { acquireProjectMutationLease } from "../project-mutation-lease";

function fixture() {
  const workspace = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "color-api-test-")));
  const project = path.join(workspace, "synthetic"), dir = path.join(project, "producer");
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(project, "project.json"), JSON.stringify({ origin: "raw", history: [] }));
  fs.writeFileSync(path.join(dir, "edit_plan.json"), JSON.stringify({ planVersion: 1, cutTrack: [{ sourceId: "raw-1", start: 0, end: 90 }] }));
  // Inert boundary fixture only: the stub runner never treats this as real admission.
  fs.writeFileSync(path.join(dir, "asset_manifest.json"), JSON.stringify({ sourceSetAdmission: { inertTest: true },
    sources: [{ id: "raw-1", path: "/private/not-returned/source.mp4", duration: 90, sourceSha256: "a".repeat(64) }] }));
  process.env.SNIPER_WORKSPACE_ROOT = workspace;
  const observed = descriptor(dir);
  return { workspace, project, dir, input: { dir, jobId: randomUUID(), expectedPlanHash: observed.planHash,
    expectedManifestHash: observed.manifestHash, contexts: observed.sources.map(unknownColorContext) },
    cleanup: () => fs.rmSync(workspace, { recursive: true, force: true }) };
}
function request(url: string, init?: RequestInit): NextRequest {
  return new NextRequest(`http://localhost:3327${url}`, { ...init, signal: init?.signal ?? undefined,
    headers: { host: "localhost:3327", "content-type": "application/json", ...init?.headers } });
}
test("GET is project-bound/read-only and rejects path/query ambiguity", async () => {
  const f = fixture();
  try {
    const before = fs.readdirSync(f.dir);
    const result = await GET(request(`/api/producer/color-diagnostic?${new URLSearchParams({ dir: f.dir })}`));
    assert.equal(result.status, 200); const text = await result.text();
    assert(!text.includes("/private/not-returned")); assert.deepEqual(fs.readdirSync(f.dir), before);
    for (const dir of ["/etc", f.dir + "/../producer", f.dir.replaceAll("/", "\\")]) {
      assert.throws(() => parseStart({ ...f.input, dir }));
    }
    assert.equal((await GET(request(`/api/producer/color-diagnostic?dir=${encodeURIComponent(f.dir)}&jobId=../bad`))).status, 400);
  } finally { f.cleanup(); }
});
test("POST rejects cross-site and queries before body consumption", async () => {
  const f = fixture();
  try {
    const cross = request("/api/producer/color-diagnostic", { method: "POST", body: JSON.stringify(f.input), headers: { origin: "https://evil.test" } });
    assert.equal((await POST(cross)).status, 403); assert.equal(cross.bodyUsed, false);
    const query = request("/api/producer/color-diagnostic?render=true", { method: "POST", body: JSON.stringify(f.input) });
    assert.equal((await POST(query)).status, 400); assert.equal(query.bodyUsed, false);
    assert.throws(() => parseStart({ ...f.input, command: "ffmpeg" }));
    assert.throws(() => validateContexts([{ ...f.input.contexts[0], sourceProfile: ["unknown"] } as never], descriptor(f.dir).sources));
    await assert.rejects(boundedBody(new Request("http://localhost", { method: "POST", body: "x".repeat(65 * 1024) })), /64 KiB/);
  } finally { f.cleanup(); }
});
test("body disconnect cancels and unlocks the input stream", async () => {
  const controller = new AbortController(); let cancelled = false;
  const stream = new ReadableStream<Uint8Array>({ cancel() { cancelled = true; } });
  const req = new Request("http://localhost", { method: "POST", body: stream, signal: controller.signal, duplex: "half" } as RequestInit);
  const pending = boundedBody(req); controller.abort();
  await assert.rejects(pending, /disconnected/); await new Promise(resolve => setTimeout(resolve, 0));
  assert(cancelled); assert.equal(stream.locked, false);
});
test("clean failed result releases exact leases; token replay is immutable and current-parent bound", async () => {
  const f = fixture(); let runs = 0;
  const before = fs.readFileSync(path.join(f.dir, "edit_plan.json"));
  try {
    const deps = { run: async () => { runs++; return { diagnosticId: null, cleanupVerified: true, interrupted: true }; } };
    const result = await startDiagnostic(f.input, deps);
    assert(!(result instanceof Response)); assert.equal(result.state, "interrupted"); assert.equal(result.cleanupVerified, true);
    assert.equal(fs.existsSync(path.join(f.project, ".sniper-project-mutation.lock")), false);
    assert.equal(fs.existsSync(path.join(f.workspace, ".sniper-color-resource/active.json")), false);
    await startDiagnostic(f.input, deps); assert.equal(runs, 1);
    await assert.rejects(startDiagnostic({ ...f.input, contexts: [{ ...f.input.contexts[0], sourceProfile: "hdr" }] }, deps), /different immutable/);
    fs.appendFileSync(path.join(f.dir, "edit_plan.json"), " ");
    await assert.rejects(startDiagnostic(f.input, deps), /parents changed/);
    assert.equal(jobStatus(f.dir, f.input.jobId).parentsCurrent, false);
    assert.equal(readRequest(f.dir, f.input.jobId).planText, before.toString());
    assert.equal(fs.existsSync(path.join(f.dir, "final.mp4")), false);
  } finally { f.cleanup(); }
});
test("shared project busy fails before runner or attempt writes", async () => {
  const f = fixture(); const held = acquireProjectMutationLease(f.project, "test writer");
  try {
    const result = await startDiagnostic(f.input, { run: async () => { throw new Error("must not launch"); } });
    assert(result instanceof Response); assert.equal(result.status, 409);
    assert.equal(fs.existsSync(path.join(f.dir, ".sniper-color-jobs")), false);
  } finally { held.lease?.release(); f.cleanup(); }
});
test("uncertain cleanup and changed active claim retain both ownership boundaries", async () => {
  for (const changed of [false, true]) {
    const f = fixture();
    try {
      const deps = { run: async () => {
        if (changed) {
          const file = path.join(f.workspace, ".sniper-color-resource/active.json");
          fs.chmodSync(file, 0o600); fs.writeFileSync(file, JSON.stringify({ requestDigest: "other" }));
        }
        return { diagnosticId: null, cleanupVerified: changed, interrupted: true };
      } };
      if (changed) await assert.rejects(startDiagnostic(f.input, deps), /ownership changed/);
      else assert(!(await startDiagnostic(f.input, deps) instanceof Response));
      assert(fs.existsSync(path.join(f.project, ".sniper-project-mutation.lock")));
      assert(fs.existsSync(path.join(f.workspace, ".sniper-color-resource/.sniper-project-mutation.lock")));
      assert(fs.existsSync(path.join(f.workspace, ".sniper-color-resource/active.json")));
      assert.equal(fs.existsSync(path.join(f.dir, "final.mp4")), false);
    } finally { f.cleanup(); }
  }
});
