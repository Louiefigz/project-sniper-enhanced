/** Current review dependencies and conservative, reusable ordinary-plan review units. */
import path from "node:path";
import { existsSync, readFileSync, readdirSync, realpathSync, statSync } from "node:fs";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { autoEditAuthoritySnapshot } from "./auto-edit-authority-snapshot";
import { canonicalJsonSha256 as hash, fileSha256 } from "./auto-edit-hash";
import { objectValue } from "@/lib/producer/contracts/validation";
import { requiredPlanningRounds } from "@/app/api/producer/auto-edit/round-policy";
import { pipelineRepositoryRoot } from "@/app/api/_lib/spawn-python";
import { assertPlanVisualSources } from "@/lib/producer/visual-source-policy";

export interface ReadinessUnit { id: string; hash: string; previewRequired: boolean }
export interface ReadinessPacket {
  schemaVersion: 1; kind: "producer-render-readiness-packet";
  digest: string; dependenciesHash: string; authority: ReturnType<typeof autoEditAuthoritySnapshot>;
  requiredReviews: number; units: ReadinessUnit[];
}

function mediaPins(ctx: AutoEditCtx): Record<string, string> {
  const manifest = objectValue(JSON.parse(readFileSync(ctx.manifestPath, "utf8")), "manifest");
  const pins: Record<string, string> = {};
  const rows = [manifest.sources, manifest.broll, manifest.music].flatMap(value => Array.isArray(value) ? value : []);
  for (const value of rows) {
    const row = objectValue(value, "manifest media");
    for (const key of ["path", "videoPath", "audioPath", "transcriptPath"]) {
      if (row[key] == null) continue;
      if (typeof row[key] !== "string" || !row[key]) throw new Error(`Invalid media ${key}`);
      const file = path.resolve(path.dirname(ctx.manifestPath), row[key]);
      const digest = fileSha256(file);
      if (!digest) throw new Error(`Readiness media is missing: ${file}`);
      pins[file] = digest;
    }
  }
  return pins;
}

/** Bind catalog sources/fonts and explicit local asset paths beyond manifest media. */
function visualPins(plan: Record<string, unknown>, ctx: AutoEditCtx): Record<string, string> {
  const root = pipelineRepositoryRoot(), files = new Set<string>();
  const seen = new Set<string>();
  function visit(directory: string): void {
    const real = realpathSync(directory);
    if (seen.has(real)) return;
    seen.add(real);
    for (const row of readdirSync(directory, { withFileTypes: true })) {
      const file = path.join(directory, row.name);
      if (row.isDirectory()) visit(file);
      else if (statSync(file).isFile()) files.add(file);
    }
  }
  for (const relative of ["vendor/hyperframes-catalog", "assets/fonts"]) {
    const directory = path.join(root, relative);
    if (existsSync(directory)) visit(directory);
  }
  function paths(value: unknown): void {
    if (Array.isArray(value)) { value.forEach(paths); return; }
    if (!value || typeof value !== "object") return;
    for (const [key, item] of Object.entries(value)) {
      if (typeof item !== "string" || !["path", "src", "assetPath", "mediaPath", "fontPath", "htmlPath"].includes(key)) { paths(item); continue; }
      if (/^https?:/i.test(item)) throw new Error("Readiness requires staged local visual assets");
      const candidates = [ctx.dir, path.dirname(ctx.manifestPath), root].map(base => path.resolve(base, item));
      const file = candidates.find(candidate => existsSync(candidate) && statSync(candidate).isFile());
      if (!file) throw new Error(`Readiness visual asset is missing: ${item}`);
      files.add(file);
    }
  }
  paths(plan);
  return Object.fromEntries([...files].sort().map(file => [file, fileSha256(file)!]));
}

function graphics(plan: Record<string, unknown>): Record<string, unknown>[] {
  if (plan.graphicsTrack == null) return [];
  if (!Array.isArray(plan.graphicsTrack) || plan.graphicsTrack.length > 1000) throw new Error("Invalid graphics review inventory");
  return plan.graphicsTrack.map(value => objectValue(value, "graphics review entry"));
}

function overlap(left: Record<string, unknown>, right: Record<string, unknown>): boolean {
  const values = [left.outStart, left.outEnd, right.outStart, right.outEnd];
  if (!values.every(value => typeof value === "number" && Number.isFinite(value))) return true;
  return Number(left.outStart) <= Number(right.outEnd) && Number(right.outStart) <= Number(left.outEnd);
}

/** Local catalog parameters/placement reuse distant units; global plan edits invalidate all. */
export function reviewUnits(plan: Record<string, unknown>, dependencies: unknown): ReadinessUnit[] {
  const entries = graphics(plan);
  const core = { ...plan };
  delete core.graphicsTrack;
  // Version is bookkeeping. Every other plan field remains an editorial dependency.
  delete core.planVersion;
  const inventory = entries.map(entry => {
    objectValue(entry.spec ?? {}, "graphics spec");
    // Only these fields are local to the graphic's existing timed render unit.
    // Track insertion/removal/order, kind, timing and unknown fields remain global.
    const global = { ...entry };
    delete global.spec;
    delete global.placement;
    return global;
  });
  const shared = hash({ core, inventory, dependencies });
  // A local copy change can change the promise/message even when distant pixels do not change.
  const units: ReadinessUnit[] = [{ id: "plan", hash: hash({ shared, entries }), previewRequired: true }];
  entries.forEach((entry, index) => {
    const context = entries.filter((other, position) => Math.abs(position - index) <= 1 || overlap(entry, other));
    units.push({ id: `graphicsTrack/${index}`, hash: hash({ shared, index, entry, context }), previewRequired: true });
  });
  return units;
}

/** Reuse the existing authority snapshot; add actual media bytes to editorial freshness. */
export function readinessPacket(ctx: AutoEditCtx): ReadinessPacket {
  const plan = objectValue(JSON.parse(readFileSync(ctx.planPath, "utf8")), "edit plan");
  assertPlanVisualSources(plan);
  const authority = autoEditAuthoritySnapshot(ctx);
  const shared = Object.fromEntries(Object.entries(authority).filter(([key]) => !["planHash", "planContentHash", "digest"].includes(key)));
  const dependencies = { shared, media: mediaPins(ctx), visuals: visualPins(plan, ctx) };
  const core = { schemaVersion: 1 as const, kind: "producer-render-readiness-packet" as const,
    authority, dependenciesHash: hash(dependencies), requiredReviews: requiredPlanningRounds(ctx.scope),
    units: reviewUnits(plan, dependencies) };
  return { ...core, digest: hash(core) };
}
