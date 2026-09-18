import fs from "fs";
import path from "path";
import type { ReferenceStyleProfile } from "./reference-types";

const IMAGE_EXTS = new Set([".jpg", ".jpeg", ".png", ".webp"]);

function contained(file: string, root: string): string | null {
  try {
    const realFile = fs.realpathSync(file);
    if (!fs.statSync(realFile).isFile()) return null;
    const realRoot = fs.realpathSync(root);
    const relative = path.relative(realRoot, realFile);
    return relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative)
      ? realFile : null;
  } catch {
    return null;
  }
}

function safeFrame(file: string, studyDir: string): string | null {
  if (!IMAGE_EXTS.has(path.extname(file).toLowerCase())) return null;
  const candidates = path.isAbsolute(file) ? [file] : [
    path.resolve(studyDir, file),
    path.resolve(path.dirname(studyDir), file),
  ];
  return candidates.map((candidate) => contained(candidate, studyDir)).find(Boolean) ?? null;
}

export function sanitizeRepresentativeFrames(profile: ReferenceStyleProfile,
                                             studyDir: string): ReferenceStyleProfile {
  const representativeFrames = profile.representativeFrames
    .map((file) => safeFrame(file, studyDir))
    .filter((file): file is string => Boolean(file));
  return { ...profile, representativeFrames };
}
