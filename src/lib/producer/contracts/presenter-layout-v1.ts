/** Declared manual layout geometry only; neither observed framing nor executable media authority. */
import { enumValue, exactKeys, objectValue, stringValue } from "./validation";
import { MANUAL_REFRAME_MIN_FRACTION } from "./treatment-proposal-v6";

export interface PresenterRectV1 { x: number; y: number; width: number; height: number }
export type PresenterMaskV1 = { kind: "rect" } | { kind: "circle" } | { kind: "rounded-rect"; radiusPx: number };
export interface PresenterLayoutV1 {
  schemaVersion: 1; sourceIds: string[]; layout: "inset" | "bubble" | "split";
  cropSpace: "held-base-display"; presenterCrop: PresenterRectV1; protectedPresenterRect: PresenterRectV1;
  presenterRect: PresenterRectV1; presentationRect: PresenterRectV1; mask: PresenterMaskV1;
  assetId: string; assetStart: { numerator: number; denominator: number };
  presentationFit: "contain"; assetAudio: "discard"; enterFrames: number; exitFrames: number;
  easing: "smoothstep-v1"; track: false;
}
export const PRESENTER_LAYOUT_MAX_FRAMES = 1_000_000_000;
const RECT_KEYS = ["x", "y", "width", "height"] as const;
const KEYS = ["schemaVersion", "sourceIds", "layout", "cropSpace", "presenterCrop", "protectedPresenterRect",
  "presenterRect", "presentationRect", "mask", "assetId", "assetStart", "presentationFit", "assetAudio",
  "enterFrames", "exitFrames", "easing", "track"];

function finite(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || Object.is(value, -0)) throw new Error(`${label} requires a finite canonical number`);
  return value;
}

function integer(value: unknown, label: string, minimum: number, maximum = Number.MAX_SAFE_INTEGER): number {
  const result = finite(value, label);
  if (!Number.isSafeInteger(result) || result < minimum || result > maximum) throw new Error(`${label} requires a bounded safe integer`);
  return result;
}

function rect(value: unknown, label: string): PresenterRectV1 {
  const row = objectValue(value, label); exactKeys(row, RECT_KEYS, RECT_KEYS, label);
  const result = { x: finite(row.x, label), y: finite(row.y, label), width: finite(row.width, label), height: finite(row.height, label) };
  if (result.x < 0 || result.y < 0 || result.width <= 0 || result.height <= 0
      || result.x + result.width > 1 || result.y + result.height > 1) throw new Error(`${label} leaves its normalized canvas`);
  return result;
}

function sourceIds(value: unknown): string[] {
  if (!Array.isArray(value) || !value.length || value.length > 128) throw new Error("Presenter sourceIds requires 1–128 ordered IDs");
  const ids = value.map((item) => stringValue(item, "presenter sourceId", 128));
  if (new Set(ids).size !== ids.length) throw new Error("Presenter sourceIds are duplicated");
  return ids;
}

function assetStart(value: unknown): PresenterLayoutV1["assetStart"] {
  const row = objectValue(value, "presenter assetStart");
  exactKeys(row, ["numerator", "denominator"], ["numerator", "denominator"], "presenter assetStart");
  const numerator = integer(row.numerator, "assetStart numerator", 0), denominator = integer(row.denominator, "assetStart denominator", 1);
  let a = BigInt(numerator), b = BigInt(denominator);
  while (b) { const next = a % b; a = b; b = next; }
  if (a !== BigInt(1)) throw new Error("Presenter assetStart must be reduced, including zero as 0/1");
  return { numerator, denominator };
}

function mask(value: unknown, layout: PresenterLayoutV1["layout"]): PresenterMaskV1 {
  const row = objectValue(value, "presenter mask");
  const kind = layout === "inset" ? "rounded-rect" : layout === "bubble" ? "circle" : "rect";
  const keys = kind === "rounded-rect" ? ["kind", "radiusPx"] : ["kind"];
  exactKeys(row, keys, keys, "presenter mask");
  if (row.kind !== kind) throw new Error("Presenter mask must match the exact layout class");
  if (kind !== "rounded-rect") return { kind };
  const radiusPx = finite(row.radiusPx, "presenter corner radius");
  if (radiusPx <= 0 || radiusPx > 8192) throw new Error("Presenter corner radius is outside bounded declared geometry");
  return { kind, radiusPx };
}

