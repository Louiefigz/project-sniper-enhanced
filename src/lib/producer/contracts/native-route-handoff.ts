import type { VisualPlanBinding } from "@/lib/server/visual-plan-binding";
import { readFileSync, realpathSync } from "node:fs";
import { canonicalJson, fileSha256 } from "@/lib/server/auto-edit-hash";

const SHA256 = /^[a-f0-9]{64}$/;

export type AutoEditCreativeRoute = "ordinary" | "native-short" | "native-long";

export interface NativeRouteHandoffPointer {
  schemaVersion: 1;
  route: "native-short" | "native-long";
  status: "awaiting-native-author";
  path: string;
  sha256: string;
  requestPath: string;
  requestSha256: string;
  requestDirectory: string;
  projectDirectory?: string;
  visualPlan: VisualPlanBinding;
}

function absolute(value: unknown): value is string {
  return typeof value === "string" && value.startsWith("/");
}

/** Validate the bounded journal pointer without trusting author-authored files. */
export function validNativeRouteHandoffPointer(
  value: unknown,
): value is NativeRouteHandoffPointer {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Partial<NativeRouteHandoffPointer>;
  const binding = row.visualPlan;
  return row.schemaVersion === 1
    && (row.route === "native-short" || row.route === "native-long")
    && row.status === "awaiting-native-author"
    && absolute(row.path) && SHA256.test(row.sha256 ?? "")
    && absolute(row.requestPath) && SHA256.test(row.requestSha256 ?? "")
    && absolute(row.requestDirectory)
    && (row.projectDirectory === undefined || absolute(row.projectDirectory))
    && binding?.schemaVersion === 1 && absolute(binding.path)
    && [binding.byteHash, binding.visualPlanSha256,
      binding.pictureInputSha256, binding.catalogPinSha256,
      binding.upstreamAuthoritySha256].every((hash) => SHA256.test(hash ?? ""));
}

/** Recheck the immutable handoff, request, and visual plan before waiting/reuse. */
export function assertNativeRouteHandoffCurrent(
  pointer: NativeRouteHandoffPointer,
): NativeRouteHandoffPointer {
  if (!validNativeRouteHandoffPointer(pointer)
      || realpathSync(pointer.path) !== pointer.path
      || fileSha256(pointer.path) !== pointer.sha256
      || realpathSync(pointer.requestPath) !== pointer.requestPath
      || fileSha256(pointer.requestPath) !== pointer.requestSha256
      || realpathSync(pointer.visualPlan.path) !== pointer.visualPlan.path
      || fileSha256(pointer.visualPlan.path) !== pointer.visualPlan.byteHash) {
    throw new Error("Native route handoff authority changed before reuse");
  }
  const value = JSON.parse(readFileSync(pointer.path, "utf8")) as {
    status?: unknown; route?: unknown; request?: unknown; visualPlan?: unknown;
  };
  const request = { directory: pointer.requestDirectory,
    path: pointer.requestPath, sha256: pointer.requestSha256 };
  if (value.status !== "awaiting-native-author" || value.route !== pointer.route
      || canonicalJson(value.request) !== canonicalJson(request)
      || canonicalJson(value.visualPlan) !== canonicalJson(pointer.visualPlan)) {
    throw new Error("Native route handoff content differs from its journal pointer");
  }
  return pointer;
}
