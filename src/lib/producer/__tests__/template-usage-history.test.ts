import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import {
  captureTemplateUsageAuthority,
  prepareTemplateUsageHistory,
  restoreTemplateUsageAuthority,
  templateUsageHistoryPath,
} from "../../server/template-usage-history";
import {
  canonicalJson, canonicalJsonSha256, fileSha256,
} from "../../server/auto-edit-hash";

interface PythonCanonical {
  raw: string;
  digest: string;
}

function pythonCanonical(value: unknown): PythonCanonical {
  const script = [
    "import hashlib, json, sys",
    "from cross_runtime_canonical_json import canonical_compact_json",
    "value = json.load(sys.stdin)",
    "raw = canonical_compact_json(value)",
    "print(json.dumps({'raw': raw, 'digest': hashlib.sha256(raw.encode('utf-8')).hexdigest()}, ensure_ascii=False))",
  ].join("; ");
  const result = spawnSync(path.join(process.cwd(), ".venv", "bin", "python3"), ["-c", script], {
    input: JSON.stringify(value), encoding: "utf8",
    env: {
      ...process.env,
      PYTHONPATH: path.join(process.cwd(), "scripts", "producer"),
    },
  });
  if (result.status !== 0) throw new Error(result.stderr || result.stdout);
  return JSON.parse(result.stdout) as PythonCanonical;
}

function crossLanguageDigestContract(): void {
  const fixturePath = path.join(__dirname, "fixtures", "template-usage-history-core.json");
  const fixture = JSON.parse(readFileSync(fixturePath, "utf8")) as unknown;
  const python = pythonCanonical(fixture);
  assert.equal(canonicalJson(fixture), python.raw,
    "TypeScript and Python must hash identical template-history bytes");
  assert.equal(canonicalJsonSha256(fixture), python.digest);
  assert.match(python.raw, /"policy":\{"minProjectShare":0\.5,"minProjects":3\}/,
    "case-sensitive code-point order prevents localeCompare policy drift");
  const edge = {
    policy: { minProjectShare: 1e-7, minProjects: 3 },
    numericKeys: { "10": "ten", "2": "two" },
  };
  const edgePython = pythonCanonical(edge);
  assert.equal(canonicalJson(edge), edgePython.raw);
  assert.equal(canonicalJsonSha256(edge), edgePython.digest);
}

function project(root: string, id: string, mode: string, kinds: string[]): string {
  const dir = path.join(root, id, "producer");
  mkdirSync(dir, { recursive: true });
  writeFileSync(path.join(dir, "edit_plan.json"), JSON.stringify({
    target: { mode }, graphicsTrack: kinds.map((kind) => ({ kind })),
  }));
  return dir;
}

function context(dir: string): AutoEditCtx {
  return {
    dir, scope: "produced", intent: { mode: "longform" },
    planPath: path.join(dir, "edit_plan.json"),
    manifestPath: path.join(dir, "asset_manifest.json"), transcriptsDir: dir,
    doctrine: { runId: "history-run", doctrineHash: "a".repeat(64),
      snapshotPath: path.join(dir, "doctrine.json"), files: {} },
  };
}

function verifiedMirror(
  producerDir: string,
  planHash: string,
  ownership: "sniper" | "palmier",
  pushedPlanHash = planHash,
): void {
  const projectPath = path.join(path.dirname(producerDir), "edit.palmier");
  mkdirSync(projectPath, { recursive: true });
  writeFileSync(path.join(producerDir, "palmier.sync.json"), JSON.stringify({
    schemaVersion: 4, ownership, workspaceMode: "verified-mirror",
    mirrorMode: "visual-master", projectId: path.basename(path.dirname(producerDir)),
    projectPath, latestTimelineId: "timeline-1", lastPushPlanHash: pushedPlanHash,
    parity: { mirrorReady: true },
    verification: { ok: true, planHash: pushedPlanHash, timelineId: "timeline-1" },
  }));
}

