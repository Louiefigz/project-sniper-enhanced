import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { chmodSync, copyFileSync, mkdirSync, mkdtempSync, readFileSync,
  readdirSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { pythonInterpreter } from "../../../app/api/_lib/spawn-python";
import { executeVisualPlanUsage } from "../../../../scripts/producer/visual-plan-usage";
import { prepareVisualRelatedUsageAuthority } from
  "../../../app/api/producer/auto-edit/visual-plan-related-usage";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import { canonicalJson, canonicalJsonSha256, fileSha256 } from
  "../../server/auto-edit-hash";
import { nativeVisualUsageProjects } from "../../server/native-visual-usage-memory";
import { readNativeVisualUsageReceipt } from "../../server/native-visual-usage-reader";
import { registerNativeVisualUsage } from "../../server/native-visual-usage-receipt";
import { resolveVisualPlanBinding } from "../../server/visual-plan-binding";

const SHA = "f".repeat(64);

function json(file: string, value: unknown, canonical = false): void {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, canonical ? canonicalJson(value) : `${JSON.stringify(value)}\n`);
}

function allocatedPlan(root: string, mode: "short" | "long"): string {
  const file = path.join(root, `VISUAL-PLAN-${mode}.json`), pins = path.join(root, `pins-${mode}`);
  const code = [
    "import json,sys",
    "from _visual_plan_fixture import candidate,opportunity,visual_plan,reseal_controller_authorities,materialize_plan_pins",
    "mode=sys.argv[3]",
    "item=candidate('candidate:usage','text',routeClass='native')",
    "value=visual_plan(opportunity('opp:usage',0,[item]))",
    "value['project']['mode']=mode",
    "value['project']['aspect']='9:16' if mode=='short' else '16:9'",
    "value=reseal_controller_authorities(value)",
    "value=materialize_plan_pins(value,sys.argv[2])",
    "open(sys.argv[1],'w').write(json.dumps(value))",
  ].join("\n");
  execFileSync(pythonInterpreter(), ["-B", "-c", code, file, pins, mode], {
    cwd: path.join(process.cwd(), "scripts/producer"),
    env: { ...process.env, PYTHONPATH: ".:tests", PYTHONDONTWRITEBYTECODE: "1" },
  });
  const cli = path.join(process.cwd(), "scripts/producer/planner/visual_plan_cli.py");
  const allocated = execFileSync(pythonInterpreter(), ["-B", cli, "allocate", file], {
    encoding: "utf8", env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1",
      SNIPER_PIPELINE_ROOT: process.cwd() },
  });
  writeFileSync(file, allocated);
  return file;
}

function application(file: string, route: "native-short" | "native-long", variant: number) {
  const visual = JSON.parse(readFileSync(file, "utf8"));
  return { schemaVersion: 1, route, visualPlanSha256: canonicalJsonSha256(visual),
    decisions: visual.allocation.decisions.map((row: Record<string, unknown>) => ({
      opportunityId: row.opportunityId, candidateId: row.candidateId, variant,
    })) };
}

function pin(file: string): { path: string; sha256: string } {
  return { path: realpathSync(file), sha256: fileSha256(file)! };
}
function manifest(project: string, plan: Record<string, unknown>, files: string[]) {
  return { schemaVersion: 1, scope: "native-short-review-project",
    projectHash: canonicalJsonSha256(plan), files: files.map((file) => ({
      file: path.basename(file), sha256: fileSha256(file),
    })), elapsedMs: 1, sourceVerified: true, structuralStrategyChecks: "passed",
    reviewMethod: "independent", prebuildReview: { status: "recorded-independent-plan-pass" },
    pixelChecks: "not-run", audioChecks: "not-run", humanApproved: false };
}

