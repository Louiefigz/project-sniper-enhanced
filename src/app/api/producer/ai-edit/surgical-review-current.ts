import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileSha256 } from "@/lib/server/auto-edit-hash";

interface CurrentReviewMarker {
  schemaVersion?: unknown;
  status?: unknown;
  planHash?: unknown;
}

/** A crashed/pending or subsequently changed AI plan may not render as reviewed. */
export function assertSurgicalReviewCurrent(
  planPath: string,
  markerName: string,
): void {
  const destination = path.join(path.dirname(planPath), markerName);
  if (!existsSync(destination)) return;
  let marker: CurrentReviewMarker;
  try {
    marker = JSON.parse(readFileSync(destination, "utf8")) as CurrentReviewMarker;
  } catch {
    throw new Error("surgical edit review marker is unreadable; rerun the requested edit");
  }
  if (marker.schemaVersion !== 1 || marker.status !== "approved"
      || typeof marker.planHash !== "string") {
    throw new Error("surgical edit is still awaiting deterministic validation and independent review");
  }
  if (fileSha256(planPath) !== marker.planHash) {
    throw new Error("the plan changed after its surgical edit review; review the current plan again");
  }
}
