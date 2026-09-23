/** Use the same offline source validator as native export and scene packages. */
import { execFileSync } from "node:child_process";
import path from "node:path";
import { pythonInterpreter, SCRIPTS_DIR } from "@/app/api/_lib/spawn-python";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import type { NativeShortProjectInput } from "./native-short-project";

export interface VisualSourceReceipt {
  schemaVersion: 1; policyVersion: string; subjectSha256: string;
  request: { path: string; sha256: string };
  decisions: Array<Record<string, unknown>>;
}

/** The complete authored canvas/extension, excluding the receipt itself. */
export function nativeVisualSourceSubject(input: NativeShortProjectInput) {
  return { canvas: input.canvas, extension: input.extension ?? null, catalogFiles: input.catalogFiles ?? [], catalogTitle: input.catalogTitle ?? null };
}

export function nativeVisualSourceTargets(input: NativeShortProjectInput): string[] {
  const ids = [...input.canvas.text, ...input.canvas.shapes].map(row => row.id);
  if (input.canvas.titleCard) ids.push("native-title-card");
  if (input.canvas.captionViews.length) ids.push("caption-presentation");
  if (input.extension && Object.values(input.extension).some(value => value.trim())) ids.push("scene-extension");
  ids.push(...(input.catalogFiles ?? []).map(row => row.file));
  return [...new Set(ids)].sort();
}

/** Called before materialization and on cold reads; no caller can skip source policy. */
export function assertNativeVisualSources(input: NativeShortProjectInput): void {
  const subject = nativeVisualSourceSubject(input), receipt = input.visualSources;
  if (!receipt || receipt.subjectSha256 !== canonicalJsonSha256(subject)) {
    throw new Error("Native design needs current visualSources evidence. Select the HyperFrames catalog or document this job's reference/custom exception.");
  }
  if (input.requestPacket && JSON.stringify(receipt.request) !== JSON.stringify(input.requestPacket)) {
    throw new Error("Visual source decisions must bind this project’s current request packet");
  }
  const producer = path.join(SCRIPTS_DIR, "producer");
  try {
    execFileSync(pythonInterpreter(), ["-B", "-m", "graphics.visual_source_receipt"], {
      cwd: producer, env: { ...process.env, PYTHONPATH: producer, PYTHONDONTWRITEBYTECODE: "1" },
      input: JSON.stringify({ receipt, subject, targets: nativeVisualSourceTargets(input) }),
      encoding: "utf8", timeout: 10_000, maxBuffer: 1024 * 1024, stdio: ["pipe", "pipe", "pipe"],
    });
  } catch (error) {
    const stderr = (error as { stderr?: string }).stderr ?? String(error);
    throw new Error(`Native visual source admission failed: ${stderr.slice(-2000)}`);
  }
}
