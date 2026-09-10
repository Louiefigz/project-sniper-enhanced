/** New-only attempt-local preparation publication. It grants no native, journal or recovery authority. */
import fs from "node:fs";
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { uuid } from "@/lib/producer/contracts/validation";
import { openingAbsolutePath } from "@/lib/producer/contracts/guided-opening-media-v1";
import { parsePreparedSourceColorCleanupFact, type PreparedSourceColorCleanupFact } from "@/lib/producer/contracts/guided-source-color-cleanup-facts";
import { assertCutPreviewDirectory, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { createOpeningRecord } from "./guided-opening-process-activation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { directoryIdentity, fileIdentity } from "./guided-source-color-cleanup-attempt-hold";
import type { HeldOpeningClaim } from "./guided-opening-process";

export interface SourceColorCleanupPreparationRef { path: string; sha256: string; sizeBytes: number }

function absent(file: string): void {
  try { fs.lstatSync(file); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return; throw error; }
  throw new Error("Source color cleanup attempt already has a preparation entry; retain it without native replay");
}

/** Entry-held ancestry and absence switch exactly once to the actual newly published file identity. */
export class CleanupPreparationPublication {
  readonly file;
  private readonly parents = new Map<string, bigint[]>();
  private readonly identity;
  private published: { reference: Readonly<SourceColorCleanupPreparationRef>; identity: bigint[] } | undefined;
  constructor(input: { held: HeldOpeningClaim; attemptId: string }) {
    const attemptId = uuid(input.attemptId, "cleanup preparation attempt");
    if (attemptId[14] !== "4") throw new Error("Cleanup preparation requires its exact UUIDv4 attempt");
    this.file = path.join(path.dirname(openingAbsolutePath(input.held.claimPath)), "cleanup-attempts", attemptId, "prepared.json");
    this.identity = { claimHash: input.held.claimHash, executionId: input.held.claim.executionId,
      beforeJournalHash: input.held.sha256, cleanupAttemptId: attemptId };
    assertCutPreviewDirectory(path.dirname(this.file));
    for (let directory = path.dirname(this.file);;) {
      this.parents.set(directory, directoryIdentity(directory));
      const parent = path.dirname(directory); if (parent === directory) break;
      directory = parent;
    }
    this.assertMetadata();
  }
  assertMetadata = (): void => {
    for (const [directory, identity] of this.parents) {
      if (!isDeepStrictEqual(directoryIdentity(directory), identity)) throw new Error("Cleanup preparation original parent identity changed");
    }
    if (!this.published) { absent(this.file); return; }
    const original = this.published;
    if (!isDeepStrictEqual(fileIdentity(this.file), original.identity)) throw new Error("Cleanup preparation original published file identity changed");
    const row = readCutPreviewObject(this.file);
    if (!isDeepStrictEqual(fileIdentity(this.file), original.identity) || row.sha256 !== original.reference.sha256
        || row.sizeBytes !== original.reference.sizeBytes || canonicalJsonSha256(row.value) !== row.sha256) {
      throw new Error("Cleanup preparation original published bytes or identity changed");
    }
  };
  /** Caller first proves actual completed output/readback and its original allowance; this is only durable publication. */
  publish(fact: PreparedSourceColorCleanupFact): Readonly<SourceColorCleanupPreparationRef> {
    this.assertMetadata();
    if (this.published) throw new Error("Cleanup preparation cannot be published twice");
    const parsed = parsePreparedSourceColorCleanupFact(fact);
    for (const key of ["claimHash", "executionId", "beforeJournalHash", "cleanupAttemptId"] as const) {
      if (parsed[key] !== this.identity[key]) throw new Error("Cleanup preparation differs from its original claim/attempt");
    }
    const record = createOpeningRecord(this.file, { ...parsed }), identity = fileIdentity(this.file), raw = readCutPreviewObject(this.file);
    if (raw.sha256 !== record.sha256) throw new Error("Cleanup preparation publication differs from its original fact");
    const reference = Object.freeze({ path: this.file, sha256: raw.sha256, sizeBytes: raw.sizeBytes });
    this.published = { reference, identity }; this.assertMetadata(); return reference;
  }
}
