import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import type { CutRestoreSpeechV1 } from
  "@/lib/producer/contracts/cut-restore-speech-v1";
import {
  pythonInterpreter,
  SCRIPTS_DIR,
} from "@/app/api/_lib/spawn-python";
import { canonicalJsonSha256, fileSha256 } from "../auto-edit-hash";
import { cutRepairProofFixture } from
  "./_p2-cut-repair-promotion-fixture";

interface RenderedProofAuthority {
  approvedCutRevisionHash: string;
  planObjectHash: string;
  planContentHash: string;
  renderGraphHash: string;
  renderGraphReceiptHash: string;
  candidatePointerHash: string;
  candidatePath: string;
  sourceSnapshotSetHash: string;
  transcriptTimingHash: string;
  workflowPolicy: "cut-first" | "autopilot";
  selectedApproval: {
    approver: "operator" | "system-policy";
    approvalPolicyHash: string;
    approvalReceiptHash: string;
  };
}

type Proof = ReturnType<typeof cutRepairProofFixture>;
let observedToolchainHash: string | undefined;

/** Resolve the exact Python render/staging closure used by live promotion. */
export function currentRenderToolchainHash(): string {
  if (observedToolchainHash) return observedToolchainHash;
  const result = spawnSync(pythonInterpreter(), [
    "-c",
    "from current_render_toolchain import current_toolchain_hash; "
      + "print(current_toolchain_hash())",
  ], {
    cwd: path.join(SCRIPTS_DIR, "producer"),
    encoding: "utf8",
    timeout: 120_000,
    env: { ...process.env },
  });
  const value = result.stdout.trim();
  if (result.status !== 0 || !/^[0-9a-f]{64}$/u.test(value)) {
    throw new Error(
      result.stderr.trim() || "current render toolchain hash failed");
  }
  observedToolchainHash = value;
  return value;
}

export function writeRealCutRepairCandidate(candidatePath: string): void {
  const result = spawnSync("ffmpeg", [
    "-nostdin", "-hide_banner", "-loglevel", "error",
    "-f", "lavfi", "-i", "color=c=navy:s=320x240:r=30:d=3",
    "-f", "lavfi", "-i",
    "sine=frequency=440:duration=3:sample_rate=48000",
    "-map", "0:v:0", "-map", "1:a:0",
    "-c:v", "libx264", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-shortest", "-y", candidatePath,
  ], { encoding: "utf8", timeout: 30_000 });
  if (result.status !== 0) {
    throw new Error(result.stderr || "real lifecycle candidate render failed");
  }
}

function descriptor(
  candidate: Record<string, unknown>,
  timelineMapHash: string,
  authority: RenderedProofAuthority,
) {
  const composite = candidate.compositeReceipt as {
    output: { path: string };
  };
  const fallback = path.join(
    path.dirname(composite.output.path), "full-plan-candidate.mp4");
  const candidatePath = authority.candidatePath || fallback;
  if (!fs.existsSync(candidatePath)) {
    fs.writeFileSync(candidatePath, "exact rendered plan fixture\n");
  }
  return {
    schemaVersion: 1,
    kind: "cut-repair-rendered-plan-candidate",
    status: "candidate-proved",
    operationHash: candidate.operationHash,
    reviewPlanObjectHash: authority.planObjectHash,
    reviewPlanContentHash: authority.planContentHash,
    reviewTimelineMapHash: timelineMapHash,
    reviewRenderGraphHash: authority.renderGraphHash,
    reviewRenderGraphReceiptHash: authority.renderGraphReceiptHash,
    reviewRenderGraphCandidatePointerHash: authority.candidatePointerHash,
    candidatePath,
    candidateSha256: fileSha256(candidatePath)!,
  };
}