function palmierOwnershipFiltering(): void {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-template-palmier-history-"));
  try {
    const current = project(root, "current", "longform", []);
    const sniperOnly = project(root, "sniper-only", "longform", ["line-swap"]);
    const inSync = project(root, "in-sync", "longform", ["chart-story"]);
    const humanOwned = project(root, "human-owned", "longform", ["hw-callout-circle"]);
    const diverged = project(root, "diverged", "longform", ["marker-highlight"]);
    const hashes = new Map([sniperOnly, inSync, humanOwned, diverged].map((dir) =>
      [dir, fileSha256(path.join(dir, "edit_plan.json"))]));
    verifiedMirror(inSync, hashes.get(inSync)!, "sniper");
    verifiedMirror(humanOwned, hashes.get(humanOwned)!, "palmier");
    verifiedMirror(diverged, hashes.get(diverged)!, "sniper", "f".repeat(64));
    const { history } = captureTemplateUsageAuthority(context(current), root, {
      approved: (dir) => {
        const planHash = hashes.get(dir);
        return planHash ? { approvedAt: "2026-07-08T00:00:00.000Z", planHash } : null;
      },
    });
    assert.equal(history.projectCount, 2);
    assert.deepEqual(history.projects.map((row) => row.projectId).sort(),
      ["in-sync", "sniper-only"],
      "verified current mirrors and Sniper-only projects teach; human or stale mirrors do not");
    assert.equal(history.counts["hw-callout-circle"], undefined);
    assert.equal(history.counts["marker-highlight"], undefined);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

function main(): void {
  crossLanguageDigestContract();
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-template-history-"));
  try {
    const current = project(root, "current", "longform", []);
    project(root, "one", "longform", ["line-swap", "chart-story"]);
    project(root, "two", "longform", ["line-swap", "line-swap"]);
    project(root, "three", "longform", ["line-swap"]);
    project(root, "four", "longform", ["hw-callout-circle", "unknown-kind"]);
    project(root, "vertical", "short", ["line-swap"]);
    project(root, "drifted", "longform", ["line-swap"]);
    const approvals = new Map([
      ["one", "2026-07-01T00:00:00.000Z"],
      ["two", "2026-07-02T00:00:00.000Z"],
      ["three", "2026-07-03T00:00:00.000Z"],
      ["four", "2026-07-04T00:00:00.000Z"],
      ["vertical", "2026-07-05T00:00:00.000Z"],
      ["current", "2026-07-06T00:00:00.000Z"],
      ["drifted", "2026-07-07T00:00:00.000Z"],
    ]);
    const ctx = context(current);
    const bound = captureTemplateUsageAuthority(ctx, root, {
      approved: (dir) => {
        const id = path.basename(path.dirname(dir));
        const approvedAt = approvals.get(id);
        if (!approvedAt) return null;
        const planHash = id === "drifted"
          ? "f".repeat(64) : fileSha256(path.join(dir, "edit_plan.json"));
        return planHash ? { approvedAt, planHash } : null;
      },
    });
    const { history } = bound;
    assert.deepEqual(restoreTemplateUsageAuthority({
      ...ctx, templateUsage: bound.authority,
    }, bound.authority).history, history);
    assert.throws(() => restoreTemplateUsageAuthority(ctx, {
      ...bound.authority, digest: "0".repeat(64),
    }), /no longer matches/);
    assert.equal(history.projectCount, 4,
      "current, other-mode, and post-approval plan drift are excluded");
    assert.equal(history.counts["line-swap"].uses, 4);
    assert.equal(history.counts["line-swap"].projects, 3);
    assert.deepEqual(history.overusedKinds, ["line-swap"]);
    assert.equal(history.counts["unknown-kind"], undefined);
    assert.equal(history.projects[0].projectId, "four", "approval time owns recency");

    project(root, "later", "longform", ["chart-story"]);
    const reused = prepareTemplateUsageHistory(ctx, root, {
      approved: () => ({ approvedAt: "2026-08-01T00:00:00.000Z", planHash: "f".repeat(64) }),
    });
    assert.deepEqual(reused, history, "one run reuses its pinned history snapshot");

    writeFileSync(templateUsageHistoryPath(ctx), "{}\n");
    assert.throws(() => prepareTemplateUsageHistory(ctx, root), /changed after capture/);
    palmierOwnershipFiltering();
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("template-usage-history.test.ts: all assertions passed");
}

main();
