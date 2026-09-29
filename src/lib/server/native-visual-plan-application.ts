/** Prove that a Native Short executed every allocated visual-plan decision. */
import { boundVisualPlanContent, type VisualPlanBinding } from "./visual-plan-binding";
import type { NativeCatalogFile } from "./native-catalog-files";
import { assertNativeExecutionBinding,
  type NativeVisualExecutionBinding } from "./native-visual-execution-binding";

export interface NativeVisualPlanCatalogBinding {
  file: string;
  mountId: string;
  catalogId: string;
  sourceSha256: string;
  implementationSha256: string;
}

export interface NativeVisualPlanExecution {
  opportunityId: string;
  candidateId: string;
  anatomy: string;
  development: string;
  startFrame: number;
  endFrameExclusive: number;
  sceneIndexes: number[];
  visibleIds: string[];
  catalogBindings: NativeVisualPlanCatalogBinding[];
  binding: NativeVisualExecutionBinding;
}

export interface NativeVisualPlanApplication {
  schemaVersion: 1;
  route: "native-short" | "native-long";
  visualPlanSha256: string;
  decisions: NativeVisualPlanExecution[];
}

interface NativeScene {
  startFrame: number;
  endFrame: number;
  visibleIds: string[];
}

interface VisualCandidate {
  id: string;
  modality: string;
  source?: { recordId?: string; sourceSha256?: string } | null;
  catalogAdmission?: { executionStatus?: string } | null;
  composition: { anatomy: string; development: string };
}

interface VisualOpportunity {
  id: string;
  timing: { startFrame: number; endFrameExclusive: number };
  candidates: VisualCandidate[];
}

interface AllocatedVisualPlan {
  project: { fps: { numerator: number; denominator: number } };
  allocation: { status: string; route: string;
    decisions: Array<{ opportunityId: string; candidateId: string }> };
  opportunities: VisualOpportunity[];
}

function exactKeys(value: object, expected: string[], name: string): void {
  const keys = Object.keys(value).sort();
  if (keys.join("\0") !== [...expected].sort().join("\0")) {
    throw new Error(`${name} has unknown or missing fields`);
  }
}

function stableIds(value: unknown, name: string, maximum: number): string[] {
  if (!Array.isArray(value) || value.length > maximum
      || value.some((item) => typeof item !== "string"
        || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test(item))
      || new Set(value).size !== value.length) {
    throw new Error(`${name} must contain bounded unique stable IDs`);
  }
  return value;
}

function sceneIndexes(value: unknown, scenes: NativeScene[], timing: {
  startFrame: number; endFrameExclusive: number;
}): number[] {
  if (!Array.isArray(value) || value.some((item) => !Number.isSafeInteger(item))) {
    throw new Error("visual-plan application scene indexes are invalid");
  }
  const expected = scenes.flatMap((scene, index) =>
    scene.startFrame < timing.endFrameExclusive && scene.endFrame > timing.startFrame ? [index] : []);
  if (JSON.stringify(value) !== JSON.stringify(expected) || !expected.length) {
    throw new Error("visual-plan application does not bind the exact overlapping scenes");
  }
  return value;
}

function mountedCatalogFile(html: string, mountId: string, file: string): boolean {
  return [...html.matchAll(/<[^>]+>/gu)].some((match) =>
    match[0].includes(`id="${mountId}"`)
    && match[0].includes(`data-composition-src="${file}"`));
}

function catalogBindings(input: { value: unknown; candidate: VisualCandidate;
  catalogFiles: NativeCatalogFile[]; visibleIds: string[]; html: string }): void {
  const { value, candidate, catalogFiles, visibleIds, html } = input;
  if (!Array.isArray(value) || value.length > 8) {
    throw new Error("visual-plan application catalog bindings are invalid");
  }
  if (candidate.modality !== "catalog") {
    if (value.length) throw new Error("non-catalog visual-plan choice claims catalog execution");
    return;
  }
  if (!value.length || !candidate.source?.recordId || !candidate.source.sourceSha256) {
    throw new Error("catalog visual-plan choice lacks an exact executable source binding");
  }
  for (const item of value) {
    if (!item || typeof item !== "object") throw new Error("catalog binding must be an object");
    const row = item as NativeVisualPlanCatalogBinding;
    exactKeys(row, ["file", "mountId", "catalogId", "sourceSha256", "implementationSha256"],
      "visual-plan catalog binding");
    const actual = catalogFiles.find((file) => file.file === row.file);
    if (!stableIds([row.mountId], "visual-plan catalog mount ID", 1)[0]
        || !visibleIds.includes(row.mountId)
        || !mountedCatalogFile(html, row.mountId, row.file)
        || !actual || row.catalogId !== candidate.source.recordId
        || row.sourceSha256 !== candidate.source.sourceSha256
        || actual.catalogId !== row.catalogId || actual.sourceSha256 !== row.sourceSha256
        || actual.sha256 !== row.implementationSha256) {
      throw new Error("visual-plan catalog choice differs from its staged implementation");
    }
    if (candidate.catalogAdmission?.executionStatus === "reference"
        && row.implementationSha256 === candidate.source.sourceSha256) {
      throw new Error("reference catalog choice requires a project-owned adaptation");
    }
  }
}

