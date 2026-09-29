import { lstatSync } from "node:fs";
import {
  parseCommitIntentV1,
  type CommitIntentV1,
} from "@/lib/producer/contracts/commit-intent";
import { readAuthorityJsonSync } from "./producer-authority-files";

const INTENT_REPLACED_WAIT = new Int32Array(new SharedArrayBuffer(4));
const MAX_WAITS = 24;

/**
 * Whether a failed read met an atomic replacement: an identity change, and no second link at the path now.
 * The path's `lstat` can land inside another process's rename and see the outgoing file at 0 links (X106),
 * or the incoming one at 1. A missing file, or a second link, is not a replacement.
 */
function replacedDuringRead(filePath: string, error: unknown): boolean {
  const message = error instanceof Error ? error.message : "";
  if (!message.includes("authority record changed while")) return false;
  const links = lstatSync(filePath, { throwIfNoEntry: false })?.nlink;
  return links !== undefined && links < 2;
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
 * can replace it while this one reads it. Such a read is repeated after a 2 ms wait, at most 24 times; an
 * intent still being replaced after the last wait is refused. Not repeated here: a malformed intent, a
 * missing file, and a second link (the authority reader's own 24 waits apply, then it refuses). A symlink
 * or special file swapped in during a read has no second link, so it is refused one 2 ms wait later, by
 * the reader's regular-file check. Worst case, with the reader's waits composed (a second link that keeps
 * appearing and going): 25 x 25 attempts and 624 waits, about 1.25 s. Every other authority record keeps
 * the reader's immediate refusal of a replacement.
 */
export function readCommitIntentSync(filePath: string): CommitIntentV1 {
  return readIntentAfter(filePath, 0);
}
