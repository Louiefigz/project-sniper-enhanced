/** Finite original V2 body metadata only. The actual stopped reader and Python replay own execution/proof admission. */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseSourceColorBodyMediaResult, type BodyMediaCompletionV2 } from "@/lib/producer/contracts/guided-body-result-v2";
import { assertBodyActivationInput } from "@/lib/producer/contracts/guided-body-activation-v1";
import { assertBodyClaimSourceColorMetadata, bodyAdmissionInputVersion } from "./guided-body-lineage";
import { assertBodyInputReferences, observeGuidedBodyMediaInput } from "./guided-body-input";
import { assertOpeningFailureAbsent } from "./guided-opening-process-activation";
import { fileIdentity, directoryIdentity } from "./guided-source-color-cleanup-attempt-hold";
import { snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import { ownedProcessLedgerPath } from "./guided-opening-process-ledger";
import type { readBodyPhase } from "./guided-body-phase";

function same(actual: unknown, expected: unknown): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error("Body source result original metadata or bytes changed");
}

/** Not exported as a result capability. Only the actual result reader privately retains an instance. */
export class BodySourceColorResultHold {
  readonly #files = new Map<string, bigint[]>();
  readonly #parents = new Map<string, bigint[]>();
  readonly #returns: Array<{ value: unknown; fixed: unknown }> = [];
  readonly #phase;
  readonly #fixed;
  readonly #opening;
  constructor(phase: ReturnType<typeof readBodyPhase>) {
    this.#phase = phase; this.#fixed = snapshotSourceColorMetadata(phase);
    const { held } = phase, input = held.invocation.input, a = held.activation;
    if (bodyAdmissionInputVersion(held.admission) !== 2 || input.schemaVersion !== 2) throw new Error("Body source result requires its actual source2 admission");
    const files = [a.inputPath, held.activationPath, path.join(a.outputRoot, "body-result.json"),
      path.join(path.dirname(held.activationPath), `body-process-${phase.factHash}.json`),
      phase.fact.references.intent.path, phase.fact.references.outcome.path,
      ownedProcessLedgerPath(path.dirname(held.activationPath), "media"),
      ...Object.values(input.references).map(ref => ref.path), input.sourceColorReplay.input.path, input.sourceColorReplay.reservationArchive.path];
    files.forEach(file => this.capture(file));
    const observed = observeGuidedBodyMediaInput(a.inputPath, a.inputSha256);
    same(observed, held.invocation); assertBodyInputReferences(held.admission, observed.input);
    assertBodyActivationInput(a, observed.input, { path: a.inputPath, sha256: a.inputSha256 });
    const activation = readCutPreviewObject(held.activationPath);
    if (activation.sha256 !== held.activationSha256) throw new Error("Body source activation raw reference changed");
    same(activation.value, a);
    const opening = readCutPreviewObject(input.references.openingResult.path);
    if (opening.sha256 !== input.references.openingResult.sha256 || opening.value.schemaVersion !== 2) throw new Error("Body source original opening result differs");
    this.#opening = snapshotSourceColorMetadata(opening.value.sourceColorEvidence); this.metadata();
  }
  private capture(file: string): void {
    const identity = fileIdentity(file), previous = this.#files.get(file);
    if (previous) same(identity, previous);
    this.#files.set(file, identity);
    for (let directory = path.dirname(file);; directory = path.dirname(directory)) {
      const identity = directoryIdentity(directory), previous = this.#parents.get(directory);
      if (previous) same(identity, previous);
      this.#parents.set(directory, identity); if (path.dirname(directory) === directory) break;
    }
  }
  retain<T>(value: T): T {
    this.#returns.push({ value, fixed: snapshotSourceColorMetadata(value) }); return value;
  }
  /** Original metadata/file sweep only; never samples a fresh deadline or replays the old current journal. */
  metadata(): void {
    same(this.#phase, this.#fixed); assertBodyClaimSourceColorMetadata(this.#phase.held.admission);
    for (const [directory, original] of this.#parents) same(directoryIdentity(directory), original);
    for (const [file, original] of this.#files) same(fileIdentity(file), original);
    const root = this.#phase.held.activation.outputRoot;
    assertOpeningFailureAbsent(path.join(root, "body-failed.json"));
    assertOpeningFailureAbsent(path.join(path.dirname(root), "body-command-failed.json"));
    for (const [directory, original] of this.#parents) same(directoryIdentity(directory), original);
    same(this.#phase, this.#fixed);
    for (const row of this.#returns) same(row.value, row.fixed);
  }
  /** Complex existing AV fields are not re-qualified here; exact original replay/receipt domains are joined. */
  receipt(record: ReturnType<typeof readCutPreviewObject>, completion: BodyMediaCompletionV2): void {
    const row = parseSourceColorBodyMediaResult(record.value), { held } = this.#phase, input = held.invocation.input, a = held.activation;
    if (input.schemaVersion !== 2 || row.executionId !== a.executionId || row.inputPath !== a.inputPath
        || row.inputSha256 !== a.inputSha256 || row.executionActivationPath !== held.activationPath
        || row.executionActivationSha256 !== held.activationSha256 || row.profile !== input.profile) {
      throw new Error("Body source result replaced its actual original invocation");
    }
    same(row.references, input.references); same(row.sourceColorReplay, input.sourceColorReplay);
    same(completion.sourceColorReplay, row.sourceColorReplay); same(completion.sourceColorReadback, row.sourceColorReadback);
    same(row.sourceColorReadback.sourceColorEvidence, this.#opening); this.metadata();
  }
}