function candidateParts(
  candidate: Record<string, unknown>,
  rendered: Record<string, unknown>,
) {
  return {
    fragment: canonicalJsonSha256(candidate.fragmentReceipt),
    composite: canonicalJsonSha256(candidate.compositeReceipt),
    pictureLock: canonicalJsonSha256(candidate.childPictureLock),
    supersession: canonicalJsonSha256(candidate.supersessionReceipt),
    caption: canonicalJsonSha256(candidate.captionRevalidation),
    palmier: canonicalJsonSha256(candidate.palmierDisposition),
    rendered: canonicalJsonSha256(rendered),
  };
}

function invariant(
  candidate: Record<string, unknown>,
  rendered: Record<string, unknown>,
  parts: ReturnType<typeof candidateParts>,
) {
  return {
    schemaVersion: 2,
    kind: "cut-repair-invariant-proof",
    operationHash: candidate.operationHash,
    fragmentReceiptHash: parts.fragment,
    childPictureLockHash: parts.pictureLock,
    supersessionHash: parts.supersession,
    palmierDispositionHash: parts.palmier,
    captionRevalidationHash:
      (candidate.captionRevalidation as { revalidationHash: string })
        .revalidationHash,
    diagnosticCompositeReceiptHash: parts.composite,
    renderedCandidateHash: parts.rendered,
    terminalRenderedPlanProved: true,
    terminalCandidateSha256: rendered.candidateSha256,
    totalOutputFramesPreserved: true,
  };
}

function evidence(
  base: Proof,
  operationHash: string,
  renderedSha256: unknown,
): Record<string, unknown> {
  const old = base.proof.promotionEvidence as Record<string, unknown>;
  const lanes = ["alignment", "vad", "retranscription", "seam", "audition"];
  const changed = Object.fromEntries(lanes.map((lane) => {
    const item = old[lane] as Record<string, unknown>;
    const receipt = {
      ...(item.receipt as Record<string, unknown>),
      candidateCompositeSha256: renderedSha256,
    };
    return [lane, {
      ...item,
      candidateCompositeSha256: renderedSha256,
      receipt,
      receiptHash: canonicalJsonSha256(receipt),
    }];
  }));
  return {
    schemaVersion: 1,
    kind: "cut-repair-promotion-evidence",
    operationHash,
    candidateCompositeSha256: renderedSha256,
    ...changed,
  };
}

/** Upgrade the diagnostic fixture so terminal authority is a full-plan MP4. */
export function cutRepairRenderedProofFixture(
  producer: string,
  action: CutRestoreSpeechV1,
  childTimelineMapHash: string,
  authority: RenderedProofAuthority,
): Proof {
  const base = cutRepairProofFixture(
    producer, action, childTimelineMapHash, {
      approvedCutRevisionHash: authority.approvedCutRevisionHash,
      planContentHash: authority.planContentHash,
      sourceSnapshotSetHash: authority.sourceSnapshotSetHash,
      transcriptTimingHash: authority.transcriptTimingHash,
      workflowPolicy: authority.workflowPolicy,
      selectedApproval: authority.selectedApproval,
    });
  const original = base.proof.candidate as Record<string, unknown>;
  const rendered = descriptor(original, childTimelineMapHash, authority);
  const parts = candidateParts(original, rendered);
  const proof = invariant(original, rendered, parts);
  const upgraded = {
    ...original,
    schemaVersion: 2,
    renderedCandidate: rendered,
    renderedCandidateHash: parts.rendered,
    invariantProof: proof,
    invariantProofHash: canonicalJsonSha256(proof),
  };
  const promotion = evidence(
    base, String(original.operationHash), rendered.candidateSha256);
  return {
    proof: { candidate: upgraded, promotionEvidence: promotion },
    hashes: {
      ...parts,
      invariant: upgraded.invariantProofHash,
      candidate: canonicalJsonSha256(upgraded),
      promotion: canonicalJsonSha256(promotion),
      fragmentMedia: base.hashes.fragmentMedia,
      compositeMedia: base.hashes.compositeMedia,
      renderedMedia: rendered.candidateSha256,
    },
  };
}
