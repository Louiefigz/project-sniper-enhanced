import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  candidateFinalPath,
  prepareQcRound,
  seedQcRoundFromPriorCandidate,
} from "../auto-edit-quality-artifacts";
import { fileSha256 } from "../auto-edit-hash";

const TOKEN = "seed:token";
const NO_GRAPHICS_PLAN = JSON.stringify({ planVersion: 1, graphicsTrack: [] });
const GRAPHICS_PLAN = JSON.stringify({
  planVersion: 1,
  graphicsTrack: [{ kind: "stat-card", outStart: 1, outEnd: 3 }],
});

function writePriorRound(dir: string, sidecar?: string, plan: string | null = NO_GRAPHICS_PLAN): string {
  const prior = candidateFinalPath(dir, TOKEN, 1);
  prepareQcRound(dir, TOKEN, 1);
  writeFileSync(prior, "prior-composited-video");
  if (plan !== null) writeFileSync(path.join(path.dirname(prior), "edit_plan.json"), plan);
  if (sidecar !== undefined) writeFileSync(`${prior}.assembled.json`, sidecar);
  return prior;
}

function validSidecar(prior: string): string {
  return JSON.stringify({
    videoFingerprint: "vfp16chars000000",
    graphicsFingerprint: "gfp16chars000000",
    planHash: "p".repeat(64),
    authorityHash: fileSha256(prior)!,
  });
}

function assertUnseeded(dir: string): void {
  const destination = candidateFinalPath(dir, TOKEN, 2);
  assert.ok(!existsSync(destination), "round 2 must have no seeded final.mp4");
  assert.ok(!existsSync(`${destination}.assembled.json`), "round 2 must have no seeded sidecar");
  assert.ok(!existsSync(path.join(path.dirname(destination), "graphics_placements.json")),
    "round 2 must have no seeded placements sidecar");
  assert.deepEqual(readdirSync(path.dirname(destination)), [], "no partial seed files may remain");
}

