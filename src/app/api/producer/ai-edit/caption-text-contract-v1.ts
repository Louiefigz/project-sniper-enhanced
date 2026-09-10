const EDGE_WHITESPACE_CLASS = [
  "\\u0009-\\u000d\\u001c-\\u0020\\u0085\\u00a0\\u1680",
  "\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff",
].join("");
const EDGE_WHITESPACE = new RegExp(
  `^[${EDGE_WHITESPACE_CLASS}]+|[${EDGE_WHITESPACE_CLASS}]+$`, "gu",
);

/** Caption limits count Unicode code points, never UTF-16 code units. */
export function captionCodePointLength(value: string): number {
  return Array.from(value).length;
}

/** Trim the explicit V1 caption-edge whitespace set in every runtime. */
export function trimCaptionText(value: string): string {
  return value.replace(EDGE_WHITESPACE, "");
}

export function captionTextWithinLimit(
  value: unknown,
  maximum: number,
): value is string {
  return typeof value === "string"
    && Boolean(trimCaptionText(value))
    && captionCodePointLength(value) <= maximum;
}
