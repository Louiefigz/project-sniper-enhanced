/** Actual source2 selection/approval/admission CAS; readiness/runtime/reduced opening observations are TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { bodyClaimServices, withFreshGuidedBodyAdmission, type FreshBodyAdmission } from "../guided-body-claim";
import { holdGuidedBodyInputUnderLease } from "../guided-body-authority";
import { readGuidedBodyClaim } from "../guided-body-lineage";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { guidedBodyInputReads, writeGuidedBodyMediaInput } from "../guided-body-input";
import { sourceColorBodyAuthorityFixture, type InitialBodySetup } from "./_guided-source-color-body-authority-fixture";
import type { FinalReadSetup } from "./_guided-source-color-read-integration-fixture";

/** Only the four approved metadata leaves differ; private admission and complete program checks remain real. */
function writerLeaves(t: TestContext, f: Awaited<ReturnType<typeof sourceColorBodyAuthorityFixture>>) {
  t.mock.method(guidedBodyInputReads, "readiness", (dir: string) => {
    assert.equal(dir, f.request.dir); return { ...f.proposal, ...observeHumanCutJob(dir) };
  });
  t.mock.method(guidedBodyInputReads, "mediaAuthority", () => f.reads.mediaAuthority());
  t.mock.method(guidedBodyInputReads, "runtime", () => f.selected.held.claim.runtime);
  t.mock.method(guidedBodyInputReads, "opening", (file: string, sha: string) => {
    assert.equal(file, f.selected.held.claim.inputPath); assert.equal(sha, f.selected.held.claim.inputSha256);
    return { ...f.f.staging.context.opening, authority: f.metadata.picture.authority } as unknown as ReturnType<typeof guidedBodyInputReads.opening>;
  });
}

/** Hold the actual fresh body lease for the callback; the existing admission service releases its own lock afterward. */
export async function bodyMediaInputAdmissionFixture(t: TestContext, initialize?: InitialBodySetup, finalize?: FinalReadSetup) {
  t.mock.timers.enable({ apis: ["Date"], now: Date.parse("2026-09-08T00:10:00.000Z") });
  const f = await sourceColorBodyAuthorityFixture(t, initialize, finalize); writerLeaves(t, f);
  f.request.lease.release();
  const services = { ...bodyClaimServices, canonicalDir: f.reads.canonicalDir, readiness: f.reads.readiness,
    hold: (request: Parameters<typeof bodyClaimServices.hold>[0]) => holdGuidedBodyInputUnderLease(request, f.reads) };
  return { f, async run<T>(operation: (value: { admission: ReturnType<typeof readGuidedBodyClaim>; context: FreshBodyAdmission;
    write: (guard?: () => void) => ReturnType<typeof writeGuidedBodyMediaInput> }) => Promise<T>) {
    return withFreshGuidedBodyAdmission({ dir: f.request.dir, submission: f.request.submission }, async context => {
      const admission = readGuidedBodyClaim(f.request.dir);
      return operation({ admission, context, write: (guard = context.budget.remainingMs) => writeGuidedBodyMediaInput(admission, guard, context.budget.remainingMs) });
    }, services);
  } };
}
export type BodyMediaInputAdmissionFixture = Awaited<ReturnType<typeof bodyMediaInputAdmissionFixture>>;

/** Replace only the newly published original invocation within this actual admitted TEST execution. */
export function replaceBodyWriterPublication(f: BodyMediaInputAdmissionFixture, execution: string): void {
  const root = fs.realpathSync(f.f.f.staging.root), file = path.join(execution, "body-media-input.json");
  assert(file.startsWith(path.join(root, "producer", "guided-v2-operations") + path.sep));
  assert.equal(fs.realpathSync(file), file); assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const temp = path.join(execution, `TEST-writer-replacement-${randomUUID()}.json`);
  fs.writeFileSync(temp, fs.readFileSync(file), { mode: 0o600, flag: "wx" }); fs.renameSync(temp, file);
}
