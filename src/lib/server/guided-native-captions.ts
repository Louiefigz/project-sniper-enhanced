/** One bounded call to the existing Python phrase policy; no duplicate TypeScript grouper. */
import path from "node:path";
import { writeFileSync } from "node:fs";
import { runCutPreviewProcess } from "@/app/api/producer/auto-edit/cut-preview-process";
import { pythonInterpreter } from "@/app/api/_lib/spawn-python";
import { canonicalJson } from "./auto-edit-hash";
import type { NativeShortDirection } from "./guided-native-candidate";
import { stageTimingEnv } from "./stage-timing-context";
import { generationChildTimeout } from "./generation-attempt-clock";

export type NativeCaptionGroups = number[][];

/** One shared next-phrase boundary for rendering and pacing measurements. */
export function nativeCaptionGroupEnd(input: {
  occurrences: NativeShortDirection["occurrences"]; captionGroups: NativeCaptionGroups; totalFrames: number;
}, index: number): number {
  const group = input.captionGroups[index], next = input.captionGroups[index + 1];
  return Math.min(input.occurrences[group.at(-1)!][4], next ? input.occurrences[next[0]][3] : input.totalFrames);
}

/** Grouping must preserve each occurrence exactly once, in order, within its source cut. */
export function assertNativeCaptionGroups(value: unknown, direction: Pick<NativeShortDirection, "occurrences">): asserts value is NativeCaptionGroups {
  if (!Array.isArray(value) || !value.length || value.length > direction.occurrences.length) throw new Error("Native caption groups are absent or unbounded");
  let next = 0;
  for (const group of value) {
    if (!Array.isArray(group) || !group.length) throw new Error("Native caption group is empty");
    const segment = direction.occurrences[next]?.[1];
    for (const index of group) {
      if (index !== next || direction.occurrences[index]?.[1] !== segment) throw new Error("Native captions lost occurrence order or crossed a source cut");
      next++;
    }
  }
  if (next !== direction.occurrences.length) throw new Error("Native captions omitted kept words");
}

/** Exact staged clock enters the captured caption implementation once, with owned process cleanup. */
export async function prepareNativeCaptionGroups(input: { directory: string; direction: NativeShortDirection; pipelineRoot: string; remainingMs: () => number }) {
  const file = path.join(input.directory, "native-caption-input.json");
  writeFileSync(file, canonicalJson(input.direction), { flag: "wx", mode: 0o600 });
  const root = path.join(input.pipelineRoot, "scripts/producer"), script = path.join(root, "studio/native_caption_groups.py");
  const result = await runCutPreviewProcess({ command: pythonInterpreter(), args: [script, file], cwd: input.directory,
    timeoutMs: generationChildTimeout(30_000, input.remainingMs), env: { ...stageTimingEnv(), PYTHONPATH: root, PYTHONDONTWRITEBYTECODE: "1" } });
  const value = JSON.parse(result.stdout);
  if (value.schemaVersion !== 1) throw new Error("Unsupported native caption grouping reply");
  assertNativeCaptionGroups(value.groups, input.direction);
  return value.groups as NativeCaptionGroups;
}
