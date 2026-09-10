/** TEST staging metadata only: no source bytes, full admission, runtime or clock lineage qualification. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import type { TestContext } from "node:test";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { parseGuidedOpeningExecutionClaim, type OpeningRuntimeControlV1 } from "@/lib/producer/contracts/guided-opening-claim-v1";
import { canonicalJson } from "../auto-edit-hash";
import { acquireProjectMutationLease, type ProjectMutationLease } from "../project-mutation-lease";
import { sourceColorExpectations } from "../guided-source-color-expectations";
import { GUIDED_SOURCE_COLOR_TS_FILES } from "../guided-source-color-staging";
import { sourceColorFixture, testSha } from "./_guided-source-color-expectations-fixture";

type OriginalFixture = ReturnType<typeof sourceColorFixture>;
const REQUEST_ID = "a8b9ce05-29ec-4bba-93cf-982d811ed137";

/** Create only private, new TEST artifacts; never overwrite an existing source or execution. */
function artifact(file: string, bytes: string | Buffer): string {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  fs.writeFileSync(file, bytes, { flag: "wx", mode: 0o600 });
  return testSha(bytes);
}

/** These bytes are inventoried but never imported or executed by this metadata fixture. */
function implementation(root: string): void {
  artifact(path.join(root, "scripts/producer/TEST_staging.py"), "# TEST inert implementation; never executed\n");
  for (const name of ["grade-observation-store.ts", "grade-observation-process.ts", "grade-observation-service.ts", "grade-observation-resource.ts"]) {
    artifact(path.join(root, "src/lib/server", name), `// TEST inert ${name}; never executed\n`);
  }
  for (const relative of GUIDED_SOURCE_COLOR_TS_FILES) {
    const file = path.join(root, relative);
    if (!fs.existsSync(file)) artifact(file, `// TEST inert additional required pin ${relative}; never executed\n`);
  }
}

/** Closed shape only: the regular placeholder is NOT an observed Docker socket or approved image. */
function runtime(root: string): OpeningRuntimeControlV1 {
  const dockerPath = path.join(root, "TEST-runtime/docker"), dockerSocketPath = path.join(root, "TEST-runtime/docker.sock");
  const imageApprovalPath = path.join(root, "templates/motion/render_image_approval.json");
  const dockerSha256 = artifact(dockerPath, "TEST nonexecutable Docker placeholder\n");
  artifact(dockerSocketPath, "TEST regular-file socket placeholder, not daemon authority\n");
  const imageApprovalSha256 = artifact(imageApprovalPath, "{\"TEST\":\"not an image approval\"}\n");
  const socket = fs.lstatSync(dockerSocketPath, { bigint: true });
  return { dockerPath, dockerSha256, dockerSocketPath, dockerSocketDevice: String(socket.dev), dockerSocketInode: String(socket.ino),
    imageId: `sha256:${testSha("TEST nonexistent image")}`, userId: "501:20", imageApprovalPath, imageApprovalSha256, runtimeRepoRoot: root };
}

/** Rehouse identical raw input, retaining every old document ref and semantic hash unchanged. */
function opening(fixture: OriginalFixture, lineage: OpeningLineage = {}) {
  const { context } = fixture, originalPath = context.inputPath, original = fs.lstatSync(originalPath);
  assert.equal(fs.realpathSync(originalPath), originalPath); assert(original.isFile()); assert.equal(original.nlink, 1);
  const bytes = fs.readFileSync(originalPath); assert.equal(testSha(bytes), context.opening.inputSha256);
  const execution = path.join(context.producerDir, "guided-v2-operations", REQUEST_ID, "executions", context.opening.input.executionId);
  const inputPath = path.join(execution, "media-input/input.json"), inputSha256 = artifact(inputPath, bytes);
  const outputRoot = path.join(execution, "media-output"); fs.mkdirSync(outputRoot, { mode: 0o700 });
  context.inputPath = inputPath;
  const claim = parseGuidedOpeningExecutionClaim({ schemaVersion: 1, kind: "guided-opening-execution-claim",
    scope: "private-opening-owned-execution-not-approval", requestId: REQUEST_ID, executionId: context.opening.input.executionId,
    beforeJournalHash: testSha("TEST unobserved original journal"), inputPath, inputSha256,
    executionInputHash: context.opening.input.executionInputHash, outputRoot, clockHash: testSha("TEST unobserved original clock"),
    generationStartedAt: "2026-09-08T00:00:00.000Z", budgetAdmissionHash: testSha("TEST unobserved original budget admission"),
    selectedGraphicOrders: [], runtime: runtime(fixture.root), ...lineage });
  const claimPath = path.join(execution, "execution-claim.json"), claimSha256 = artifact(claimPath, canonicalJson(claim));
  return { claim, claimPath, claimSha256 };
}

/** Acquire only this fixture's actual live lock; never resolve the real workspace namespace. */
type OpeningLineage = Partial<Pick<ReturnType<typeof parseGuidedOpeningExecutionClaim>,
  "beforeJournalHash" | "clockHash" | "generationStartedAt" | "budgetAdmissionHash">>;
export function sourceColorStagingFixture(t: TestContext, beforeOpening?: (fixture: OriginalFixture) => OpeningLineage) {
  const owned: { lease?: ProjectMutationLease } = {};
  // Registered before the base fixture's tree cleanup, so the original lock is released first.
  t.after(() => { owned.lease?.release(); });
  const fixture = sourceColorFixture(t), { context } = fixture;
  fs.chmodSync(context.producerDir, 0o700); implementation(fixture.root);
  const lineage = beforeOpening?.(fixture);
  const heldOpening = opening(fixture, lineage), resource = path.join(fixture.root, ".sniper-color-resource");
  fs.mkdirSync(resource, { mode: 0o700 });
  // Base fixture root has project.json; keep mutationProjectRoot on this actual resource lock.
  artifact(path.join(resource, "project.json"), "{\"TEST\":\"lease root marker only; not a project or admission\"}\n");
  const acquired = acquireProjectMutationLease(resource, "TEST fixture-only source color staging");
  assert(acquired.lease); const lease = acquired.lease; owned.lease = lease;
  const assertResource = cutPreviewLeaseGuard(resource, lease); assertResource();
  const expectations = sourceColorExpectations(context);
  return { ...fixture, opening: heldOpening, resource: { resource, lease, assertResource }, expectations,
    sourceColor: context.selection, producerDir: context.producerDir, guard: context.guard };
}