interface Built { project: string; checked: string; checks: string; receipt?: string }
function clonedReceipt(source: string, directory: string, index: number): void {
  const prior = JSON.parse(readFileSync(source, "utf8"));
  const approvedAt = new Date(Date.UTC(2025, 0, index + 1)).toISOString();
  const { digest: _old, ...core } = prior;
  core.machineCheckedAt = approvedAt;
  core.project = { ...core.project, approvedAt, projectId: `historical-clone-${index}` };
  const digest = canonicalJsonSha256(core);
  const stamp = String(Date.parse(approvedAt)).padStart(13, "0");
  json(path.join(directory, `${stamp}-short-${digest}.json`), { ...core, digest });
}
function adversarialReceiptEntries(source: string, directory: string): void {
  for (let index = 0; index < 60; index += 1) clonedReceipt(source, directory, index);
  const malformed = `9999999999999-short-${"a".repeat(64)}.json`;
  json(path.join(directory, malformed), { malformed: true });
  const foreign = JSON.parse(readFileSync(source, "utf8"));
  const { digest: _old, ...core } = foreign;
  const foreignAt = "2099-01-01T00:00:00.000Z";
  core.producerDir = path.join(path.dirname(core.producerDir), "foreign-producer");
  core.machineCheckedAt = foreignAt;
  core.project = { ...core.project, approvedAt: foreignAt, projectId: "foreign-project" };
  const digest = canonicalJsonSha256(core);
  const stamp = String(Date.parse(foreignAt)).padStart(13, "0");
  json(path.join(directory, `${stamp}-short-${digest}.json`), { ...core, digest });
  writeFileSync(path.join(directory, `9999999999997-short-${"b".repeat(64)}.json`),
    Buffer.alloc(16 * 1024 * 1024 + 1));
  symlinkSync(source,
    path.join(directory, `9999999999996-short-${"c".repeat(64)}.json`));
}

function siblingUsageProject(
  workspace: string,
  source: string,
  index: number,
): string {
  const project = path.join(workspace, `history-${String(index).padStart(3, "0")}`);
  const producer = path.join(project, "producer");
  const directory = path.join(producer, ".sniper-visual-usage");
  mkdirSync(directory, { recursive: true });
  const prior = JSON.parse(readFileSync(source, "utf8"));
  const approvedAt = new Date(Date.UTC(2027, 0, index + 1)).toISOString();
  const { digest: _old, ...core } = prior;
  core.producerDir = producer;
  core.machineCheckedAt = approvedAt;
  core.project = { ...core.project, approvedAt, projectId: `native-short-bounded-${index}` };
  const digest = canonicalJsonSha256(core);
  const stamp = String(Date.parse(approvedAt)).padStart(13, "0");
  json(path.join(directory, `${stamp}-short-${digest}.json`), { ...core, digest });
  return approvedAt;
}

function legacyReceiptHistory(workspace: string, sources: string[]): {
  project: string; dates: string[];
} {
  const project = path.join(workspace, "legacy-over-64"), producer = path.join(project, "producer");
  const directory = path.join(producer, ".sniper-visual-usage"), dates: string[] = [];
  mkdirSync(directory, { recursive: true });
  for (let index = 0; index < 65; index += 1) {
    const prior = JSON.parse(readFileSync(sources[index % sources.length], "utf8"));
    const approvedAt = new Date(Date.UTC(2024, 0, index + 1)).toISOString();
    const { digest: _old, ...core } = prior;
    core.producerDir = producer;
    core.machineCheckedAt = approvedAt;
    core.project = { ...core.project, approvedAt, projectId: `native-short-legacy-${index}` };
    const digest = canonicalJsonSha256(core);
    json(path.join(directory, `${digest}.json`), { ...core, digest });
    dates.push(approvedAt);
  }
  return { project, dates };
}

