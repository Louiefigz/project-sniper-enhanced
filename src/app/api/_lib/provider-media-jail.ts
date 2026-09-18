import fs from "node:fs";
import path from "node:path";
import { SCRIPTS_DIR } from "./spawn-python";

/**
 * OS-enforced media boundary for tool-less provider reviews.
 *
 * The provider CLI (already admitted by subscription-invocation.ts) is started
 * through macOS `sandbox-exec` with `scripts/producer/headless/provider_media_deny.sb`:
 * neither the CLI nor anything it starts can read the project folder outside the
 * review folder, or open a file named as video/audio, a Sniper media snapshot or
 * a snapshot staging file anywhere. Matching is by name; the tool-less review is
 * the primary boundary. It is used only for invocations that run without tools; a CLI
 * that sandboxes its own tool commands cannot run inside another Seatbelt
 * profile (macOS refuses nested `sandbox_apply`).
 */
export const PROVIDER_MEDIA_PROFILE = path.join(SCRIPTS_DIR, "producer", "headless", "provider_media_deny.sb");
export const SANDBOX_EXEC = "/usr/bin/sandbox-exec";
export const PROVIDER_MEDIA_POLICY = "sniper-provider-media-deny-v2";

export interface JailedCommand {
  bin: string;
  args: string[];
}

/** The project folder to hide and the review folder inside it that stays readable. */
export interface ProviderJailScope {
  project: string;
  review: string;
}

function scopedDirectory(value: string, label: string): string {
  if (!path.isAbsolute(value) || /[\0\r\n]/u.test(value)) throw new Error(`Provider jail ${label} must be an absolute path`);
  return fs.realpathSync(value);
}

/**
 * Wrap an admitted provider command; refuse rather than run unconfined. With a scope the
 * project folder is hidden except its review folder; without one (a text-only call such as
 * Segmenter or Clipper, which has no project) only the media-name rules apply.
 */
export function providerMediaJail(bin: string, args: readonly string[], scope?: ProviderJailScope): JailedCommand {
  if (process.platform !== "darwin") throw new Error("The provider media boundary requires macOS");
  if (!path.isAbsolute(bin) || !fs.statSync(bin).isFile()) throw new Error("Jailed provider CLI must be an absolute file");
  if (!fs.statSync(SANDBOX_EXEC).isFile() || !fs.statSync(PROVIDER_MEDIA_PROFILE).isFile()) {
    throw new Error("The provider media boundary is unavailable on this Mac");
  }
  if (!scope) return { bin: SANDBOX_EXEC, args: ["-f", PROVIDER_MEDIA_PROFILE, bin, ...args] };
  const project = scopedDirectory(scope.project, "project"), review = scopedDirectory(scope.review, "review folder");
  if (!review.startsWith(`${project}${path.sep}`)) throw new Error("Provider jail review folder must be inside the project");
  return { bin: SANDBOX_EXEC,
    args: ["-D", `PROJECT=${project}`, "-D", `REVIEW=${review}`, "-f", PROVIDER_MEDIA_PROFILE, bin, ...args] };
}
