import { lstatSync, readdirSync, rmSync, type BigIntStats } from "node:fs";
import path from "node:path";
import type { ProducerAuthorityPaths } from "./producer-authority-files";

// A hard-link publisher's temporary name: `.<published name>.<uuid>.tmp` for immutable records
// (`publishImmutableAuthorityJsonSync`), or `.<sha256>.<uuid>.tmp` for content-addressed objects and media,
// whose published name is `<sha256>.<extension>` (`content-addressed-json.ts`, `content-addressed-file.ts`).
const LEFTOVER = /^\.(.+)\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.tmp$/u;

/** One sweep's result: temporary names removed, and temporary names left in place. */
export interface PublicationRepair {
  removed: string[];
  kept: string[];
}

function statOf(filePath: string): BigIntStats | undefined {
  return lstatSync(filePath, { bigint: true, throwIfNoEntry: false });
}

/** The published names in `names` that a temporary name with this stem can belong to. */
function publishedNames(stem: string, names: Set<string>): string[] {
  if (names.has(stem)) return [stem];
  return [...names].filter((name) => name.startsWith(`${stem}.`) && !name.startsWith("."));
}

/** The same file under both names: same device and inode, so that file has at least two links. */
function sameFile(temporary: BigIntStats, published: BigIntStats | undefined): boolean {
  return published !== undefined && temporary.isFile() && published.isFile()
    && temporary.dev === published.dev && temporary.ino === published.ino
    && published.nlink >= BigInt(2);
}

function repairName(directory: string, name: string, names: Set<string>, repair: PublicationRepair): void {
  const stem = LEFTOVER.exec(name)?.[1];
  const temporary = path.join(directory, name);
  const stat = stem === undefined ? undefined : statOf(temporary);
  if (stem === undefined || stat === undefined) return;
  const owner = publishedNames(stem, names)
    .find((published) => sameFile(stat, statOf(path.join(directory, published))));
  if (owner === undefined) {
    repair.kept.push(temporary);
    return;
  }
  rmSync(temporary, { force: true });
  repair.removed.push(temporary);
}

/**
 * Remove the stray names that hard-link publication leaves behind (M-061c, X110). A publisher links its
 * temporary file to the published name, then removes the temporary name; a crash in between leaves both
 * names on one file. That is a lasting second link, which every authority reader refuses, so on an advance
 * or GENESIS it stops head resolution for good. For each temporary name in the store's publication folders
 * (advances, idempotency records, every object folder), the sweep removes it **only** when it is the same
 * file as its published name (same device and inode, at least two links): the published name keeps exactly
 * those bytes, and the removal only brings its link count back down. Every other temporary name is left and
 * reported in `kept`: a publisher that has not linked yet still needs it, and a stale one is inert. A
 * published record with a second link that is not its own temporary name is not changed here, and every
 * authority reader keeps refusing it by name.
 *
 * Safe beside a live publisher: temporary names are unique (a uuid) and never renamed, so the name the sweep
 * inspected is the name it removes; a publisher removes its own temporary name with `force`, so an earlier
 * removal by the sweep costs it nothing; and removing the same-inode name only ends that publisher's
 * two-link window early. Called where the store opens (`initializeProducerAuthoritySync`) and where it
 * recovers (`unresolvedProducerIntentsSync`, the first step of every commit and of every reconcile).
 */
export function repairPublicationLeftoversSync(paths: ProducerAuthorityPaths): PublicationRepair {
  const repair: PublicationRepair = { removed: [], kept: [] };
  for (const directory of [paths.advances, paths.idempotency, ...Object.values(paths.objects)]) {
    const names = new Set(readdirSync(directory));
    for (const name of names) repairName(directory, name, names, repair);
  }
  return repair;
}
