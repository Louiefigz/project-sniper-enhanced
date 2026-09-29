/**
 * Derive preview dependency regions from the actual executable composition mounts.
 *
 * The map is generated from the staged index.html and catalog composition bytes, both of
 * which the prebuild review already binds, so it never enters the reviewed plan hash; the cold
 * reader re-derives it byte-for-byte. It schedules and scopes moving previews only: it is not
 * editorial approval, pixel evidence or final QC. `studio/native_review_regions.py` re-checks
 * every interval against the same mounts before using a row.
 */
import { Parser } from "htmlparser2";
import { analyzeComposition, compositionControlsVisibility, rootVisibilitySafe, rootStylesIsolated,
  type CompositionIsolation } from "./native-composition-isolation";
import { rootScriptsIsolated } from "./native-root-isolation";

export const NATIVE_REVIEW_REGIONS_FILE = "REVIEW-REGIONS.json";
export const NATIVE_REVIEW_REGIONS_DERIVATION = "mounted-composition-intervals-v1";
export interface NativeReviewRegion {
  id: string; file: string; startFrame: number; endFrame: number; isolation: CompositionIsolation;
}
export interface NativeReviewRegionMap {
  schemaVersion: 2; derivation: typeof NATIVE_REVIEW_REGIONS_DERIVATION; units: NativeReviewRegion[];
}
interface Mount { attributes: Record<string, string>; timedAncestor: boolean }
interface ExecutableScan { mounts: Mount[]; ids: string[]; compositionIds: string[]; styles: string[]; scripts: string[]; externalSafe: boolean }

const DECIMAL = /^(?:0|[1-9]\d*)(?:\.\d+)?$/u;
const FILE = /^compositions\/([a-z0-9][a-z0-9-]{0,79})\.html$/u;

/** One streaming pass over the executable document, mirroring the Python mount parser's stack. */
function scanExecutable(html: string): ExecutableScan {
  const scan: ExecutableScan = { mounts: [], ids: [], compositionIds: [], styles: [], scripts: [], externalSafe: true };
  const stack: Array<{ name: string; timed: boolean }> = [];
  let capture: { kind: "styles" | "scripts"; text: string } | undefined;
  const parser = new Parser({
    onopentag(name, attributes) {
      if (name === "link" || name === "script" && attributes.src !== undefined && attributes.src !== "assets/gsap.min.js") {
        scan.externalSafe = false;
      }
      if (Object.keys(attributes).some(attribute => /^on/iu.test(attribute))) scan.externalSafe = false;
      if (attributes.style !== undefined) scan.styles.push(`element{${attributes.style}}`);
      if (attributes["data-composition-src"] !== undefined) {
        scan.mounts.push({ attributes, timedAncestor: stack.some(row => row.timed) });
      }
      if (attributes.id !== undefined) scan.ids.push(attributes.id);
      if (attributes["data-composition-id"] !== undefined) scan.compositionIds.push(attributes["data-composition-id"]);
      stack.push({ name, timed: attributes["data-start"] !== undefined });
      if (name === "style" || (name === "script" && attributes.src === undefined)) {
        capture = { kind: name === "style" ? "styles" : "scripts", text: "" };
      }
    },
    ontext(text) { if (capture) capture.text += text; },
    onclosetag(name) {
      if (capture && (name === "style" || name === "script")) { scan[capture.kind].push(capture.text); capture = undefined; }
      const index = stack.map(row => row.name).lastIndexOf(name);
      if (index >= 0) stack.splice(index);
    },
  }, { decodeEntities: true });
  parser.write(html);
  parser.end();
  return scan;
}

/**
 * Exact active frames of a root-clock mount in exported pictures. The pinned SDK's capture and
 * render file server injects `__HF_EXPORT_RENDER_SEEK_CONFIG` (cli.js buildRenderModeScript),
 * so the runtime snaps clip bounds with floor(seconds * fps + 1e-9) and shows [start, end).
 * Python recomputes the same IEEE-754 expression; overlap tests widen it by one frame.
 */
export function mountFrames(attributes: Record<string, string>, rate: number): [number, number] | undefined {
  const start = attributes["data-start"], duration = attributes["data-duration"];
  if (start === undefined || duration === undefined || !DECIMAL.test(start) || !DECIMAL.test(duration)
      || attributes["data-end"] !== undefined || attributes["data-hidden"] !== undefined) return undefined;
  const begin = Number(start), end = begin + Number(duration);
  return [Math.floor(begin * rate + 1e-9), Math.floor(end * rate + 1e-9)];
}

function compositionIds(html: string): string[] {
  return scanExecutable(html).compositionIds;
}

function isolationFor(scan: ExecutableScan, files: Record<string, string>, file: string, mount: Mount): CompositionIsolation {
  const host = { compositionId: mount.attributes["data-composition-id"] ?? "", style: mount.attributes.style ?? "" };
  const seen = scan.compositionIds.filter(id => id === host.compositionId).length;
  const foreign = new Set(Object.entries(files).filter(([name]) => name !== file).flatMap(([, html]) => compositionIds(html)));
  if (seen !== 1) foreign.add(host.compositionId);
  const rootIds = new Set(scan.ids.filter(id => id !== mount.attributes.id));
  return analyzeComposition(files[file], host, { rootIds, foreignCompositionIds: foreign });
}

/** Map every uniquely mounted, frame-exact catalog composition; anything else stays global. */
export function deriveNativeReviewRegions(html: string, files: Record<string, string>,
  canvas: { frameRate: string; totalFrames: number }): NativeReviewRegionMap | undefined {
  const [num, den] = canvas.frameRate.split("/").map(Number);
  if (!Number.isSafeInteger(num) || !Number.isSafeInteger(den) || den <= 0 || num % den !== 0) return undefined;
  const rate = num / den, scan = scanExecutable(html);
  const documentSafe = scan.externalSafe && rootVisibilitySafe(scan.styles, scan.scripts)
    && rootStylesIsolated(scan.styles) && rootScriptsIsolated(scan.scripts, new Set(scan.ids))
    && Object.values(files).every(file => !compositionControlsVisibility(file));
  const units: NativeReviewRegion[] = [];
  for (const mount of scan.mounts) {
    const file = mount.attributes["data-composition-src"], id = FILE.exec(file)?.[1];
    const range = mountFrames(mount.attributes, rate);
    if (!id || id.startsWith("project-") || !(file in files) || mount.timedAncestor || !range
        || scan.mounts.filter(row => row.attributes["data-composition-src"] === file).length !== 1
        || range[0] >= range[1] || range[1] > canvas.totalFrames) continue;
    let isolation = isolationFor(scan, files, file, mount);
    if (isolation.status === "scoped" && !documentSafe) {
      isolation = { status: "global", reason: "document styles or scripts lack composition independence proof" };
    }
    units.push({ id, file, startFrame: range[0], endFrame: range[1], isolation });
  }
  // An unconfined sibling can read the edited body's DOM or expose its fragment
  // resources elsewhere. Its unchanged source bytes do not prove independence.
  const complete = units.every(unit => unit.isolation.status === "scoped")
    && scan.mounts.every(mount => units.some(unit => unit.file === mount.attributes["data-composition-src"]));
  if (!complete) {
    for (const unit of units) {
      unit.isolation = { status: "global", reason: "another mounted composition lacks document independence proof" };
    }
  }
  units.sort((left, right) => left.startFrame - right.startFrame || (left.id < right.id ? -1 : 1));
  return units.length ? { schemaVersion: 2, derivation: NATIVE_REVIEW_REGIONS_DERIVATION, units } : undefined;
}
