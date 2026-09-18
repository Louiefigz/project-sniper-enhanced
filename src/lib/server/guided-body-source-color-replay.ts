/** Genuine source2 opening evidence projected for a future body worker, never body activation. */
import { isDeepStrictEqual } from "node:util";
import { BODY_SOURCE_COLOR_REPLAY_SCOPE, parseBodySourceColorReplayReferences,
  type BodySourceColorReplayReferencesV2 } from "@/lib/producer/contracts/guided-body-source-color-replay-v2";
import { assertOpeningSelectionMetadata, type readSelectedOpeningMedia } from "./guided-opening-selection";
import { assertOpeningCleanupMetadata } from "./guided-opening-cleanup-store";
import { readHeldSourceColorOpeningResult, assertSourceColorOpeningResultMetadata,
  type HeldSourceColorOpeningResult } from "./guided-source-color-opening-result";
import { holdSourceColorReadInvocation, assertSourceColorReadInvocation } from "./guided-source-color-read-transport";
import { freezeSourceColorValue, snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";

export interface BodySourceColorReplayContext {
  selected: ReturnType<typeof readSelectedOpeningMedia>; result: HeldSourceColorOpeningResult; guard: () => void;
}
export interface HeldBodySourceColorReplayReferences {
  readonly references: BodySourceColorReplayReferencesV2;
  readonly scope: typeof BODY_SOURCE_COLOR_REPLAY_SCOPE;
}
const retained = new WeakMap<HeldBodySourceColorReplayReferences, () => void>();
const active = new WeakSet<BodySourceColorReplayContext>();

function same(actual: unknown, expected: unknown): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error("Body source-color replay original proof binding changed");
}

/** Actual parents are authenticated before any caller guard or new metadata read. */
function originalContext(input: BodySourceColorReplayContext) {
  const { selected, result, guard } = input;
  if (typeof guard !== "function") throw new Error("Body source-color replay requires its original caller guard");
  assertOpeningSelectionMetadata(selected); assertSourceColorOpeningResultMetadata(result, selected.held);
  const cleanup = selected.observed, held = selected.held, cleanupHeld = cleanup.held;
  assertOpeningCleanupMetadata(cleanup);
  same([selected.fact.schemaVersion, selected.fact.mediaResultSha256, selected.receiptSha256, selected.fact.receiptHash, selected.receiptHash],
    [2, result.record.sha256, result.record.sha256, result.completion.receiptHash, result.completion.receiptHash]);
  const metadata = () => {
    if (input.selected !== selected || input.result !== result || input.guard !== guard
        || selected.held !== held || selected.observed !== cleanup || cleanup.held !== cleanupHeld) {
      throw new Error("Body source-color replay original caller identity changed");
    }
    assertOpeningSelectionMetadata(selected); assertSourceColorOpeningResultMetadata(result, held); assertOpeningCleanupMetadata(cleanup);
  };
  metadata(); return { selected, result, guard, cleanup, cleanupHeld, metadata };
}

/** Only the two original raw references escape; all other records stay inside actual metadata capabilities. */
function projection(context: ReturnType<typeof originalContext>, observed: HeldSourceColorOpeningResult): BodySourceColorReplayReferencesV2 {
  const { selected, cleanup } = context, source = observed.process.sourceColor;
  if (!("pending" in cleanup) || !source) throw new Error("Body source-color replay needs actual final source cleanup");
  const claim = cleanup.held.claim;
  return parseBodySourceColorReplayReferences({ schemaVersion: 2, kind: "guided-body-source-color-replay-references",
    scope: BODY_SOURCE_COLOR_REPLAY_SCOPE, opening: { selectionHash: selected.selectionHash, claimHash: cleanup.held.claimHash,
      cleanupHash: cleanup.cleanupHash, executionId: claim.executionId, inputSha256: claim.inputSha256,
      executionInputHash: claim.executionInputHash, mediaResultSha256: observed.record.sha256, receiptHash: observed.completion.receiptHash },
    sourceColorHash: source.sourceColorHash, input: source.input, reservationArchive: cleanup.pending.fact.archive,
    executable: false, bodyApproved: false, deliveryApproved: false });
}

function read(input: BodySourceColorReplayContext): HeldBodySourceColorReplayReferences {
  const context = originalContext(input);
  const check = () => { context.metadata(); context.guard(); context.metadata(); };
  // Selection's historical result and its observed cleanup may have DISTINCT actual held objects.
  const observed = readHeldSourceColorOpeningResult({ held: context.cleanupHeld, guard: check });
  same([observed.process, observed.completion, observed.record], [context.result.process, context.result.completion, context.result.record]);
  const invocation = holdSourceColorReadInvocation({ cleanup: context.cleanup, selected: observed });
  const references = freezeSourceColorValue(projection(context, observed)), fixed = snapshotSourceColorMetadata(references);
  const value = Object.freeze({ references, scope: BODY_SOURCE_COLOR_REPLAY_SCOPE });
  const metadata = () => {
    context.metadata(); assertSourceColorOpeningResultMetadata(observed, context.cleanupHeld);
    assertSourceColorReadInvocation(invocation, context.cleanupHeld); same(value.references, fixed);
  };
  metadata(); check(); metadata(); retained.set(value, metadata); return value;
}

/** No clock, source/tool payload, lease or native authority is created; the caller supplies its unchanged guard. */
export function holdBodySourceColorReplayReferences(input: BodySourceColorReplayContext): HeldBodySourceColorReplayReferences {
  if (!input || typeof input !== "object" || active.has(input)) throw new Error("Body source-color replay input is invalid or reentered");
  active.add(input);
  try { return read(input); } finally { active.delete(input); }
}

/** Finite original metadata only; serialized/copied projections cannot reconstruct this private proof. */
export function assertBodySourceColorReplayMetadata(value: HeldBodySourceColorReplayReferences): void {
  const check = retained.get(value);
  if (!check) throw new Error("Body source-color replay requires its actual original retained proof");
  check();
}
