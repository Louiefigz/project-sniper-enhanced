/** Explicit opening evidence dispatch for body consumers; these reads never authorize body execution. */
import { assertOpeningSelectionMetadata, openingSelectionVersion, type readSelectedOpeningMedia } from "./guided-opening-selection";
import { readHeldOpeningResult, type HeldOpeningResult } from "./guided-opening-result";
import { readHeldSourceColorOpeningResult, assertSourceColorOpeningResultMetadata,
  type HeldSourceColorOpeningResult } from "./guided-source-color-opening-result";
import { verifyCleanedOpeningMediaUnderLease, type ReadbackInput } from "./guided-opening-readback";
import { verifyCleanedSourceColorOpeningMediaUnderLease, assertSourceColorOpeningReadbackOwner,
  assertSourceColorOpeningReadbackMetadata } from "./guided-source-color-readback";
import { assertSourceColorOpeningApprovalMetadata } from "./guided-source-color-approval-read";
import { holdBodySourceColorReplayReferences } from "./guided-body-source-color-replay";

type Selection = ReturnType<typeof readSelectedOpeningMedia>;
export type BodyOpeningResult = HeldOpeningResult | HeldSourceColorOpeningResult;
export type BodyOpeningVerification = Awaited<ReturnType<typeof verifyCleanedOpeningMediaUnderLease>>
  | Awaited<ReturnType<typeof verifyCleanedSourceColorOpeningMediaUnderLease>>;
export const bodyOpeningVersionServices = { sourceVerify: verifyCleanedSourceColorOpeningMediaUnderLease };

/** Project once from the actual source2 parents; legacy inputs never acquire source replay metadata. */
export function holdBodyOpeningReplay(input: { selected: Selection; result: BodyOpeningResult; guard: () => void }) {
  if (openingSelectionVersion(input.selected) === 1) return null;
  assertSourceColorOpeningResultMetadata(input.result as HeldSourceColorOpeningResult, input.selected.held);
  return holdBodySourceColorReplayReferences({ ...input, result: input.result as HeldSourceColorOpeningResult });
}

/** The exact parsed selection controls the version; unsupported versions never borrow a legacy reader. */
export function readBodyOpeningResult(input: { selected: Selection; guard: () => void }, legacy = readHeldOpeningResult): BodyOpeningResult {
  const { selected, guard } = input;
  if (openingSelectionVersion(selected) === 2) {
    assertOpeningSelectionMetadata(selected);
    const result = readHeldSourceColorOpeningResult({ held: selected.held, guard });
    assertOpeningSelectionMetadata(selected); assertSourceColorOpeningResultMetadata(result, selected.held); return result;
  }
  if (selected.fact.schemaVersion !== 1) throw new Error("Body opening selection version is unsupported");
  return legacy(selected.held);
}

/** Capture before later callbacks: changing a discriminator cannot discard the original source2 obligations. */
export function retainBodyOpeningMetadata(input: { selected: Selection; result: BodyOpeningResult; approval: object }): () => void {
  const { selected, result, approval } = input;
  if (openingSelectionVersion(selected) !== 2) {
    if (selected.fact.schemaVersion !== 1 || result.completion.schemaVersion !== 1) throw new Error("Body opening evidence versions differ");
    return () => {}; // Legacy consumers retain their existing independent record checks.
  }
  const check = () => {
    assertOpeningSelectionMetadata(selected);
    assertSourceColorOpeningResultMetadata(result as HeldSourceColorOpeningResult, selected.held);
    assertSourceColorOpeningApprovalMetadata(approval);
  };
  check(); return check;
}

/** The schema2 verifier must return its genuine capability under the same caller-owned lease/remainder. */
export async function verifyBodyOpeningInput(input: { request: ReadbackInput; selected: Selection },
  legacy = verifyCleanedOpeningMediaUnderLease): Promise<BodyOpeningVerification> {
  if (openingSelectionVersion(input.selected) === 2) {
    const owner = bodyVerifierOwner(input);
    const verified = await bodyOpeningVersionServices.sourceVerify(owner.request);
    owner.metadata(); assertSourceColorOpeningReadbackOwner(verified, owner.original); owner.metadata(); return verified;
  }
  if (input.selected.fact.schemaVersion !== 1) throw new Error("Body opening verification version is unsupported");
  return legacy(input.request);
}

/** Capture the original request before the service callback; validating against a modified request would rebaseline ownership. */
function bodyVerifierOwner(input: { request: ReadbackInput; selected: Selection }) {
  const { request, selected } = input, original = { ...request }, release = request.lease.release;
  const metadata = () => {
    if (input.request !== request || input.selected !== selected || request.dir !== original.dir
        || request.lease !== original.lease || request.remainingMs !== original.remainingMs
        || request.expectedCleanupHash !== original.expectedCleanupHash || original.lease.release !== release) {
      throw new Error("Body opening verifier original request owner changed");
    }
    assertOpeningSelectionMetadata(selected);
  };
  metadata(); return { request, original, metadata };
}

/** Finite retained proof only; later caller checks must not reenter the verifier or renew its allowance. */
export function retainBodyOpeningVerification(sourceColor: boolean, verified: BodyOpeningVerification): () => void {
  if (!sourceColor) return () => {}; // Legacy reads still recheck their existing actual output/receipt records.
  const check = () => { assertSourceColorOpeningReadbackMetadata(verified as Awaited<ReturnType<typeof verifyCleanedSourceColorOpeningMediaUnderLease>>); };
  check(); return check;
}
