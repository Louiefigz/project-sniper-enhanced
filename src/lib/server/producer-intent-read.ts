import { lstatSync } from "node:fs";
import {
  parseCommitIntentV1,
  type CommitIntentV1,
} from "@/lib/producer/contracts/commit-intent";
import { readAuthorityJsonSync } from "./producer-authority-files";

const INTENT_REPLACED_WAIT = new Int32Array(new SharedArrayBuffer(4));
const MAX_WAITS = 24;

/** Whether a failed read met an atomic replacement: an identity change, and one link at the path now. */
function replacedDuringRead(filePath: string, error: unknown): boolean {
  const message = error instanceof Error ? error.message : "";
  return message.includes("authority record changed while")
    && lstatSync(filePath, { throwIfNoEntry: false })?.nlink === 1;
}

function readIntentAfter(filePath: string, waits: number): CommitIntentV1 {
  try {
    return parseCommitIntentV1(readAuthorityJsonSync(filePath));
  } catch (error) {
    if (waits === MAX_WAITS || !replacedDuringRead(filePath, error)) throw error;
  }
  Atomics.wait(INTENT_REPLACED_WAIT, 0, 0, 2);
  return readIntentAfter(filePath, waits + 1);
}

/**
 * Read one producer commit intent (M-061b, X94). An intent is the one mutable authority record of a
 * commit: `transitionIntent` replaces it by atomic rename, so a second process recovering the same commit
 * can replace it while this one reads it. That read is repeated after a 2 ms wait, at most 24 times.
 * Anything else is refused at once: a malformed intent, a missing file, a second link, and every other
 * authority record (their reader keeps its immediate refusal). An intent still being replaced after the
 * last wait is refused too.
 */
export function readCommitIntentSync(filePath: string): CommitIntentV1 {
  return readIntentAfter(filePath, 0);
}