function styleCoherence(input: { row: NativeVisualPlanExecution; styleApplication?: {
  choices?: unknown[]; supplementalChoices?: unknown[];
} }): void {
  const choices = [...(input.styleApplication?.choices ?? []),
    ...(input.styleApplication?.supplementalChoices ?? [])];
  for (const choice of choices) {
    if (!choice || typeof choice !== "object") continue;
    const value = choice as { sceneIndex?: unknown; visibleIds?: unknown;
      anatomy?: unknown; development?: unknown };
    const overlaps = typeof value.sceneIndex === "number"
      && input.row.sceneIndexes.includes(value.sceneIndex)
      && Array.isArray(value.visibleIds)
      && value.visibleIds.some((id) => input.row.visibleIds.includes(String(id)));
    if (overlaps && (value.anatomy !== input.row.anatomy
        || value.development !== input.row.development)) {
      throw new Error("visual-plan execution and style application disagree on composition development");
    }
  }
}

function validateExecution(input: { row: NativeVisualPlanExecution; opportunity: VisualOpportunity;
  candidate: VisualCandidate; scenes: NativeScene[]; html: string; catalogFiles: NativeCatalogFile[];
  assets: Array<{ file: string; sha256: string }>; seen: Set<string>; fps: number;
  styleApplication?: { choices?: unknown[]; supplementalChoices?: unknown[] } }): void {
  const { row, opportunity, candidate, scenes, html, catalogFiles } = input;
  exactKeys(row, ["opportunityId", "candidateId", "anatomy", "development",
    "startFrame", "endFrameExclusive",
    "sceneIndexes", "visibleIds", "catalogBindings", "binding"],
  "visual-plan application decision");
  const timing = opportunity.timing;
  if (row.opportunityId !== opportunity.id || row.candidateId !== candidate.id
      || row.anatomy !== candidate.composition.anatomy
      || row.development !== candidate.composition.development
      || row.startFrame !== timing.startFrame || row.endFrameExclusive !== timing.endFrameExclusive) {
    throw new Error("visual-plan application decision differs from its allocation or timing");
  }
  const indexes = sceneIndexes(row.sceneIndexes, scenes, timing);
  const visible = stableIds(row.visibleIds, "visual-plan application visible IDs", 64);
  if ((candidate.modality === "omit") !== (visible.length === 0)) {
    throw new Error("visual-plan application needs executable IDs for every rendered choice");
  }
  const owned = new Set(indexes.flatMap((index) => scenes[index].visibleIds));
  if (visible.some((id) => !owned.has(id) || !html.includes(`id="${id}"`))) {
    throw new Error("visual-plan application names an absent or unrelated executable visual");
  }
  if (visible.some((id) => input.seen.has(id))) {
    throw new Error("visual-plan application duplicates executable visual ownership");
  }
  visible.forEach((id) => input.seen.add(id));
  catalogBindings({ value: row.catalogBindings, candidate, catalogFiles,
    visibleIds: visible, html });
  assertNativeExecutionBinding({ binding: row.binding, candidate, visibleIds: visible,
    html, assets: input.assets, timing, fps: input.fps,
    catalogBindings: row.catalogBindings });
  styleCoherence({ row, styleApplication: input.styleApplication });
}

/** Validate complete allocation-to-scene execution for one frozen Native Short plan. */
export function assertNativeVisualPlanApplication(input: {
  binding?: VisualPlanBinding;
  application?: NativeVisualPlanApplication;
  scenes: NativeScene[];
  html: string;
  catalogFiles?: NativeCatalogFile[];
  assets?: Array<{ file: string; sha256: string }>;
  styleApplication?: { choices?: unknown[]; supplementalChoices?: unknown[] };
}): void {
  if (!input.binding) {
    if (input.application) throw new Error("visual-plan application lacks its planning authority");
    return;
  }
  if (!input.application) throw new Error("allocated visual plan requires an execution application");
  exactKeys(input.application, ["schemaVersion", "route", "visualPlanSha256", "decisions"],
    "native visual-plan application");
  const bound = boundVisualPlanContent(input.binding);
  const plan = bound.content as AllocatedVisualPlan;
  if (input.application.schemaVersion !== 1 || input.application.route !== "native-short"
      || input.application.visualPlanSha256 !== input.binding.visualPlanSha256
      || plan.allocation?.status !== "allocated" || plan.allocation.route !== "native-short") {
    throw new Error("native visual-plan application differs from its allocated authority");
  }
  const opportunities = new Map(plan.opportunities.map((row) => [row.id, row]));
  const fps = plan.project?.fps?.numerator / plan.project?.fps?.denominator;
  if (!Number.isFinite(fps) || fps <= 0) throw new Error("visual plan has no exact frame rate");
  if (!Array.isArray(input.application.decisions)
      || input.application.decisions.length !== plan.allocation.decisions.length) {
    throw new Error("visual-plan application must cover every allocated decision exactly once");
  }
  const seen = new Set<string>();
  plan.allocation.decisions.forEach((decision, index) => {
    const opportunity = opportunities.get(decision.opportunityId);
    const candidate = opportunity?.candidates.find((row) => row.id === decision.candidateId);
    if (!opportunity || !candidate) throw new Error("allocated visual-plan choice is missing");
    validateExecution({ row: input.application!.decisions[index], opportunity, candidate,
      scenes: input.scenes, html: input.html, catalogFiles: input.catalogFiles ?? [],
      assets: input.assets ?? [], seen, fps,
      styleApplication: input.styleApplication });
  });
}