const root = mkdtempSync(path.join(os.tmpdir(), "sniper-qc-seed-"));
try {
  // Valid graphics-free seed → the round holds exactly the prior bytes +
  // verbatim sidecar, which is what makes assemble.py's audio-only mux fast
  // path eligible; no graphicsTrack means no placements evidence is owed.
  const seeded = path.join(root, "seeded");
  const prior = writePriorRound(seeded);
  const sidecarRaw = validSidecar(prior);
  writeFileSync(`${prior}.assembled.json`, sidecarRaw);
  prepareQcRound(seeded, TOKEN, 2);
  assert.equal(seedQcRoundFromPriorCandidate(seeded, TOKEN, 2), true);
  const destination = candidateFinalPath(seeded, TOKEN, 2);
  assert.equal(readFileSync(destination, "utf8"), "prior-composited-video");
  assert.equal(readFileSync(`${destination}.assembled.json`, "utf8"), sidecarRaw);
  assert.deepEqual(
    readdirSync(path.dirname(destination)).sort(),
    ["final.mp4", "final.mp4.assembled.json"],
    "the seed is exactly the candidate + sidecar pair",
  );

  // Produced graphics → the prior round's graphics_placements.json rides along
  // verbatim, so Audit B's fail-closed eye_trace gate keeps its evidence when
  // assemble's mux fast path skips the composite that would rewrite it.
  const graphics = path.join(root, "graphics");
  const graphicsPrior = writePriorRound(graphics, undefined, GRAPHICS_PLAN);
  writeFileSync(`${graphicsPrior}.assembled.json`, validSidecar(graphicsPrior));
  const placementsRaw = JSON.stringify([{ kind: "stat-card", outStart: 1 }]);
  writeFileSync(path.join(path.dirname(graphicsPrior), "graphics_placements.json"), placementsRaw);
  prepareQcRound(graphics, TOKEN, 2);
  assert.equal(seedQcRoundFromPriorCandidate(graphics, TOKEN, 2), true);
  const graphicsDestination = candidateFinalPath(graphics, TOKEN, 2);
  assert.equal(
    readFileSync(path.join(path.dirname(graphicsDestination), "graphics_placements.json"), "utf8"),
    placementsRaw,
    "the eye-trace placements evidence must be copied verbatim",
  );
  assert.deepEqual(
    readdirSync(path.dirname(graphicsDestination)).sort(),
    ["final.mp4", "final.mp4.assembled.json", "graphics_placements.json"],
  );

  // Produced graphics but no placements evidence in the prior round →
  // unseeded (seeding would make Audit B's eye_trace gate fail the round).
  const evidenceless = path.join(root, "evidenceless");
  const evidencelessPrior = writePriorRound(evidenceless, undefined, GRAPHICS_PLAN);
  writeFileSync(`${evidencelessPrior}.assembled.json`, validSidecar(evidencelessPrior));
  prepareQcRound(evidenceless, TOKEN, 2);
  assert.equal(seedQcRoundFromPriorCandidate(evidenceless, TOKEN, 2), false);
  assertUnseeded(evidenceless);

  // No prior edit_plan.json → provenance unknown → unseeded.
  const planless = path.join(root, "planless");
  const planlessPrior = writePriorRound(planless, undefined, null);
  writeFileSync(`${planlessPrior}.assembled.json`, validSidecar(planlessPrior));
  prepareQcRound(planless, TOKEN, 2);
  assert.equal(seedQcRoundFromPriorCandidate(planless, TOKEN, 2), false);
  assertUnseeded(planless);

  // Hash mismatch (bytes no longer match the recorded authorityHash) →
  // unseeded, so assemble takes the full composite instead of a stale frame.
  const tampered = path.join(root, "tampered");
  const tamperedPrior = writePriorRound(tampered);
  writeFileSync(`${tamperedPrior}.assembled.json`, validSidecar(tamperedPrior));
  writeFileSync(tamperedPrior, "tampered-after-proof");
  prepareQcRound(tampered, TOKEN, 2);
  assert.equal(seedQcRoundFromPriorCandidate(tampered, TOKEN, 2), false);
  assertUnseeded(tampered);

  // Missing sidecar → unseeded (full composite).
  const bare = path.join(root, "bare");
  writePriorRound(bare);
  prepareQcRound(bare, TOKEN, 2);
  assert.equal(seedQcRoundFromPriorCandidate(bare, TOKEN, 2), false);
  assertUnseeded(bare);

  // Malformed sidecar JSON → unseeded.
  const malformed = path.join(root, "malformed");
  writePriorRound(malformed, "{not json");
  prepareQcRound(malformed, TOKEN, 2);
  assert.equal(seedQcRoundFromPriorCandidate(malformed, TOKEN, 2), false);
  assertUnseeded(malformed);

  // Sidecar missing a reuse hash (ambiguous provenance) → unseeded.
  const partial = path.join(root, "partial");
  const partialPrior = writePriorRound(partial);
  writeFileSync(`${partialPrior}.assembled.json`, JSON.stringify({
    videoFingerprint: "vfp16chars000000",
    authorityHash: fileSha256(partialPrior)!,
  }));
  prepareQcRound(partial, TOKEN, 2);
  assert.equal(seedQcRoundFromPriorCandidate(partial, TOKEN, 2), false);
  assertUnseeded(partial);

  // Round 1 has no prior round → never seeds.
  const first = path.join(root, "first");
  prepareQcRound(first, TOKEN, 1);
  assert.equal(seedQcRoundFromPriorCandidate(first, TOKEN, 1), false);
  assert.ok(!existsSync(candidateFinalPath(first, TOKEN, 1)));
} finally {
  rmSync(root, { recursive: true, force: true });
}

console.log("auto-edit-qc-seed.test.ts: all assertions passed");
