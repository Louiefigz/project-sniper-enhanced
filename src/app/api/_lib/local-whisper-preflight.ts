import { spawnSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";

export interface LocalWhisperPreflight {
  ready: boolean;
  binary: string | null;
  version: string | null;
  model: string | null;
  detail: string | null;
}

function executable(candidate: string): boolean {
  try {
    fs.accessSync(candidate, fs.constants.X_OK);
    return fs.statSync(candidate).isFile();
  } catch {
    return false;
  }
}

function regularFile(candidate: string): boolean {
  try {
    return fs.statSync(candidate).isFile();
  } catch {
    return false;
  }
}

function binaryCandidates(): string[] {
  const explicit = process.env.WHISPER_CPP_BIN?.trim();
  if (explicit) return [path.resolve(explicit.replace(/^~/, os.homedir()))];
  const fromPath = (process.env.PATH ?? "")
    .split(path.delimiter)
    .filter(Boolean)
    .map((entry) => path.join(entry, "whisper-cli"));
  return [
    ...fromPath,
    "/opt/homebrew/bin/whisper-cli",
    "/usr/local/bin/whisper-cli",
  ];
}

function modelCandidates(): string[] {
  const explicit = process.env.WHISPER_CPP_MODEL?.trim();
  if (explicit) return [path.resolve(explicit.replace(/^~/, os.homedir()))];
  return [
    path.join(os.homedir(), ".cache/hyperframes/whisper/models/ggml-small.en.bin"),
    path.join(process.cwd(), "models/ggml-small.en.bin"),
    "/opt/homebrew/share/whisper-cpp/models/ggml-small.en.bin",
    "/usr/local/share/whisper-cpp/models/ggml-small.en.bin",
  ];
}

function whisperVersion(binary: string): string | null {
  const result = spawnSync(binary, ["--version"], {
    encoding: "utf8",
    timeout: 5_000,
  });
  const text = `${result.stdout ?? ""}\n${result.stderr ?? ""}`.trim();
  return result.status === 0 ? text.split("\n")[0] || null : null;
}

export function localWhisperPreflight(): LocalWhisperPreflight {
  const binary = binaryCandidates().find(executable) ?? null;
  const model = modelCandidates().find(regularFile) ?? null;
  const problems = [
    binary ? null : "whisper-cli was not found",
    model ? null : "a local whisper.cpp model was not found",
  ].filter(Boolean);
  return {
    ready: Boolean(binary && model),
    binary,
    version: binary ? whisperVersion(binary) : null,
    model,
    detail: problems.length ? problems.join("; ") : null,
  };
}
