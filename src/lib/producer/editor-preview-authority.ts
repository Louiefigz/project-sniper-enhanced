import type { StreamEvent } from "./types";

export type PreviewAuthority = "checking" | "current" | "unapproved" | "stale";

/** A dirty timeline always outranks an older disk approval. */
export function effectivePreviewAuthority(
  dirty: boolean,
  verified: PreviewAuthority,
): PreviewAuthority {
  return dirty ? "stale" : verified;
}

/** Only the QC controller's explicit approval event can make a preview current. */
export function approvedOutputEvent(event: StreamEvent): boolean {
  if (event.event !== "outputs") return false;
  if (event.approved !== true) {
    throw new Error("render stream ended without QC approval; the previous video remains stale");
  }
  return true;
}

export function previewAuthorityMessage(authority: PreviewAuthority): string {
  if (authority === "checking") return "Checking whether this render matches the saved timeline…";
  if (authority === "unapproved") {
    return "This is an inspectable review copy, not the approved delivery. Render and QC the saved timeline before sending it to Palmier.";
  }
  return "Preview out of date — render and QC the saved timeline to see the current video.";
}
