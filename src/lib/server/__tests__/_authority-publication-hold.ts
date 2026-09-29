import fs from "node:fs";
import path from "node:path";
import { authorityKey } from "../producer-authority-files";
import { advancePath, publishProducerAdvanceSync } from "../producer-revision-head";
import { materializeProducerCommitSync } from "../producer-revision-materialize";
import {
  recoverProducerCommitSync,
  type ProducerCommitOutcome,
} from "../producer-revision-recovery";
import {
  bootstrapRevisionFixture,
  revisionCommitInput,
} from "./_producer-revision-fixture";

// A half-published authority file (X38(c), M-061a): a publisher links its temporary file to the
// destination, then removes the temporary name. In between, the destination has two links. These
// helpers hold that state and finish it only when the reader waits, so a reader that does not wait
// fails every time and one that waits succeeds every time. No timing is involved.

/** The held second links, the reader's publication waits, and whether the publication never completes. */
export interface HeldPublication {
  links: string[];
  waits: number;
  stuck: boolean;
}

export type RevisionFixture = ReturnType<typeof bootstrapRevisionFixture>;

/** Hold `destination` half-published: add the second, temporary link a publisher has before its unlink. */
export function holdPublication(held: HeldPublication, destination: string): void {
  const link = path.join(path.dirname(destination), `.${path.basename(destination)}.held.tmp`);
  fs.linkSync(destination, link);
  held.links.push(link);
}

/**
 * Run `action`. Each wait the authority reader makes between attempts (its `Atomics.wait` backoff) is
 * counted and first finishes the held publications by removing their temporary links, unless they are stuck.
 */
export function whilePublicationHeld<T>(held: HeldPublication, action: () => T): T {
  const wait = Atomics.wait;
  Atomics.wait = ((...args: unknown[]) => {
    held.waits += 1;
    if (!held.stuck) held.links.splice(0).forEach((link) => fs.rmSync(link));
    return Reflect.apply(wait, Atomics, args);
  }) as typeof Atomics.wait;
  try {
    return action();
  } finally {
    Atomics.wait = wait;
  }
}

/** Materialize request `variant` (objects, idempotency record, intent); `advance()` publishes its parent advance. */
export function stageRevision(fixture: RevisionFixture, variant: string) {
  const input = revisionCommitInput(fixture.producer, fixture.genesis, variant);
  const { paths, record } = materializeProducerCommitSync(input);
  const { expectedParentRevisionHash, childRevisionHash, idempotencyKey, requestDigest } = record;
  const advance = (): string => {
    publishProducerAdvanceSync(paths, {
      schemaVersion: 1, expectedParentRevisionHash, childRevisionHash, idempotencyKey, requestDigest,
    });
    return advancePath(paths, expectedParentRevisionHash);
  };
  const idempotency = path.join(paths.idempotency, `${authorityKey(idempotencyKey)}.json`);
  return { input, paths, record, advance, idempotency };
}

/** A recovery whose parent advance is published and held just before `matchingAdvance` reads it. */
export function heldRecovery(
  fixture: RevisionFixture,
  held: HeldPublication,
): () => ProducerCommitOutcome {
  const { advance, record } = stageRevision(fixture, "b");
  return () => recoverProducerCommitSync(fixture.producer, record.idempotencyKey, {
    after: (boundary) => {
      if (boundary === "after-local-commit-intent") holdPublication(held, advance());
    },
  });
}
