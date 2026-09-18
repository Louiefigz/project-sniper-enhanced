/** Backed upper title cards adapted from inspected A02 and the operator's reference. */
import { assertHookLineBreaks, type NativeTitleCopy } from "./native-hook-template";

export const NATIVE_TITLE_PALETTES = {
  "white-on-black": { ink: "#ffffff", backing: "#111111" },
  "white-on-red": { ink: "#ffffff", backing: "#b81732" },
  "red-on-white": { ink: "#b81732", backing: "#ffffff" },
} as const;
export interface NativeTitleCard {
  copy: NativeTitleCopy;
  lines: string[];
  palette: keyof typeof NATIVE_TITLE_PALETTES;
  endFrame: number;
  top: number;
  fontSize: number;
}
export interface NativeTitleClock { frameRate: string; totalFrames: number }

function escape(text: string): string {
  return text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

/** Return measurable opaque colors; foreground/backing must be judged as a pair. */
export function titleContrast(palette: keyof typeof NATIVE_TITLE_PALETTES): number {
  if (!Object.hasOwn(NATIVE_TITLE_PALETTES, palette)) throw new Error("Unknown native title palette");
  const pair = NATIVE_TITLE_PALETTES[palette];
  const luminance = (hex: string) => {
    const values = [1, 3, 5].map((index) => parseInt(hex.slice(index, index + 2), 16) / 255)
      .map((channel) => channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4);
    return values[0] * .2126 + values[1] * .7152 + values[2] * .0722;
  };
  const values = [luminance(pair.ink), luminance(pair.backing)].sort((a, b) => a - b);
  return (values[1] + .05) / (values[0] + .05);
}

/** Editable, immediately readable title; its compact backing follows each authored line. */
export function renderNativeTitleCard(card: NativeTitleCard, clock: NativeTitleClock): string {
  assertHookLineBreaks(card.copy, card.lines);
  const [num, den] = clock.frameRate.split("/").map(Number);
  if (!/^\d+\/\d+$/u.test(clock.frameRate) || !num || !den
      || !Number.isSafeInteger(clock.totalFrames) || clock.totalFrames < 1
      || !Number.isSafeInteger(card.endFrame) || card.endFrame < 1 || card.endFrame > clock.totalFrames
      || !Number.isFinite(card.top) || card.top < 72 || card.top > 250
      || !Number.isFinite(card.fontSize) || card.fontSize < 64 || card.fontSize > 96
      || card.top + card.lines.length * (card.fontSize * 1.1 + 24) > 580
      || titleContrast(card.palette) < 4.5) throw new Error("Native title needs a bounded upper position, readable type and exact lifetime");
  const pair = NATIVE_TITLE_PALETTES[card.palette];
  const lineStyle = `display:table;margin:0 auto;padding:12px 22px;max-width:920px;white-space:nowrap;`
    + `color:${pair.ink};background:${pair.backing};border-radius:16px;`;
  const provenance = card.copy.scope === "user-supplied-title" ? ' data-title-scope="user-supplied-title"'
    : ` data-hook-anchor="${escape(card.copy.anchor)}" data-library-hash="${escape(card.copy.libraryHash)}"`;
  return `<div id="native-title-card" data-hf-id="hf-native-title-card" class="clip native-title-card"`
    + ` data-start="0" data-duration="${card.endFrame * den / num}" data-track-index="5"`
    + provenance
    + ` style="position:absolute;left:80px;top:${card.top}px;width:920px;z-index:5;text-align:center;`
    + `font:700 ${card.fontSize}px/1.1 Inter;">`
    + card.lines.map((line, index) => `<span id="native-title-line-${index}" data-hf-id="hf-native-title-line-${index}" style="${lineStyle}">${escape(line)}</span>`).join("")
    + "</div>";
}
