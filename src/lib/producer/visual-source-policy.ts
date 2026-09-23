/** Source policy shared by fresh planning, edits and saved-runtime admission. */
import policy from "../../../schemas/producer/visual-source-policy-v1.json";

export const VISUAL_SOURCE_POLICY = policy;
export const VISUAL_SOURCE_POLICY_PATH = "schemas/producer/visual-source-policy-v1.json";
export const CATALOG_KINDS = Object.keys(policy.integrated);

export function requireCatalogKind(kind: unknown): string {
  if (typeof kind !== "string" || !Object.hasOwn(policy.integrated, kind)) {
    throw new Error(`Visual source ${JSON.stringify(kind)} is retired or unregistered. Select the HyperFrames catalog; use a source-bound native project for reference/custom work.`);
  }
  return kind;
}

/** Inspect input even when an older plan/schema/parser accepts its shape. */
export function assertPlanVisualSources(plan: Record<string, unknown>): void {
  if (plan.graphicsTrack !== undefined && !Array.isArray(plan.graphicsTrack)) throw new Error("Invalid graphicsTrack");
  for (const row of (plan.graphicsTrack ?? []) as Array<{ kind?: unknown }>) requireCatalogKind(row.kind);
  for (const lane of ["titleCards", "transitions"]) {
    if (plan[lane] !== undefined && (!Array.isArray(plan[lane]) || (plan[lane] as unknown[]).length)) {
      throw new Error(`Legacy ${lane} presets are retired. Use a HyperFrames catalog component in the native project.`);
    }
  }
  const target = plan.target;
  if (target !== undefined && target !== null && (typeof target !== "object" || Array.isArray(target))) {
    throw new Error("Invalid visual target; use graphicsStyle=catalog-first.");
  }
  if (target && (Object.hasOwn(target, "style") || Object.hasOwn(target, "visualProfile")
      || (Object.hasOwn(target, "graphicsStyle") && (target as Record<string, unknown>).graphicsStyle !== "catalog-first"))) {
    throw new Error("Legacy or unknown visual styles are retired; use graphicsStyle=catalog-first and current-job source evidence.");
  }
}

/** Immutable bytes from an old run do not grant permission under current policy. */
export function assertVisualSourceSnapshot(files: Array<{ path: string; hash: string }>, currentHash: string): void {
  if (files.find(row => row.path === VISUAL_SOURCE_POLICY_PATH)?.hash !== currentHash) {
    throw new Error("Saved pipeline predates the current HyperFrames source policy. Preserve the old evidence and start a migrated native project; this snapshot cannot execute.");
  }
  const retired = new Set(Object.keys(policy.retired));
  if (files.some(row => row.path.startsWith("templates/motion/compositions/")
      && retired.has(row.path.split("/").at(-1)!.replace(/\.html$/u, "")))) {
    throw new Error("Saved pipeline contains retired visual templates and cannot execute.");
  }
}

export const VISUAL_SOURCE_INSTRUCTIONS = [
  "Visual design is HyperFrames upstream catalog first. Search and inspect the complete catalog before selecting a graphic or transition.",
  "The compatibility menu contains verified installed ports only. Other catalog components use the native project workflow; do not force a local substitute or silently omit a requested visual.",
  "Reference design requires this job's explicit reference and evidence. Custom work requires inspected closest catalog alternatives, a concrete capability/quality gap, and bounded scope.",
  "Bind each authored design to visualSources evidence and its exact subject bytes. Retired Sniper house templates cannot be selected, restored or relabeled as custom.",
].join("\n");
