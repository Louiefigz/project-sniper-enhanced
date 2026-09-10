import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { planObjectContentHash } from "@/lib/server/auto-edit-authority";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { runCutRepairAnalysis } from
  "@/app/api/producer/ai-edit/cut-repair-route-runner";

function sha(bytes: Buffer | string): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function writeJson(filePath: string, value: unknown): string {
  const bytes = Buffer.from(JSON.stringify(value), "utf8");
  fs.writeFileSync(filePath, bytes);
  return sha(bytes);
}

function media(filePath: string, value: string): string {
  fs.writeFileSync(filePath, value);
  return sha(value);
}

interface Fixture {
  root: string;
  producer: string;
  manifest: string;
}

function fixture(): Fixture {
  const root = fs.realpathSync(fs.mkdtempSync(
    path.join(os.tmpdir(), "p2-route-runner-")));
  const producer = path.join(root, "producer");
  const sourceDir = path.join(root, "source");
  fs.mkdirSync(producer);
  fs.mkdirSync(sourceDir);
  const sourcePath = path.join(sourceDir, "raw.mov");
  const parentPath = path.join(producer, "parent.mov");
  const sourceHash = media(sourcePath, "source");
  const parentHash = media(parentPath, "parent");
  writeJson(path.join(sourceDir, "raw.transcript.json"), {
    transcript: [{
      speaker: "host",
      words: [
        { word: "use", start: 0.8, end: 0.95 },
        { word: "automation", start: 1, end: 1.1 },
      ],
    }],
  });
  const plan = {
    planVersion: 1,
    target: { mode: "longform", fps: 30 },
    cutTrack: [
      { id: "seg-a", sourceId: "raw", start: 0, end: 1.05, speed: 1 },
      { id: "seg-b", sourceId: "raw", start: 2, end: 5, speed: 1 },
    ],
  };
  const planSha = writeJson(path.join(producer, "edit_plan.json"), plan);
  const manifest = path.join(sourceDir, "manifest.json");
  const manifestHash = writeJson(manifest, {
    sources: [{
      id: "raw", path: sourcePath, contentHash: sourceHash,
      transcriptPath: "raw.transcript.json", fps: 30, vfr: false,
      audio: { sampleRate: 48_000 },
    }],
  });
  const revision = {
    schemaVersion: 1, workflowState: "PICTURE_LOCKED",
    pictureLockHash: "7".repeat(64), timelineMapHash: "8".repeat(64),
    planContentHash: planObjectContentHash(plan)!, manifestHash,
  };
  const revisionBytes = Buffer.from(JSON.stringify(revision), "utf8");
  const head = sha(revisionBytes);
  const authority = path.join(producer, ".sniper-authority-v1");
  const revisions = path.join(authority, "objects", "revisions");
  fs.mkdirSync(revisions, { recursive: true });
  fs.writeFileSync(path.join(revisions, `${head}.json`), revisionBytes);
  fs.writeFileSync(path.join(authority, "ACTIVE_HEAD"), `${head}\n`);
  const evidence = {
    schemaVersion: 1, kind: "cut-repair-acoustic-evidence",
    parentRevisionHash: head, planSha256: planSha,
    manifestSha256: manifestHash, sourceId: "raw",
    alignment: {
      status: "pinned-bounded-evidence",
      receiptSha256: "1".repeat(64), runtimeSha256: "2".repeat(64),
      modelSha256: "3".repeat(64), cacheSha256: "4".repeat(64),
    },
    vad: {
      status: "pinned-bounded-evidence",
      receiptSha256: "5".repeat(64),
    },
    audition: {
      status: "operator-reported-damage",
      receiptSha256: "6".repeat(64),
    },
    audioIsolation: {
      status: "dialogue-only-bounded-evidence",
      receiptSha256: "9".repeat(64),
      runtimeSha256: "a".repeat(64),
      musicSfxOverlapCount: 0,
    },
    silences: [],
    coveredPicture: [{ startFrame: 32, endFrameExclusive: 34 }],
    replaceableAudio: [{
      startSample: 51_200, endSampleExclusive: 53_600,
    }],
    replaceableAudioEvidenceHash: "5".repeat(64),
    dependents: [],
    parentMedia: { path: parentPath, sha256: parentHash },
    maxDirtyFrames: 120, maxAudioOverlapFrames: 15,
  };
  writeJson(path.join(
    producer, "cut_repair_acoustic_evidence_v1.json"), {
    ...evidence, authorityHash: canonicalJsonSha256(evidence),
  });
  return { root, producer, manifest };
}

const target = {
  schemaVersion: 1 as const,
  operation: "cut.restoreSpeech" as const,
  mode: "analyze" as const,
  target: { phrase: "automation" },
};

async function run(): Promise<void> {
  const value = fixture();
  try {
    const result = await runCutRepairAnalysis(
      value.producer, value.manifest, target);
    assert.equal(result.status, "eligible");
    const recommended = result.recommendedCandidate as {
      operation: { method: string };
    };
    assert.equal(recommended.operation.method, "audio-lj-overlap");
    assert.equal(fs.existsSync(path.join(
      value.producer, "cut_repair_context_v1.json")), false);
    fs.unlinkSync(path.join(
      value.producer, "cut_repair_acoustic_evidence_v1.json"));
    await assert.rejects(
      runCutRepairAnalysis(value.producer, value.manifest, target),
      /cut_repair_acoustic_evidence_v1\.json/,
    );
  } finally {
    fs.rmSync(value.root, { recursive: true, force: true });
  }
}

run()
  .then(() => console.log("p2-cut-repair-route-runner tests passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
