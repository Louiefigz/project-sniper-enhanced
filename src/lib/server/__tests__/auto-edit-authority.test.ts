import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  planContentHash,
  planObjectContentHash,
} from "../auto-edit-authority";

const root = mkdtempSync(path.join(os.tmpdir(), "sniper-authority-hash-"));
try {
  const planPath = path.join(root, "edit_plan.json");
  writeFileSync(planPath, JSON.stringify({
    planVersion: 2,
    _private: "ignored",
    title: "Café",
    graphicsTrack: [{ id: "g1", text: "A", x: 30.0 }],
    cutTrack: [],
  }));
  assert.equal(
    planContentHash(planPath),
    "db7bebe2a120cdcf84e01030226daa7fed66ddc3baa9150b2a95331bcff043c1",
    "TypeScript canonical hashing must match fingerprints.py",
  );
  const clean = { cutTrack: [{ sourceId: "raw-1", start: 0, end: 1 }] };
  const metadata = {
    ending: "addressing-only",
    transitionRationale: "addressing-only",
    treatmentMap: { addressing: true },
    cutTrack: [{
      ...clean.cutTrack[0],
      id: "segment-1", generation: 2, version: 2,
      sourceAnchor: "word-1", dependencies: ["caption-1"],
      confidence: 0.9, evidence: ["word-1"], rationale: "because",
      reason: "repair", semanticBeatId: "beat-1", trigger: "speech",
    }],
  };
  assert.equal(planObjectContentHash(metadata), planObjectContentHash(clean));
  assert.equal(
    planObjectContentHash({
      ...clean,
      cutDecisions: { schemaVersion: 1, removals: [] },
    }),
    planObjectContentHash(clean),
    "cut decisions are non-render receipt data in both runtimes",
  );
  assert.equal(
    planObjectContentHash({ x: 1e-7 }),
    "4edc61b9f1a875cc21382a6e2224f7ca85f7d32e1747caf5071276ce760035c1",
  );
  assert.equal(
    planObjectContentHash({
      "\ue000": "bmp", "😀": "astral", lone: "\ud800",
    }),
    "f5716c4dd1b4fb8f6045dbe8215672cd1577bc404cd7c253b10679981c423bb9",
  );
  assert.equal(planObjectContentHash({ x: Number.NaN }), undefined);
  assert.equal(
    planObjectContentHash({ x: Number.MAX_SAFE_INTEGER + 1 }),
    undefined,
  );
  console.log("auto-edit-authority.test.ts: all assertions passed");
} finally {
  rmSync(root, { recursive: true, force: true });
}