function buildNative(
  producer: string,
  planSource: string,
  mode: "short" | "long",
  variant: number,
): Built {
  const route = mode === "short" ? "native-short" : "native-long";
  const project = path.join(path.dirname(producer), `native-${mode}-${variant}`);
  const checked = path.join(path.dirname(producer), `checked-${mode}-${variant}`);
  mkdirSync(project); mkdirSync(checked);
  const requestDir = path.join(producer, mode === "short" ? "native-shorts" : "native-longform",
    "requests", `request-${variant}`);
  const requestFile = path.join(requestDir, mode === "short" ? "SHORT-REQUEST.json" : "LONG-REQUEST.json");
  json(requestFile, { schemaVersion: 1, producerDir: producer });
  const binding = resolveVisualPlanBinding(planSource)!;
  const app = application(planSource, route, variant);
  copyFileSync(planSource, path.join(project, "VISUAL-PLAN.json"));
  const prebuildFile = path.join(project, "PREBUILD-REVIEW.json");
  json(prebuildFile, { schemaVersion: 1,
    scope: mode === "short" ? "native-short-full-plan" : "native-long-full-project",
    review: { verdict: "pass", materialIssues: [] } });
  const requestPacket = pin(requestFile);
  const projectFile = path.join(project, mode === "short" ? "SHORT-PROJECT.json" : "LONG-PROJECT.json");
  const projectPlan = mode === "short"
    ? { requestPacket, visualPlan: binding, strategy: { visualPlanApplication: app } }
    : { schemaVersion: 2, requestPacket, visualPlan: binding, visualPlanApplication: app };
  json(projectFile, projectPlan, true);
  const applicationFile = mode === "short"
    ? path.join(project, "VISUAL-PLAN-APPLICATION.json") : projectFile;
  if (mode === "short") {
    json(applicationFile, app, true);
    const files = [projectFile, path.join(project, "VISUAL-PLAN.json"), applicationFile, prebuildFile];
    json(path.join(project, "PROJECT-MANIFEST.json"), manifest(project, projectPlan, files), true);
  } else {
    json(path.join(project, "NATIVE-LONG-POLICY.json"), { schemaVersion: 1,
      requirement: "required-for-new-native-long", requestPacket }, true);
  }
  const supporting = mode === "short" ? path.join(project, "PROJECT-MANIFEST.json")
    : path.join(project, "NATIVE-LONG-POLICY.json");
  const inputs = [projectFile, planSource, applicationFile, prebuildFile, requestFile, supporting];
  const pins = Object.fromEntries(inputs.map((file) => [realpathSync(file), fileSha256(file)]));
  const request = { schemaVersion: 1, ...(mode === "long" ? { adapter: "native-long" } : {}),
    project, output: checked, pins };
  const requestPath = path.join(checked, "export-request.json");
  json(requestPath, request);
  const checks = path.join(checked, "checks.json");
  json(checks, { status: "checks-passed-awaiting-owned-cleanup",
    sha256: SHA, fullAudioVideoDecodePassed: true });
  const status = `${route}-checked-for-review`;
  const owner = path.join(checked, "verification.render.json");
  json(owner, { status, exitCode: 0, project, output: checks, abortReason: null,
    cleanup: { verified: true, survivors: [] },
    additionalFilePinsBefore: { ...pins, [requestPath]: fileSha256(requestPath) } });
  const review = path.join(checked, "review.mp4");
  writeFileSync(review, "TEST media bytes must never be read by usage memory");
  chmodSync(review, 0o000);
  json(path.join(checked, "delivery.json"), { status, output: review, sha256: SHA,
    fullAudioVideoDecodePassed: true, humanApproved: false,
    completedAt: `2026-09-${String(variant + 1).padStart(2, "0")}T00:00:00.000Z`,
    stages: [{ phase: "verification", receipt: owner,
      sha256: fileSha256(owner), status }] });
  return { project, checked, checks };
}

