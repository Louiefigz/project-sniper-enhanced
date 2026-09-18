import path from "node:path";
import {
  observeCurrentRenderGraphAuthoritySync,
  type CurrentRenderGraphAuthority,
} from "./current-render-graph-authority";
import {
  activateOrResolve,
  candidateArgs,
  runCandidateCommand,
  verifiedGraphHash,
  type CandidateCommandResult,
} from "./current-render-graph-candidate-command";
import {
  observeStagedRenderGraphAuthoritySync,
} from "./staged-render-graph-authority";

export interface ExactRenderGraphActivationInput {
  candidatePath: string;
  producerDir: string;
  candidateSha256: string;
  graphHash: string;
}

export function approvedRenderGraphReady(
  producerDir: string,
  planPath: string,
  manifestPath: string,
  expectedSha256: string,
): boolean {
  try {
    runCandidateCommand([
      "active",
      "--producer-dir", producerDir,
      "--final", path.join(producerDir, "final.mp4"),
      "--expected-sha256", expectedSha256,
      "--plan", planPath,
      "--manifest", manifestPath,
      "--base", path.join(producerDir, "base_final.mp4"),
    ]);
    return true;
  } catch {
    return false;
  }
}

/** Verify staged bytes and exact ACTIVE parent before final.mp4 is replaced. */
export function verifyExactRenderGraphCandidateSync(
  input: ExactRenderGraphActivationInput,
): void {
  const staged = observeStagedRenderGraphAuthoritySync({
    producerDir: input.producerDir,
    candidatePath: input.candidatePath,
    expectedCandidateHash: input.candidateSha256,
  });
  let verified: CandidateCommandResult;
  try {
    verified = runCandidateCommand(candidateArgs(
      "verify", input.candidatePath,
      input.producerDir, input.candidateSha256));
  } catch (trigger) {
    try {
      verified = runCandidateCommand(candidateArgs(
        "candidate-active", input.candidatePath,
        input.producerDir, input.candidateSha256));
    } catch {
      throw trigger;
    }
  }
  const graphHash = verifiedGraphHash(verified);
  if (graphHash !== input.graphHash || graphHash !== staged.graphHash) {
    throw new Error("activation candidate graph identity changed");
  }
}

/** CAS one already-verified candidate after its bytes replace final.mp4. */
export function activateExactRenderGraphCandidateSync(
  input: ExactRenderGraphActivationInput,
): CurrentRenderGraphAuthority {
  activateOrResolve({
    candidate: input.candidatePath,
    producerDir: input.producerDir,
    expectedSha256: input.candidateSha256,
    command: runCandidateCommand,
  });
  return observeCurrentRenderGraphAuthoritySync({
    producerDir: input.producerDir,
    expectedGraphHash: input.graphHash,
    expectedFinalHash: input.candidateSha256,
  });
}

/** Restore the staged candidate's exact prior ACTIVE generation. */
export function rollbackExactRenderGraphCandidateSync(
  input: ExactRenderGraphActivationInput,
): void {
  runCandidateCommand(candidateArgs(
    "rollback",
    input.candidatePath,
    input.producerDir,
    input.candidateSha256,
  ));
}
