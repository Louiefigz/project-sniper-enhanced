import {
  accessSync,
  constants,
  existsSync,
  lstatSync,
  mkdirSync,
  realpathSync,
} from "node:fs";
import path from "node:path";
import { localWhisperPreflight } from
  "../../_lib/local-whisper-preflight";
import {
  pythonInterpreter,
  SCRIPTS_DIR,
} from "../../_lib/spawn-python";
import { producerAuthorityPaths } from
  "@/lib/server/producer-authority-files";
import { runCutRepairPython } from "./cut-repair-route-runner";

const PIN_CONTROLLER = path.join(
  SCRIPTS_DIR, "producer", "edit", "cut_repair_candidate_qc_pin.py");
const ALIGNMENT_IMPLEMENTATION = path.join(
  SCRIPTS_DIR, "producer", "edit",
  "source_waveform_alignment_adapter.py");
const ALIGNMENT_POLICY = path.join(
  SCRIPTS_DIR, "producer", "contracts",
  "cut-repair-source-waveform-alignment-policy-v1.json");
const VISUAL_IMPLEMENTATION = path.join(
  SCRIPTS_DIR, "producer", "edit", "cut_repair_visual_lip_sync.py");
const VISUAL_POLICY = path.join(
  SCRIPTS_DIR, "producer", "contracts",
  "cut-repair-visual-lip-sync-policy-v1.json");

function executable(candidate: string): string | null {
  try {
    accessSync(candidate, constants.X_OK);
    const resolved = realpathSync(candidate);
    return lstatSync(resolved).isFile() ? resolved : null;
  } catch {
    return null;
  }
}

function executableCandidates(name: string): string[] {
  return (process.env.PATH ?? "")
    .split(path.delimiter)
    .filter(Boolean)
    .map((entry) => path.join(entry, name));
}

function resolveExecutable(
  requested: string,
  fallbackName: string,
  label: string,
): string {
  const candidates = path.isAbsolute(requested)
    ? [requested]
    : [requested, ...executableCandidates(fallbackName)];
  const resolved = candidates.map(executable).find(Boolean);
  if (!resolved) {
    throw new Error(`CUT_REPAIR_QC_TOOLCHAIN_UNAVAILABLE:${label}`);
  }
  return resolved;
}

function ensureRealDirectory(directory: string): void {
  if (!existsSync(directory)) mkdirSync(directory, { mode: 0o700 });
  const stat = lstatSync(directory);
  if (!stat.isDirectory() || stat.isSymbolicLink()
      || realpathSync(directory) !== directory) {
    throw new Error("candidate QC toolchain directory is not canonical");
  }
}

function manifestPath(producerDir: string): string {
  const root = path.join(
    producerAuthorityPaths(producerDir).sagas,
    "cut-repair-automated-qc");
  ensureRealDirectory(root);
  return path.join(root, "tool-manifest.json");
}

function parsePinResult(
  code: number | null,
  stdout: string,
  stderr: string,
): void {
  let value: unknown;
  try {
    value = JSON.parse(stdout.trim());
  } catch {
    throw new Error(stderr.trim() || "candidate QC tool pin returned no JSON");
  }
  const row = value as Record<string, unknown>;
  if (code !== 0 || row.ok !== true
      || row.kind !== "cut-repair-qc-tool-manifest") {
    const blocker = row.blocker as Record<string, unknown> | undefined;
    throw new Error(
      typeof blocker?.message === "string"
        ? blocker.message : "candidate QC tool pin was rejected");
  }
}

/** Create-once the approved local QC manifest without network or downloads. */
export async function ensureCutRepairQcToolManifest(
  producerDir: string,
): Promise<string> {
  const output = manifestPath(producerDir);
  if (existsSync(output)) return output;
  const whisper = localWhisperPreflight();
  if (!whisper.ready || !whisper.binary || !whisper.model) {
    throw new Error(
      `CUT_REPAIR_QC_TOOLCHAIN_UNAVAILABLE:${whisper.detail ?? "Whisper"}`);
  }
  const ffmpeg = resolveExecutable(
    process.env.FFMPEG_BIN?.trim() || "ffmpeg", "ffmpeg", "ffmpeg");
  const python = resolveExecutable(
    pythonInterpreter(), "python3", "approved Python runtime");
  const args = [
    output,
    "--ffmpeg", ffmpeg,
    "--whisper", realpathSync(whisper.binary),
    "--whisper-model", realpathSync(whisper.model),
    "--aligner-runtime", python,
    "--aligner-implementation", realpathSync(ALIGNMENT_IMPLEMENTATION),
    "--aligner-policy", realpathSync(ALIGNMENT_POLICY),
    "--visual-runtime", python,
    "--visual-implementation", realpathSync(VISUAL_IMPLEMENTATION),
    "--visual-policy", realpathSync(VISUAL_POLICY),
  ];
  const result = await runCutRepairPython(
    PIN_CONTROLLER, args, "cut repair QC tool pin");
  parsePinResult(result.code, result.stdout, result.stderr);
  return output;
}
