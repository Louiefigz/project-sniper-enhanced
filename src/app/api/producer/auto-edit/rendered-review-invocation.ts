import fs from "node:fs";
import path from "node:path";
import { buildClaudeBrainArgs } from "./brain-review-process";
import type { RenderedReviewAttachments } from "./rendered-review-prompt";
import type { AutoEditCtx } from "./stream";

/** Per-image ceiling the providers accept for base64 image input. */
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

export function attachmentPaths(attachments: RenderedReviewAttachments): string[] {
  return [...attachments.frames, ...attachments.reference].map((row) => row.path);
}

/** JPEG or PNG only, read through one bounded regular-file read. */
function imageBlock(file: string): Record<string, unknown> {
  const stat = fs.lstatSync(file);
  if (!path.isAbsolute(file) || !stat.isFile() || stat.size <= 0 || stat.size > MAX_IMAGE_BYTES) {
    throw new Error(`rendered review attachment is not a bounded regular image: ${path.basename(file)}`);
  }
  const bytes = fs.readFileSync(file);
  const mediaType = bytes.subarray(0, 3).equals(Buffer.from([0xff, 0xd8, 0xff])) ? "image/jpeg"
    : bytes.subarray(0, 8).equals(Buffer.from("89504e470d0a1a0a", "hex")) ? "image/png" : null;
  if (!mediaType) throw new Error(`rendered review attachment is not a JPEG or PNG: ${path.basename(file)}`);
  return { type: "image", source: { type: "base64", media_type: mediaType, data: bytes.toString("base64") } };
}

/** One stream-json user message: the prompt text, then every attachment in manifest order. */
export function claudeRenderedInput(prompt: string, attachments: RenderedReviewAttachments): string {
  const content = [{ type: "text", text: prompt }, ...attachmentPaths(attachments).map(imageBlock)];
  return `${JSON.stringify({ type: "user", message: { role: "user", content } })}\n`;
}

/** Tool-less Claude critic reading its message (text + images) from stdin. */
export function claudeRenderedArgs(ctx: AutoEditCtx): string[] {
  return [...buildClaudeBrainArgs("", ctx, "isolated-review", []), "--input-format", "stream-json"];
}
