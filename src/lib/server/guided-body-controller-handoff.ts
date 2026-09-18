/** Same-call code-metadata transfer only; never reconstructed launch, lease or native authority. */
import { isDeepStrictEqual } from "node:util";
import { assertBodyControllerSourcesMetadata, type HeldBodyControllerSources } from "./guided-body-controller-sources";
import { snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import type { writeGuidedBodyMediaInput } from "./guided-body-input";
import type { readGuidedBodyActivation } from "./guided-body-activation";

type Invocation = ReturnType<typeof writeGuidedBodyMediaInput>;
type Activation = ReturnType<typeof readGuidedBodyActivation>;
interface Original { fixed: unknown; sources?: HeldBodyControllerSources }
const invocations = new WeakMap<Invocation, Original>();
const activations = new WeakMap<Activation, Original>();
const transferred = new WeakSet<Invocation>();

/** Pure original returned values precede all callbacks. Even a legacy result cannot be copied into this handoff. */
export function retainBodyControllerInvocation(value: Invocation, sources?: HeldBodyControllerSources): void {
  if (invocations.has(value)) throw new Error("Body controller invocation is already retained");
  const original = { fixed: snapshotSourceColorMetadata(value), sources };
  if ((value.input.schemaVersion === 2) !== Boolean(sources)) throw new Error("Body controller invocation source version differs");
  if (sources) assertBodyControllerSourcesMetadata(sources);
  same(value, original); invocations.set(value, original);
}

/** No current-journal read, raw rehash or caller callback; the original controller deadline still applies. */
function same(value: object, original: Original): void {
  if (!isDeepStrictEqual(value, original.fixed)) throw new Error("Body controller original handoff values changed");
  if (original.sources) assertBodyControllerSourcesMetadata(original.sources);
  if (!isDeepStrictEqual(value, original.fixed)) throw new Error("Body controller original handoff values changed during metadata read");
}

/** Require the actual writer return, not mutually consistent replacement input/record DTOs. */
export function assertBodyControllerInvocation(value: Invocation): void {
  const original = invocations.get(value);
  if (!original) throw new Error("Body controller handoff requires its actual original invocation");
  same(value, original);
}

/** Sample only the saved original parent and shorten its retained source deadline before the final metadata sweep. */
function check<T extends object>(value: T, records: WeakMap<T, Original>): void {
  const original = records.get(value);
  if (!original) throw new Error("Body controller check requires its actual original live handoff");
  same(value, original); original.sources?.check(); same(value, original);
}

export function checkBodyControllerInvocation(value: Invocation): void {
  check(value, invocations);
}

export function checkBodyControllerActivation(value: Activation): void {
  check(value, activations);
}

/** Transfer to the actual post-CAS activation without reentering the stale pre-CAS admission journal guard. */
export function retainBodyControllerActivation(invocation: Invocation, value: Activation): void {
  const fixed = snapshotSourceColorMetadata(value), original = invocations.get(invocation);
  if (!original || activations.has(value) || transferred.has(invocation)) throw new Error("Body controller activation requires an unused actual handoff");
  transferred.add(invocation);
  assertBodyControllerInvocation(invocation);
  if (value.activation.inputPath !== invocation.record.path || value.activation.inputSha256 !== invocation.record.sha256
      || value.invocation.record.sha256 !== invocation.record.sha256 || !isDeepStrictEqual(value.invocation.input, invocation.input)
      || value.admission.claimHash !== invocation.input.references.admissionClaim.sha256
      || (original.sources && value.controlJob.ctx.pipeline?.digest !== original.sources.pipelineDigest)) {
    throw new Error("Body controller activation differs from its original writer or pipeline");
  }
  const held = { fixed, sources: original.sources }; same(value, held);
  activations.set(value, held);
}

/** Historical status/cleanup reads never call this: only the original live return carries code metadata. */
export function assertBodyControllerActivationMetadata(value: Activation): void {
  const original = activations.get(value);
  if (!original) throw new Error("Body controller activation requires its actual original live return");
  same(value, original);
}