function main(): void {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "native-visual-usage-")));
  try {
    const workspace = path.join(root, "workspace"), prior = path.join(workspace, "prior");
    const current = path.join(workspace, "current"), producer = path.join(prior, "producer");
    mkdirSync(producer, { recursive: true }); mkdirSync(path.join(current, "producer"), { recursive: true });
    json(path.join(current, "project.json"), { intent: { mode: "short" } });
    const shortPlan = allocatedPlan(root, "short"), built: Built[] = [];
    for (let variant = 0; variant < 9; variant += 1) {
      const item = buildNative(producer, shortPlan, "short", variant);
      const registered = variant === 0
        ? executeVisualPlanUsage(["register", producer, item.project, item.checked])
        : registerNativeVisualUsage(producer, item.project, item.checked);
      item.receipt = registered.receipt;
      assert.equal(registered.registration.path,
        path.join(item.checked, "visual-usage-registration.json"));
      assert.equal(registered.registration.sha256,
        fileSha256(registered.registration.path));
      if (variant === 0) {
        const repeated = executeVisualPlanUsage(
          ["register", producer, item.project, item.checked],
        );
        assert.deepEqual(repeated.registration, registered.registration);
      }
      built.push(item);
    }
    const usageDirectory = path.dirname(built[0].receipt!);
    adversarialReceiptEntries(built[0].receipt!, usageDirectory);
    assert.ok(readdirSync(usageDirectory).length > 64);
    const newest = nativeVisualUsageProjects(prior, "short");
    assert.equal(newest.length, 8);
    assert.deepEqual(newest.map((row) => row.approvedAt), Array.from(
      { length: 8 }, (_, index) => `2026-09-${String(9 - index).padStart(2, "0")}T00:00:00.000Z`,
    ));
    const legacy = legacyReceiptHistory(workspace, built.map((row) => row.receipt!));
    assert.deepEqual(nativeVisualUsageProjects(legacy.project, "short")
      .map((row) => row.approvedAt), legacy.dates.slice(-8).reverse());
    const related = prepareVisualRelatedUsageAuthority(
      { dir: path.join(current, "producer") } as AutoEditCtx,
      { mode: "short", aspect: "9:16", durationFrames: 100, fps: { numerator: 30, denominator: 1 },
        intentSha256: SHA, acceptedProgramSha256: SHA, transcriptSha256: SHA },
      path.join(current, "producer", "RELATED-USAGE-AUTHORITY.json"),
    );
    const authority = JSON.parse(readFileSync(related.pin.path, "utf8"));
    assert.equal(authority.source, "validated-current-projects");
    assert.equal(authority.projectCount, 8);
    assert.equal(authority.projects[0].approvedAt, "2026-09-09T00:00:00.000Z");
    assert.equal(related.relatedUsage.length, 8);
    const currentProducer = path.join(current, "producer"), currentIds: string[] = [];
    for (const variant of [20, 21]) {
      const item = buildNative(currentProducer, shortPlan, "short", variant);
      currentIds.push(registerNativeVisualUsage(
        currentProducer, item.project, item.checked).project.projectId);
    }
    const currentUsage = prepareVisualRelatedUsageAuthority(
      { dir: currentProducer } as AutoEditCtx,
      { mode: "short", aspect: "9:16", durationFrames: 100,
        fps: { numerator: 30, denominator: 1 }, intentSha256: SHA,
        acceptedProgramSha256: SHA, transcriptSha256: SHA },
      path.join(currentProducer, "RELATED-USAGE-AUTHORITY.json"),
    );
    const currentAuthority = JSON.parse(readFileSync(currentUsage.pin.path, "utf8"));
    assert.equal(currentAuthority.projectCount, 8);
    assert.ok(currentIds.every((id) => currentAuthority.projects.some(
      (row: { projectId: string }) => row.projectId === id)));
    const longPlan = allocatedPlan(root, "long"), long = buildNative(producer, longPlan, "long", 0);
    const longReceipt = registerNativeVisualUsage(producer, long.project, long.checked);
    assert.equal(readNativeVisualUsageReceipt(longReceipt.receipt, producer).uses.length, 1);
    assert.equal(nativeVisualUsageProjects(prior, "long").length, 1);
    json(long.checks, { status: "changed" });
    assert.equal(nativeVisualUsageProjects(prior, "long").length, 0);
    const siblingDates = Array.from({ length: 70 }, (_, index) => siblingUsageProject(
      workspace, built[index % built.length].receipt!, index,
    ));
    const bounded = prepareVisualRelatedUsageAuthority(
      { dir: path.join(current, "producer") } as AutoEditCtx,
      { mode: "short", aspect: "9:16", durationFrames: 100,
        fps: { numerator: 30, denominator: 1 }, intentSha256: SHA,
        acceptedProgramSha256: SHA, transcriptSha256: SHA },
      path.join(current, "producer", "RELATED-USAGE-BOUNDED.json"),
    );
    const boundedValue = JSON.parse(readFileSync(bounded.pin.path, "utf8"));
    assert.equal(boundedValue.projectCount, 8);
    assert.deepEqual(boundedValue.projects.map((row: { approvedAt: string }) => row.approvedAt),
      siblingDates.slice(-8).reverse());
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

main();
console.log("native visual usage memory tests passed");
