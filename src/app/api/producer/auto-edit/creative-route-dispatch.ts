import { existsSync, readFileSync, realpathSync } from "node:fs";
import path from "node:path";
import type { AutoEditCreativeRoute, NativeRouteHandoffPointer } from
  "@/lib/producer/contracts/native-route-handoff";
import { atomicCreateJsonSync } from "@/lib/server/atomic-file";
import { canonicalJson, canonicalJsonSha256, fileSha256 } from
  "@/lib/server/auto-edit-hash";
import { runtimeRepositoryRoot } from "@/lib/server/auto-edit-pipeline-authority";
import { prepareNativeLongformRequest } from "@/lib/server/native-longform-request";
import { prepareNativeShortRequest } from "@/lib/server/native-short-request";
import type { AutoEditCtx } from "./stream";
import { ordinaryVisualPlanRequired } from "./stream";
import { currentVisualPlanProjectAuthority } from "./visual-plan-context";
import {
  boundVisualPlanContent, projectVisualPlanBinding,
  visualPlanValidationAuthority, type VisualPlanBinding,
} from "@/lib/server/visual-plan-binding";

const HANDOFF_FILE = "NATIVE-AUTHOR-HANDOFF.json";

interface NativePreparation {
  directory: string;
  requestHash: string;
  projectDirectory?: string;
}

export interface CreativeRouteDispatchDependencies {
  prepareShort: typeof prepareNativeShortRequest;
  prepareLong: typeof prepareNativeLongformRequest;
  repoRoot: typeof runtimeRepositoryRoot;
}

export type CreativeRouteDispatchOutcome =
  | { status: "ordinary"; route: "ordinary" }
  | { status: "awaiting_native_author"; route: "native-short" | "native-long";
    handoff: NativeRouteHandoffPointer };

const DEFAULTS: CreativeRouteDispatchDependencies = {
  prepareShort: prepareNativeShortRequest,
  prepareLong: prepareNativeLongformRequest,
  repoRoot: runtimeRepositoryRoot,
};

export function allocatedCreativeRoute(
  ctx: AutoEditCtx,
  binding: VisualPlanBinding,
): AutoEditCreativeRoute {
  const bound = boundVisualPlanContent(binding, visualPlanValidationAuthority(ctx));
  const value = bound.content as { project?: { mode?: unknown };
    allocation?: { status?: unknown; route?: unknown } };
  const route = value.allocation?.route;
  if (value.allocation?.status !== "allocated"
      || !["ordinary", "native-short", "native-long"].includes(String(route))) {
    throw new Error("VISUAL-PLAN.json lacks one allocated controller route");
  }
  if ((route === "native-short" && value.project?.mode !== "short")
      || (route === "native-long" && value.project?.mode !== "long")) {
    throw new Error("VISUAL-PLAN.json native route conflicts with its project mode");
  }
  return route as AutoEditCreativeRoute;
}

function prepare(
  ctx: AutoEditCtx,
  route: "native-short" | "native-long",
  deps: CreativeRouteDispatchDependencies,
): NativePreparation {
  const repo = deps.repoRoot();
  if (route === "native-long") return deps.prepareLong(ctx.dir, repo);
  return deps.prepareShort({ producerDir: ctx.dir,
    intent: { ...ctx.intent, scope: ctx.scope }, repo });
}

function handoffValue(
  ctx: AutoEditCtx,
  route: "native-short" | "native-long",
  binding: VisualPlanBinding,
  prepared: NativePreparation,
): Record<string, unknown> {
  const requestName = route === "native-short" ? "SHORT-REQUEST.json" : "LONG-REQUEST.json";
  const requestPath = path.join(prepared.directory, requestName);
  const requestSha256 = fileSha256(requestPath);
  if (!requestSha256 || requestSha256 !== prepared.requestHash
      || realpathSync(requestPath) !== requestPath) {
    throw new Error("Prepared native request does not match its controller hash");
  }
  return { schemaVersion: 1, kind: "auto-edit-native-route-handoff",
    status: "awaiting-native-author", route, producerDir: realpathSync(ctx.dir),
    visualPlan: binding, projectAuthority: currentVisualPlanProjectAuthority(ctx),
    request: { directory: prepared.directory, path: requestPath,
      sha256: requestSha256 },
    ...(prepared.projectDirectory
      ? { projectDirectory: prepared.projectDirectory } : {}) };
}

function persistHandoff(
  ctx: AutoEditCtx,
  value: Record<string, unknown>,
): NativeRouteHandoffPointer {
  const file = path.join(ctx.dir, HANDOFF_FILE);
  if (!existsSync(file)) atomicCreateJsonSync(file, value);
  if (realpathSync(file) !== file) {
    throw new Error("Native author handoff must be a canonical project file");
  }
  const observed = JSON.parse(readFileSync(file, "utf8")) as Record<string, unknown>;
  if (canonicalJsonSha256(observed) !== canonicalJsonSha256(value)
      || canonicalJson(observed) !== canonicalJson(value)) {
    throw new Error("Native author handoff changed after controller dispatch");
  }
  const request = observed.request as Record<string, string>;
  const visualPlan = observed.visualPlan as unknown as VisualPlanBinding;
  const route = observed.route as "native-short" | "native-long";
  return { schemaVersion: 1, route, status: "awaiting-native-author",
    path: realpathSync(file), sha256: fileSha256(file)!,
    requestPath: request.path, requestSha256: request.sha256,
    requestDirectory: request.directory, visualPlan,
    ...(typeof observed.projectDirectory === "string"
      ? { projectDirectory: observed.projectDirectory } : {}) };
}

/** Dispatch the allocator-owned route. Native lanes stop at an exact author handoff. */
export function dispatchAutoEditCreativeRoute(
  ctx: AutoEditCtx,
  overrides: Partial<CreativeRouteDispatchDependencies> = {},
): CreativeRouteDispatchOutcome {
  if (!ordinaryVisualPlanRequired(ctx)) {
    return { status: "ordinary", route: "ordinary" };
  }
  const authority = visualPlanValidationAuthority(ctx);
  const binding = projectVisualPlanBinding(
    ctx.dir, authority, ctx.visualPlan?.catalogReceiptAuthority,
  );
  if (!binding) return { status: "ordinary", route: "ordinary" };
  const route = allocatedCreativeRoute(ctx, binding);
  if (route === "ordinary") return { status: "ordinary", route };
  const deps = { ...DEFAULTS, ...overrides };
  const value = handoffValue(ctx, route, binding, prepare(ctx, route, deps));
  return { status: "awaiting_native_author", route,
    handoff: persistHandoff(ctx, value) };
}
