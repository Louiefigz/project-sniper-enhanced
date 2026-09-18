import fs from "node:fs";
import path from "node:path";
import { SCRIPTS_DIR } from "./spawn-python";

/**
 * OS-enforced media boundary for tool-less provider reviews.
 *
 * The provider CLI (already admitted by subscription-invocation.ts) is started
 * through macOS `sandbox-exec` with `scripts/producer/headless/provider_media_deny.sb`:
 * neither the CLI nor anything it starts can open a video/audio file or a Sniper
 * media snapshot. It is used only for invocations that run without tools; a CLI
 * that sandboxes its own tool commands cannot run inside another Seatbelt
 * profile (macOS refuses nested `sandbox_apply`).
 */
export const PROVIDER_MEDIA_PROFILE = path.join(SCRIPTS_DIR, "producer", "headless", "provider_media_deny.sb");
export const SANDBOX_EXEC = "/usr/bin/sandbox-exec";
export const PROVIDER_MEDIA_POLICY = "sniper-provider-media-deny-v1";

export interface JailedCommand {
  bin: string;
  args: string[];
}

/** Wrap an admitted provider command; refuse rather than run unconfined. */
export function providerMediaJail(bin: string, args: readonly string[]): JailedCommand {
  if (process.platform !== "darwin") throw new Error("The provider media boundary requires macOS");
  if (!path.isAbsolute(bin) || !fs.statSync(bin).isFile()) throw new Error("Jailed provider CLI must be an absolute file");
  if (!fs.statSync(SANDBOX_EXEC).isFile() || !fs.statSync(PROVIDER_MEDIA_PROFILE).isFile()) {
    throw new Error("The provider media boundary is unavailable on this Mac");
  }
  return { bin: SANDBOX_EXEC, args: ["-f", PROVIDER_MEDIA_PROFILE, bin, ...args] };
}