/** Parse intent without resolving assets, watching footage, guessing sources or authorizing a renderer. */
export function parsePresenterLayoutV1(value: unknown): PresenterLayoutV1 {
  const row = objectValue(value, "PresenterLayoutV1"); exactKeys(row, KEYS, KEYS, "PresenterLayoutV1");
  if (row.schemaVersion !== 1 || row.cropSpace !== "held-base-display" || row.presentationFit !== "contain"
      || row.assetAudio !== "discard" || row.easing !== "smoothstep-v1" || row.track !== false) {
    throw new Error("Presenter layout requires exact manual picture-only schema1 policies");
  }
  const layout = enumValue(row.layout, ["inset", "bubble", "split"] as const, "presenter layout");
  const presenterCrop = rect(row.presenterCrop, "presenter crop");
  if (Math.min(presenterCrop.width, presenterCrop.height) < MANUAL_REFRAME_MIN_FRACTION) throw new Error("Presenter crop is below the existing manual crop minimum");
  return { schemaVersion: 1, sourceIds: sourceIds(row.sourceIds), layout, cropSpace: "held-base-display", presenterCrop,
    protectedPresenterRect: rect(row.protectedPresenterRect, "protected manual presenter envelope"),
    presenterRect: rect(row.presenterRect, "presenter destination"), presentationRect: rect(row.presentationRect, "presentation destination"),
    mask: mask(row.mask, layout), assetId: stringValue(row.assetId, "presenter assetId", 128), assetStart: assetStart(row.assetStart),
    presentationFit: "contain", assetAudio: "discard", enterFrames: integer(row.enterFrames, "presenter enterFrames", 1, PRESENTER_LAYOUT_MAX_FRAMES),
    exitFrames: integer(row.exitFrames, "presenter exitFrames", 1, PRESENTER_LAYOUT_MAX_FRAMES), easing: "smoothstep-v1", track: false };
}

function inside(inner: PresenterRectV1, outer: PresenterRectV1): boolean {
  return inner.x >= outer.x && inner.y >= outer.y && inner.x + inner.width <= outer.x + outer.width
    && inner.y + inner.height <= outer.y + outer.height;
}

function approximately(a: number, b: number): boolean {
  // Numerical comparison only: sub-millionth-pixel error, not a geometry-fitting tolerance.
  return Math.abs(a - b) <= 1e-7;
}

function tiled(a: PresenterRectV1, b: PresenterRectV1): boolean {
  const horizontal = a.y === 0 && b.y === 0 && a.height === 1 && b.height === 1
    && a.width + b.width === 1 && (a.x === 0 && b.x === a.width || b.x === 0 && a.x === b.width);
  const vertical = a.x === 0 && b.x === 0 && a.width === 1 && b.width === 1
    && a.height + b.height === 1 && (a.y === 0 && b.y === a.height || b.y === 0 && a.y === b.height);
  return horizontal || vertical;
}

function maskContains(point: [number, number], size: [number, number], shape: PresenterMaskV1): boolean {
  const [x, y] = point, [width, height] = size;
  if (shape.kind === "rect") return true;
  if (shape.kind === "circle") return Math.hypot(x - width / 2, y - height / 2) <= width / 2;
  const r = shape.radiusPx, dx = Math.max(r - x, 0, x - (width - r)), dy = Math.max(r - y, 0, y - (height - r));
  return Math.hypot(dx, dy) <= r;
}

function assertEnvelope(value: PresenterLayoutV1, size: [number, number]): void {
  const crop = value.presenterCrop, region = value.protectedPresenterRect;
  if (!inside(region, crop)) throw new Error("Protected manual presenter envelope leaves the crop");
  const xs = [region.x, region.x + region.width], ys = [region.y, region.y + region.height];
  const points: [number, number][] = xs.flatMap((x) => ys.map((y): [number, number] =>
    [(x - crop.x) / crop.width * size[0], (y - crop.y) / crop.height * size[1]]));
  if (points.some((point) => !maskContains(point, size, value.mask))) throw new Error("Protected manual presenter envelope intersects its target mask");
}

/** Target-dependent declared geometry only; actual display/SAR/even-pixel/caption/frame checks remain mandatory. */
export function assertPresenterLayoutGeometry(input: unknown, canvas: { width: number; height: number }): void {
  const value = parsePresenterLayoutV1(input);
  const width = integer(canvas.width, "presenter canvas width", 2, 16384), height = integer(canvas.height, "presenter canvas height", 2, 16384);
  const p = value.presenterRect, crop = value.presenterCrop, size: [number, number] = [p.width * width, p.height * height];
  if (Math.min(...size, crop.width * width, crop.height * height) < 2) throw new Error("Presenter declared surfaces are smaller than two pixels");
  if (!approximately(size[1], crop.height * height / (crop.width * width) * size[0])) throw new Error("Presenter crop and destination would stretch the picture");
  if (value.layout === "bubble" && !approximately(...size)) throw new Error("Presenter bubble must be square in actual output pixels");
  if (value.mask.kind === "rounded-rect" && value.mask.radiusPx > Math.min(...size) / 2) throw new Error("Presenter radius exceeds its target mask");
  if (value.layout === "split" && !tiled(p, value.presentationRect)) throw new Error("Presenter split cells must tile the full canvas without overlaps or gaps");
  if (value.layout !== "split" && !RECT_KEYS.every((key) => value.presentationRect[key] === (key === "x" || key === "y" ? 0 : 1))) {
    throw new Error("Inset/bubble requires an explicit full-canvas presentation");
  }
  if (value.layout !== "split" && p.width === 1 && p.height === 1) throw new Error("Inset/bubble presenter must be smaller than the full canvas");
  assertEnvelope(value, size);
}
