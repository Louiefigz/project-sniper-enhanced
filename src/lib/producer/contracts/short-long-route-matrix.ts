import {
  enumValue,
  exactKeys,
  objectValue,
  stableId,
  stringValue,
  uniqueStrings,
} from "./validation";

const STATUSES = [
  "released",
  "compatibility",
  "unqualified",
  "unsupported",
  "not-applicable",
] as const;
const MODE_POLICIES = [
  "form-neutral",
  "mode-aware",
  "delivery-only",
] as const;

export type FormStatus = (typeof STATUSES)[number];

export interface FormDispositionV1 {
  status: FormStatus;
  behavior: string;
  blockers: string[];
}

export interface ShortLongRouteGroupV1 {
  groupId: string;
  routes: string[];
  role: string;
  modePolicy: (typeof MODE_POLICIES)[number];
  short: FormDispositionV1;
  longform: FormDispositionV1;
  incrementalBoundary: string;
  palmierBoundary: string;
}

export interface ShortLongWorkflowV1 {
  workflowId: string;
  entrypoints: string[];
  short: FormDispositionV1;
  longform: FormDispositionV1;
  incrementalBoundary: string;
  palmierBoundary: string;
}

export interface ShortLongRouteMatrixV1 {
  schemaVersion: 1;
  asOf: string;
  completeness: "complete";
  phaseExit: "passed";
  routeRoot: string;
  routeGroups: ShortLongRouteGroupV1[];
  workflows: ShortLongWorkflowV1[];
  evidence: Record<string, string[]>;
}

function strings(value: unknown, label: string): string[] {
  return uniqueStrings(value, label, (item, itemLabel) =>
    stringValue(item, itemLabel, 2_000));
}

function disposition(value: unknown, label: string): FormDispositionV1 {
  const row = objectValue(value, label);
  const keys = ["status", "behavior", "blockers"] as const;
  exactKeys(row, keys, keys, label);
  const status = enumValue(row.status, STATUSES, `${label}.status`);
  const blockers = strings(row.blockers, `${label}.blockers`);
  if (status === "released" && blockers.length) {
    throw new Error(`${label} released status cannot retain blockers`);
  }
  if ((status === "unqualified" || status === "unsupported")
      && !blockers.length) {
    throw new Error(`${label} must explain its blocking gates`);
  }
  return {
    status,
    behavior: stringValue(row.behavior, `${label}.behavior`, 4_000),
    blockers,
  };
}

function parseRouteGroup(value: unknown, index: number): ShortLongRouteGroupV1 {
  const label = `routeGroups[${index}]`;
  const row = objectValue(value, label);
  const keys = [
    "groupId", "routes", "role", "modePolicy", "short", "longform",
    "incrementalBoundary", "palmierBoundary",
  ] as const;
  exactKeys(row, keys, keys, label);
  const routes = strings(row.routes, `${label}.routes`);
  if (!routes.length) throw new Error(`${label} must own at least one route`);
  return {
    groupId: stableId(row.groupId, `${label}.groupId`),
    routes,
    role: stringValue(row.role, `${label}.role`, 2_000),
    modePolicy: enumValue(row.modePolicy, MODE_POLICIES, `${label}.modePolicy`),
    short: disposition(row.short, `${label}.short`),
    longform: disposition(row.longform, `${label}.longform`),
    incrementalBoundary: stringValue(
      row.incrementalBoundary, `${label}.incrementalBoundary`, 4_000),
    palmierBoundary: stringValue(
      row.palmierBoundary, `${label}.palmierBoundary`, 4_000),
  };
}

function parseWorkflow(value: unknown, index: number): ShortLongWorkflowV1 {
  const label = `workflows[${index}]`;
  const row = objectValue(value, label);
  const keys = [
    "workflowId", "entrypoints", "short", "longform",
    "incrementalBoundary", "palmierBoundary",
  ] as const;
  exactKeys(row, keys, keys, label);
  const entrypoints = strings(row.entrypoints, `${label}.entrypoints`);
  if (!entrypoints.length) {
    throw new Error(`${label} must name an executable entrypoint`);
  }
  return {
    workflowId: stableId(row.workflowId, `${label}.workflowId`),
    entrypoints,
    short: disposition(row.short, `${label}.short`),
    longform: disposition(row.longform, `${label}.longform`),
    incrementalBoundary: stringValue(
      row.incrementalBoundary, `${label}.incrementalBoundary`, 4_000),
    palmierBoundary: stringValue(
      row.palmierBoundary, `${label}.palmierBoundary`, 4_000),
  };
}

