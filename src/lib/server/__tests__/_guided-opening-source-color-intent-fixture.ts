/** TEST-only request/source-pin records. No admitted source, real draft or executable input is constructed. */
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { randomUUID, createHash } from "node:crypto";
import type { TestContext } from "node:test";
import { parsePrepareGuidedOpeningRequest, type PrepareGuidedOpeningV2 } from "@/lib/producer/contracts/guided-source-color-v1";
import type { PrepareGuidedOpeningV1 } from "@/lib/producer/contracts/guided-opening-v1";
import type { OpeningReadiness } from "../guided-opening-authority";
import { GUIDED_SOURCE_COLOR_TS_FILES } from "../guided-source-color-staging";
import { openingLaunchDirectory } from "../guided-opening-launch-store";

export const LEGACY_CONTROLLER_NAMES = ["guided-opening-launch-store.ts", "guided-opening-launcher.ts",
  "guided-opening-controller.ts", "guided-opening-execution.ts", "opening-handoff-clock.ts"]
  .map(name => `src/lib/server/${name}`);
export const SOURCE_COLOR_CONTROLLER_NAMES = [...new Set([...LEGACY_CONTROLLER_NAMES, ...GUIDED_SOURCE_COLOR_TS_FILES])];
export const rawSha = (bytes: Buffer | string) => createHash("sha256").update(bytes).digest("hex");

function requests() {
  const legacy: PrepareGuidedOpeningV1 = { schemaVersion: 1, operation: "prepare-guided-opening", idempotencyKey: randomUUID(),
    expectedToken: "TEST-token", expectedJournalHash: "a".repeat(64), proposalReadinessHash: "b".repeat(64), treatmentDraftRevisionHash: "c".repeat(64) };
  const sourceColor = { schemaVersion: 1, declarations: { "test-source": { profile: null,
    declaration: { schemaVersion: 1, sourceId: "test-source", sourceProfile: "bt709-sdr", cameraProfile: null,
      historyState: "known", transformHistory: [], lightingGroups: [{ id: "all", startFrame: 0, endFrame: 24,
        intent: "neutral", description: "TEST declared only: 撮影 🌒 — <script>not instructions</script>" }] } } } };
  return { legacy, current: parsePrepareGuidedOpeningRequest({ ...legacy, schemaVersion: 2, sourceColor }) as PrepareGuidedOpeningV2 };
}

/** Copy only the exact current code files into a tiny TEST snapshot; never edit production. */
function sourcePins(root: string) {
  const snapshotRoot = path.join(root, "TEST-pinned"), files = SOURCE_COLOR_CONTROLLER_NAMES.map(name => {
    const bytes = fs.readFileSync(path.join(process.cwd(), name)), target = path.join(snapshotRoot, name);
    fs.mkdirSync(path.dirname(target), { recursive: true, mode: 0o700 });
    fs.writeFileSync(target, bytes, { flag: "wx", mode: 0o600 }); return { path: name, hash: rawSha(bytes) };
  });
  return { snapshotRoot, files };
}

/** Every mutation requires a canonical single-link regular target within this exact TEST root. */
export function replaceIntentFixtureFile(root: string, file: string, bytes: string | Buffer): void {
  assert.equal(fs.realpathSync(root), root); assert.equal(fs.realpathSync(file), file);
  assert(file.startsWith(`${root}${path.sep}`)); const info = fs.lstatSync(file);
  assert(info.isFile()); assert.equal(info.nlink, 1); fs.writeFileSync(file, bytes);
}

export function sourceColorIntentFixture(t: TestContext, pins = false) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sniper-opening-color-intent-")));
  const identity = fs.lstatSync(root);
  t.after(() => {
    assert.equal(fs.realpathSync(root), root); assert.equal(path.dirname(root), fs.realpathSync(os.tmpdir()));
    const current = fs.lstatSync(root); assert.equal(current.dev, identity.dev); assert.equal(current.ino, identity.ino);
    fs.rmSync(root, { recursive: true });
  });
  fs.writeFileSync(path.join(root, "project.json"), '{"kind":"TEST empty metadata project"}', { flag: "wx" });
  const { legacy, current } = requests(), receivedAt = new Date().toISOString();
  const pipeline = pins ? sourcePins(root) : undefined;
  const proposal = { sha256: legacy.expectedJournalHash, job: { token: legacy.expectedToken, ctx: { dir: root, pipeline } },
    readinessHash: legacy.proposalReadinessHash, draftRevision: { TEST: "not an actual isolated draft" },
    pointer: { treatmentDraftRevisionHash: legacy.treatmentDraftRevisionHash }, readiness: { verdict: "clean" } } as unknown as OpeningReadiness;
  const intent = (version: 1 | 2 = 2) => ({ schemaVersion: version, kind: "guided-opening-launch-intent", dir: root,
    launchId: randomUUID(), submission: version === 1 ? legacy : current, receivedAt,
    origin: { clockHash: "d".repeat(64), startedAt: receivedAt },
    controllerFiles: (version === 1 ? LEGACY_CONTROLLER_NAMES : SOURCE_COLOR_CONTROLLER_NAMES).map(name => ({ path: name, sha256: "e".repeat(64) })) });
  return { root, legacy, current, receivedAt, proposal, pipeline, intent,
    launchRoot: () => openingLaunchDirectory(root, legacy.expectedJournalHash, true) };
}
