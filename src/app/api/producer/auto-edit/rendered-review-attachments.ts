import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import { MAX_IMAGE_ATTACHMENTS } from "../../_lib/codex-cli";
import { pythonInterpreter, SCRIPTS_DIR } from "../../_lib/spawn-python";

const run = promisify(execFile);
/** Up to this many review frames are attached one by one at full resolution. */
export const INDIVIDUAL_FRAME_LIMIT = 16;
/** Reference representative frames, when a study is attached, take at most this many slots. */
export const REFERENCE_FRAME_SLOTS = 4;
const SHEET_SCRIPT = path.join(SCRIPTS_DIR, "producer", "audit", "critic_sheets.py");

export interface ReviewAttachment {
  path: string;
  labels: string[];
}

/** `{label}_t{seconds}.jpg` → `label @ seconds s` (audit_frames.py naming). */
export function frameLabel(framePath: string): string {
  const stem = path.basename(framePath).replace(/\.(jpe?g|png)$/iu, "");
  const match = /^(.*)_t0*(\d+\.\d+)$/u.exec(stem);
  return match ? `${match[1]} @ ${Number(match[2])}s` : stem;
}

/** Frames per attachment: 1 (individual) or a 2×2, 3×3 or 4×4 labelled sheet. */
export function framesPerAttachment(frameCount: number, slots: number): 1 | 4 | 9 | 16 {
  if (!Number.isInteger(frameCount) || frameCount < 1) throw new Error("rendered review requires at least one audit frame");
  if (frameCount <= Math.min(INDIVIDUAL_FRAME_LIMIT, slots)) return 1;
  for (const size of [4, 9, 16] as const) if (Math.ceil(frameCount / size) <= slots) return size;
  throw new Error(`rendered review has ${frameCount} frames, more than ${slots * 16} can be attached; the review cannot run`);
}

async function contactSheets(framePaths: string[], outDir: string, perSheet: 4 | 9 | 16): Promise<ReviewAttachment[]> {
  fs.mkdirSync(outDir, { mode: 0o700 });
  const request = path.join(path.dirname(outDir), `${path.basename(outDir)}.request.json`);
  fs.writeFileSync(request, JSON.stringify({ outDir, perSheet,
    frames: framePaths.map((framePath) => ({ path: framePath, label: frameLabel(framePath) })) }), { mode: 0o600 });
  try {
    const { stdout } = await run(pythonInterpreter(), ["-B", SHEET_SCRIPT, request], { timeout: 120_000, maxBuffer: 1024 * 1024 });
    const sheets = (JSON.parse(stdout) as { sheets: ReviewAttachment[] }).sheets;
    if (!Array.isArray(sheets) || sheets.reduce((total, sheet) => total + sheet.labels.length, 0) !== framePaths.length) {
      throw new Error("contact sheets do not cover every review frame");
    }
    return sheets;
  } finally {
    fs.rmSync(request, { force: true });
  }
}

/**
 * Still-image attachments for a tool-less rendered critic: every audit frame,
 * individually when few, otherwise in labelled contact sheets. Never drops a frame.
 */
export async function renderedReviewAttachments(framePaths: string[], workDir: string,
  referenceFrames: string[] = []): Promise<{ frames: ReviewAttachment[]; reference: ReviewAttachment[] }> {
  const reference = referenceFrames.slice(0, REFERENCE_FRAME_SLOTS)
    .map((framePath) => ({ path: framePath, labels: [`reference ${path.basename(framePath)}`] }));
  const perAttachment = framesPerAttachment(framePaths.length, MAX_IMAGE_ATTACHMENTS - reference.length);
  const frames = perAttachment === 1
    ? framePaths.map((framePath, index) => ({ path: framePath, labels: [`#${index + 1} ${frameLabel(framePath)}`] }))
    : await contactSheets(framePaths, path.join(workDir, `.critic-sheets-${randomUUID()}`), perAttachment);
  return { frames, reference };
}