function uniqueIds(rows: Array<{ groupId?: string; workflowId?: string }>): void {
  const ids = rows.map((row) => row.groupId ?? row.workflowId!);
  if (new Set(ids).size !== ids.length) {
    throw new Error("short/long matrix ids repeat");
  }
}

function parseEvidence(
  value: unknown,
  expectedIds: string[],
): Record<string, string[]> {
  const row = objectValue(value, "short/long matrix evidence");
  const actualIds = Object.keys(row).sort();
  if (JSON.stringify(actualIds) !== JSON.stringify([...expectedIds].sort())) {
    throw new Error("short/long matrix evidence must cover every exact matrix id");
  }
  return Object.fromEntries(actualIds.map((id) => {
    const paths = strings(row[id], `short/long matrix evidence.${id}`);
    if (!paths.length) throw new Error(`short/long matrix evidence.${id} is empty`);
    return [id, paths];
  }));
}

export function parseShortLongRouteMatrixV1(
  value: unknown,
): ShortLongRouteMatrixV1 {
  const row = objectValue(value, "ShortLongRouteMatrixV1");
  const keys = [
    "schemaVersion", "asOf", "completeness", "phaseExit", "routeRoot",
    "routeGroups", "workflows", "evidence",
  ] as const;
  exactKeys(row, keys, keys, "ShortLongRouteMatrixV1");
  if (row.schemaVersion !== 1 || row.completeness !== "complete"
      || row.phaseExit !== "passed" || !Array.isArray(row.routeGroups)
      || !row.routeGroups.length || !Array.isArray(row.workflows)
      || !row.workflows.length) {
    throw new Error("ShortLongRouteMatrixV1 is malformed");
  }
  const asOf = stringValue(row.asOf, "short/long matrix asOf", 10);
  if (!/^\d{4}-\d{2}-\d{2}$/u.test(asOf)) {
    throw new Error("short/long matrix asOf is not a date");
  }
  const routeGroups = row.routeGroups.map(parseRouteGroup);
  const workflows = row.workflows.map(parseWorkflow);
  uniqueIds([...routeGroups, ...workflows]);
  const ids = [
    ...routeGroups.map((group) => group.groupId),
    ...workflows.map((workflow) => workflow.workflowId),
  ];
  return {
    schemaVersion: 1,
    asOf,
    completeness: "complete",
    phaseExit: "passed",
    routeRoot: stringValue(row.routeRoot, "short/long routeRoot", 1_000),
    routeGroups,
    workflows,
    evidence: parseEvidence(row.evidence, ids),
  };
}

function cell(value: FormDispositionV1): string {
  const blockers = value.blockers.length
    ? ` Blockers: ${value.blockers.join("; ")}` : "";
  return `**${value.status}** — ${value.behavior}${blockers}`;
}

export function renderShortLongRouteMatrixMarkdown(
  matrix: ShortLongRouteMatrixV1,
): string {
  const lines = [
    "# Short-form versus long-form executable matrix",
    "",
    "> Generated from `contracts/short-long-route-matrix-v1.json`. "
      + "Do not edit this file by hand.",
    "",
    `Evidence date: ${matrix.asOf}. Documentation parity gate: **PASS**.`,
    "",
    "A status describes the current executable boundary, not the desired end state. "
      + "`compatibility` means the path works but still carries a broader or legacy "
      + "render/authority boundary; `unqualified` means code exists without release proof.",
    "",
    "## Operator workflows",
    "",
    "| Workflow | Short-form | Long-form | Incremental boundary | Palmier boundary |",
    "|---|---|---|---|---|",
    ...matrix.workflows.map((row) =>
      `| \`${row.workflowId}\` | ${cell(row.short)} | ${cell(row.longform)} `
      + `| ${row.incrementalBoundary} | ${row.palmierBoundary} |`),
    "",
    "## Production API route coverage",
    "",
    "| Route group | Routes | Mode policy | Short-form | Long-form |",
    "|---|---|---|---|---|",
    ...matrix.routeGroups.map((row) =>
      `| \`${row.groupId}\` | ${row.routes.map((route) => `\`${route}\``).join("<br>")} `
      + `| ${row.modePolicy} | ${cell(row.short)} | ${cell(row.longform)} |`),
    "",
    "Every `route.ts` below the configured route root appears exactly once in "
      + "the machine contract. The parity test also requires every workflow "
      + "entrypoint and every route path to exist.",
    "",
  ];
  return `${lines.join("\n")}\n`;
}
