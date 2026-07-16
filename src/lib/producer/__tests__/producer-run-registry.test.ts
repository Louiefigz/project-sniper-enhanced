import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import {
  appendProducerRunEvent,
  beginProducerRun,
  clearProducerRun,
  completeProducerRun,
  failProducerRun,
  producerRun,
  producerRunActive,
  updateProducerRun,
} from "../../server/producer-run-registry";

const dir = `/tmp/sniper-run-registry-${Date.now()}`;
mkdirSync(dir, { recursive: true });
clearProducerRun(dir);

const token = beginProducerRun(dir, "auto_edit", "authoring", "started");
assert.equal(producerRunActive(dir), true);
assert.equal(producerRun(dir)?.controlToken, token, "active Auto Edit exposes its attempt fence to local controls");
updateProducerRun(dir, token, "rendering", "rendering final");
assert.equal(producerRun(dir)?.phase, "rendering");

for (let index = 0; index < 30; index += 1) {
  appendProducerRunEvent(dir, token, `event ${index}`);
}
assert.equal(producerRun(dir)?.events.length, 24, "run logs stay bounded");
completeProducerRun(dir, "wrong-token");
assert.ok(producerRun(dir), "a stale request cannot clear the current run");

failProducerRun(dir, token, "render failed");
assert.equal(producerRunActive(dir), false);
assert.equal(producerRun(dir)?.message, "render failed");
const stateFile = path.join(dir, ".sniper-run-state.json");
assert.equal(existsSync(stateFile), true, "failed run survives a page or server refresh");
assert.equal(JSON.parse(readFileSync(stateFile, "utf8")).message, "render failed");
const globalStore = globalThis as typeof globalThis & { __sniperProducerRuns?: Map<string, unknown> };
globalStore.__sniperProducerRuns?.delete(dir);
assert.equal(producerRun(dir)?.message, "render failed", "status reloads from the durable file");

beginProducerRun(dir, "render", "rendering", "retrying");
assert.equal(producerRun(dir)?.controlToken, undefined, "render runs do not expose Auto Edit controls");
const reusedPid = JSON.parse(readFileSync(stateFile, "utf8"));
// Keep this registry test deterministic on sandboxes where `ps` is denied.
// Start-token conflicts are covered with an injected probe by process-liveness.test.ts.
reusedPid.ownerIdentity = { ...reusedPid.ownerIdentity, pid: reusedPid.ownerPid + 1 };
writeFileSync(stateFile, JSON.stringify(reusedPid));
globalStore.__sniperProducerRuns?.delete(dir);
assert.equal(producerRun(dir)?.status, "interrupted", "PID reuse cannot impersonate the recorded server process");

beginProducerRun(dir, "render", "rendering", "stale heartbeat");
const staleHeartbeat = JSON.parse(readFileSync(stateFile, "utf8"));
staleHeartbeat.updatedAt = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
writeFileSync(stateFile, JSON.stringify(staleHeartbeat));
globalStore.__sniperProducerRuns?.delete(dir);
assert.equal(producerRun(dir)?.status, "interrupted", "a stale heartbeat cannot remain running forever");

beginProducerRun(dir, "render", "rendering", "dead owner");
const interrupted = JSON.parse(readFileSync(stateFile, "utf8"));
interrupted.ownerPid = 99_999_999;
writeFileSync(stateFile, JSON.stringify(interrupted));
globalStore.__sniperProducerRuns?.delete(dir);
assert.equal(producerRun(dir, { recover: false })?.status, "running",
  "an unrelated status card reads persisted state without probing or recovering its owner");
assert.equal(JSON.parse(readFileSync(stateFile, "utf8")).status, "running",
  "a read-only card status must not mutate another project's durable run");
assert.equal(producerRun(dir)?.status, "interrupted", "a dead server owner becomes resumable, not permanent");

const finalRetry = beginProducerRun(dir, "render", "rendering", "retry after interruption");
completeProducerRun(dir, finalRetry);
assert.equal(producerRun(dir), null);
assert.equal(existsSync(stateFile), false, "successful completion clears durable run state");
rmSync(dir, { recursive: true, force: true });

console.log("producer-run-registry.test.ts: all assertions passed");
