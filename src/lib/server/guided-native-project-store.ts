/** Publish a reconstructed native proposal through the shared project writer. */
import path from "node:path";
import { readGuidedTreatmentProposal } from "./guided-proposal-store";
import type { GuidedNativeVisualPlan } from "./guided-native-project";
import { assertGuidedNativeGeometry, guidedNativeSourceMedia } from "./guided-native-geometry";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { humanCutDirectory } from "./human-cut-acceptance-store";
import { timedStage } from "./stage-timing";
import { prepareNativeCaptionGroups } from "./guided-native-captions";
import type { NativeShortDirection } from "./guided-native-candidate";
import { writeNativeShortProject } from "./native-short-project";
import { assertGuidedNativeAuthority } from "./guided-native-authority";
import { buildGuidedNativeBinding, guidedNativeRequestMarker } from "./guided-native-binding";
import { nativeProposalPreparationAllowed } from "./guided-native-supporting";
import { assertNativeShortPrebuildReview } from "./native-short-prebuild-review";

export interface GuidedNativeProjectDependencies {
  readGuidedProposal?: typeof readGuidedTreatmentProposal;
  prepareCaptionGroups?: typeof prepareNativeCaptionGroups;
}

function assertAuthority(visual: GuidedNativeVisualPlan, proposal: ReturnType<typeof readGuidedTreatmentProposal>): void {
  assertGuidedNativeAuthority(visual.project, { intent: proposal.job.ctx.intent,
    manifest: { path: proposal.job.ctx.manifestPath, sha256: proposal.manifest.sha256, value: proposal.manifest.value } });
}

/** No contained-source fallback and no mutation of an accepted Studio edit. */
export async function writeGuidedNativeProject(dir: string, remainingMs: () => number, visual?: GuidedNativeVisualPlan,
  dependencies: GuidedNativeProjectDependencies = {}) {
  remainingMs();
  const readProposal = dependencies.readGuidedProposal ?? readGuidedTreatmentProposal;
  const proposal = readProposal(dir), candidate = proposal.result.candidate;
  if (!nativeProposalPreparationAllowed(proposal.result) || !candidate) {
    throw new Error("Native project needs a supported reconstructed V9/V10 development candidate");
  }
  if (!visual) throw new Error("Native visual strategy and inspected crop/title/caption geometry are required before assembly");
  assertNativeShortPrebuildReview(visual.project);
  assertAuthority(visual, proposal);
  const parent = humanCutDirectory(dir, "native-development"), directory = path.join(parent, proposal.proposalHash);
  return timedStage(dir, "native_short_project_write", async () => {
    const preparation = humanCutDirectory(parent, `${proposal.proposalHash}-preparation`);
    const groups = await (dependencies.prepareCaptionGroups ?? prepareNativeCaptionGroups)({ directory: preparation, direction: candidate.nativeDirection as NativeShortDirection,
      pipelineRoot: proposal.job.ctx.pipeline!.snapshotRoot, remainingMs });
    const media = guidedNativeSourceMedia(visual.project, proposal.manifest.value.sources);
    assertGuidedNativeGeometry(candidate, media, groups, visual);
    const project = { ...visual.project, guidedBinding: buildGuidedNativeBinding(visual.project, proposal, visual.assetResolutions) };
    const current = readProposal(dir);
    if (canonicalJsonSha256(guidedNativeRequestMarker(current)) !== canonicalJsonSha256(project.guidedBinding.marker)) throw new Error("Native proposal changed before publication");
    assertAuthority(visual, current);
    remainingMs();
    const result = writeNativeShortProject(project, directory, { readGuidedProposal: readProposal });
    const published = readProposal(dir);
    if (canonicalJsonSha256(guidedNativeRequestMarker(published)) !== canonicalJsonSha256(project.guidedBinding.marker)) throw new Error("Native proposal changed during publication; retained project is not admitted");
    assertAuthority(visual, published);
    return result;
  });
}
