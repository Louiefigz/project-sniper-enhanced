import crypto from "crypto";
import fs from "fs";
import path from "path";
import { listReferences } from "./projects-registry";
import { workspaceRoot } from "./workspace";
import { buildReferenceStyleProfile } from "./reference-profile";
import { sanitizeRepresentativeFrames } from "./reference-frame-policy";
import { validStoredReferenceDecision } from "./reference-decision";
import { assertStudyFresh } from "./reference-provenance";
import { validAdmittedReference } from "./reference-admission-verifier";
import { verifyReferenceVttAdmission } from "./reference-sidecar";
import { addIgnoredIds, atomicWriteJson, readIgnoredIds } from "./reference-storage";
import {
  evictReferenceJsonUnder,
  readDeepStudyVideo,
  readReferenceJson as readJson,
} from "./reference-json";
import type {
  ReferenceDecision,
  ReferenceEntry,
  ReferenceMetadata,
  ReferenceStyleProfile,
} from "./reference-types";
const VIDEO_EXTS = new Set([".mp4", ".mov", ".m4v", ".webm", ".mkv", ".media"]);
const ADMISSION_PENDING = ".sniper-admission-pending";
const TRANSCRIPT_SOURCE_WINDOW_MS = 10 * 60 * 1000;
const hashCache = new Map<string, { key: string; value: string }>();
function walkVideos(root: string): string[] {
  if (!fs.existsSync(root)) return [];
  const out: string[] = [];
  const visit = (dir: string) => {
    if (fs.existsSync(path.join(dir, ADMISSION_PENDING))) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const hit = path.join(dir, entry.name);
      if (entry.isDirectory() && !entry.isSymbolicLink() && !entry.name.startsWith(".")) visit(hit);
      if (entry.isFile() && VIDEO_EXTS.has(path.extname(entry.name).toLowerCase())) out.push(hit);
    }
  };
  visit(root);
  return out;
}
function namedFiles(root: string, name: string, maxDepth = 2): string[] {
  const out: string[] = [];
  const visit = (dir: string, depth: number) => {
    if (!fs.existsSync(dir) || depth > maxDepth) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const hit = path.join(dir, entry.name);
      if (entry.isFile() && entry.name === name) out.push(hit);
      if (entry.isDirectory() && !entry.isSymbolicLink() && !entry.name.startsWith(".")) visit(hit, depth + 1);
    }
  };
  visit(root, 0);
  return out;
}
export function stableReferenceId(video: string): string {
  const normalized = path.resolve(video).normalize("NFC");
  return `ref_${crypto.createHash("sha256").update(normalized).digest("hex").slice(0, 16)}`;
}
function directVideoCount(dir: string): number {
  try {
    return fs.readdirSync(dir).filter((name) => VIDEO_EXTS.has(path.extname(name).toLowerCase())).length;
  } catch {
    return 0;
  }
}
function deepStudyFor(video: string): string | null {
  const dir = path.dirname(video);
  const stem = path.parse(video).name;
  const candidates = namedFiles(dir, "deep_study.json");
  const scored = candidates.map((file) => {
    const sourceVideo = readDeepStudyVideo(file);
    const recorded = sourceVideo ? path.resolve(sourceVideo) : "";
    let score = recorded === path.resolve(video) ? 4 : path.basename(recorded) === path.basename(video) ? 3 : 0;
    const parent = path.basename(path.dirname(file));
    if (parent.startsWith(`${stem}.study`) || parent === "study") score = Math.max(score, 2);
    if ((parent === "deep" || parent === "full.study") && directVideoCount(dir) === 1) score = Math.max(score, 1);
    return { file, score, mtime: fs.statSync(file).mtimeMs };
  }).filter((row) => row.score > 0);
  return scored.sort((a, b) => b.score - a.score || b.mtime - a.mtime)[0]?.file ?? null;
}
export function canonicalStudyDir(video: string): string {
  const deep = deepStudyFor(video);
  if (deep) return path.dirname(deep);
  const dir = path.dirname(video);
  return path.join(dir, directVideoCount(dir) > 1 ? `${path.parse(video).name}.study` : "study");
}
function fingerprintFor(video: string, deep: string | null): string | null {
  const beside = deep ? path.join(path.dirname(deep), "fingerprint.json") : "";
  if (beside && fs.existsSync(beside)) return beside;
  const stem = path.parse(video).name;
  return namedFiles(path.dirname(video), "fingerprint.json")
    .find((file) => path.basename(path.dirname(file)).startsWith(`${stem}.study`)) ?? null;
}
function hasTimedWords(file: string): boolean {
  try {
    if (file.endsWith(".vtt")) return fs.readFileSync(file, "utf8").includes("<c>");
    const payload = readJson<unknown>(file);
    const record = payload && typeof payload === "object" && !Array.isArray(payload)
      ? payload as Record<string, unknown> : null;
    const rows = Array.isArray(payload) ? payload : record?.transcript;
    return Array.isArray(rows) && rows.some((row) => {
      if (!row || typeof row !== "object" || Array.isArray(row)) return false;
      const words = (row as Record<string, unknown>).words;
      return Array.isArray(words) && words.some((word) => {
        if (!word || typeof word !== "object" || Array.isArray(word)) return false;
        return Number.isFinite((word as Record<string, unknown>).start);
      });
    });
  } catch {
    return false;
  }
}
export function findWordTranscript(video: string): string | null {
  const dir = path.dirname(video);
  const stem = path.parse(video).name;
  const videoMtime = fs.statSync(video).mtimeMs;
  const source = readJson<Record<string, unknown>>(
    path.join(dir, "reference-source.json"),
  );
  const textRows = Array.isArray(source?.transcripts)
    ? source.transcripts
    : source?.transcript === null || source?.transcript === undefined
      ? []
      : [source.transcript];
  const admitted = new Set(
    textRows.map((row) => verifyReferenceVttAdmission(row, dir))
      .filter((file): file is string => file !== null),
  );
  const governed = source !== null;
  const siblings = fs.readdirSync(dir)
    .filter((name) => name.startsWith(stem) && name.toLowerCase().endsWith(".vtt"))
    .map((name) => path.join(dir, name))
    .filter((file) => !governed || admitted.has(path.resolve(file)))
    .filter((file) => fs.statSync(file).mtimeMs >= videoMtime - TRANSCRIPT_SOURCE_WINDOW_MS)
    .sort();
  const cached = [path.join(canonicalStudyDir(video), "transcript.json")]
    .filter((file) => fs.existsSync(file) && fs.statSync(file).mtimeMs >= videoMtime);
  return [...siblings, ...cached].find(hasTimedWords) ?? null;
}
function sha256(video: string, stat: fs.Stats): string {
  const key = `${stat.dev}:${stat.ino}:${stat.size}:${stat.mtimeMs}:${stat.ctimeMs}`;
  const cached = hashCache.get(video);
  if (cached?.key === key) return cached.value;
  const hash = crypto.createHash("sha256");
  const fd = fs.openSync(video, "r");
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  try {
    let size = fs.readSync(fd, buffer, 0, buffer.length, null);
    while (size) {
      hash.update(buffer.subarray(0, size));
      size = fs.readSync(fd, buffer, 0, buffer.length, null);
    }
  } finally {
    fs.closeSync(fd);
  }
  const value = hash.digest("hex");
  hashCache.set(video, { key, value });
  return value;
}
function sourceUrl(dir: string): string | null {
  const source = readJson<{ url?: unknown }>(path.join(dir, "reference-source.json"));
  return typeof source?.url === "string" ? source.url : null;
}
function validProfile(value: ReferenceStyleProfile | null, id: string): value is ReferenceStyleProfile {
  return value?.schemaVersion === 1 && value.referenceId === id &&
    typeof value.source?.video === "string" && typeof value.source?.sha256 === "string" &&
    Boolean(value.mechanics) && Boolean(value.quality) && Array.isArray(value.representativeFrames);
}
function profileFrom(deepPath: string | null, fingerprintPath: string | null,
                     title: string, video: string): ReferenceStyleProfile | null {
  if (!deepPath) return null;
  const id = stableReferenceId(video);
  const stored = readJson<ReferenceStyleProfile>(path.join(path.dirname(deepPath), "style_profile.json"));
  if (validProfile(stored, id)) return sanitizeRepresentativeFrames(stored, path.dirname(deepPath));
  const deep = readJson<Record<string, unknown>>(deepPath);
  if (!deep) return null;
  const profile = buildReferenceStyleProfile({ id, title, video, sha256: "", deep,
    fingerprint: fingerprintPath ? readJson<Record<string, unknown>>(fingerprintPath) : null });
  return sanitizeRepresentativeFrames(profile, path.dirname(deepPath));
}
function decisionFor(video: string, studyDir: string): { value: ReferenceDecision | null; path: string } {
  const decisionPath = path.join(studyDir, "reference.json");
  const value = readJson<ReferenceDecision>(decisionPath);
  const id = stableReferenceId(video);
  return { value: validStoredReferenceDecision(value, id) ? value : null, path: decisionPath };
}
function shellQuote(value: string): string {
  return `"${value.replace(/(["\\$`])/g, "\\$1")}"`;
}
function entryFor(video: string, registryTitles: Map<string, string>): ReferenceEntry {
  const stat = fs.statSync(video);
  const dir = path.dirname(video);
  const id = stableReferenceId(video);
  const title = registryTitles.get(dir) ?? path.parse(video).name;
  const deepStudyPath = deepStudyFor(video);
  const fingerprintPath = fingerprintFor(video, deepStudyPath);
  const studyDir = deepStudyPath ? path.dirname(deepStudyPath) : canonicalStudyDir(video);
  const recordedVideo = deepStudyPath ? readDeepStudyVideo(deepStudyPath) : null;
  const sourceMatches = recordedVideo !== null && path.resolve(recordedVideo) === path.resolve(video);
  const profile = sourceMatches
    ? profileFrom(deepStudyPath, fingerprintPath, title, video) : null;
  const decision = decisionFor(video, studyDir);
  const transcriptPath = findWordTranscript(video);
  const width = profile?.source.width ?? null;
  const height = profile?.source.height ?? null;
  const metadata: ReferenceMetadata = {
    fileName: path.basename(video), bytes: stat.size, mtimeMs: stat.mtimeMs,
    width, height, fps: profile?.source.fps ?? null,
    durationS: profile?.source.durationS ?? null,
    aspect: profile?.source.aspect ?? null,
    orientation: !width || !height ? null : width === height ? "square" : width > height ? "landscape" : "portrait",
    transcriptPath, sourceUrl: sourceUrl(dir),
  };
  const args = [".venv/bin/python3 scripts/producer/study/study_deep.py", shellQuote(video), shellQuote(studyDir)];
  if (transcriptPath) args.push("--transcript", shellQuote(transcriptPath));
  const hashRecorded = profile?.source.sha256.length === 64;
  const sourceFresh = !deepStudyPath || stat.mtimeMs <= fs.statSync(deepStudyPath).mtimeMs;
  const usableProfile = sourceFresh && validProfile(profile, id) && profile.representativeFrames.length > 0;
  const state = !deepStudyPath ? "not-studied" : !usableProfile ? "invalid" :
    decision.value && hashRecorded ? "ready" : "needs-decision";
  return {
    id, dir, title, exists: true, video, studied: Boolean(profile), cli: args.join(" "), metadata,
    profile, decision: decision.value,
    status: { state, deepStudyPath, fingerprintPath,
      profilePath: deepStudyPath && fs.existsSync(path.join(studyDir, "style_profile.json"))
        ? path.join(studyDir, "style_profile.json") : null,
      decisionPath: decision.path },
  };
}
export function listReferenceLibrary(): ReferenceEntry[] {
  const registered = listReferences();
  const titles = new Map(registered.map((entry) => [path.resolve(entry.dir), entry.title]));
  const roots = [path.join(workspaceRoot(), "_references"),
    ...registered.filter((entry) => entry.exists).map((entry) => entry.dir)];
  const videos = [...new Set(roots.flatMap(walkVideos).map((video) => path.resolve(video)))]
    .filter(validAdmittedReference);
  const ignored = readIgnoredIds(path.join(workspaceRoot(), "_references"));
  const visible = videos.filter((video) => {
    if (!ignored.has(stableReferenceId(video))) return true;
    evictReferenceJsonUnder(path.dirname(video));
    return false;
  });
  return visible.map((video) => entryFor(video, titles))
    .sort((a, b) => b.metadata.mtimeMs - a.metadata.mtimeMs);
}
export function findReferenceById(id: string): ReferenceEntry {
  const entry = listReferenceLibrary().find((candidate) => candidate.id === id);
  if (!entry) throw new Error(`unknown reference id: ${id}`);
  return entry;
}
export function persistStyleProfile(entry: ReferenceEntry): string {
  if (!entry.profile || !entry.status.deepStudyPath) throw new Error(`reference ${entry.id} is not studied`);
  const deep = readJson<Record<string, unknown>>(entry.status.deepStudyPath);
  if (!deep) throw new Error(`malformed deep study for ${entry.id}`);
  const stat = fs.statSync(entry.video);
  const deepStat = fs.statSync(entry.status.deepStudyPath);
  const profilePath = path.join(path.dirname(entry.status.deepStudyPath), "style_profile.json");
  const stored = readJson<ReferenceStyleProfile>(profilePath);
  const profileStat = fs.existsSync(profilePath) ? fs.statSync(profilePath) : null;
  const currentHash = sha256(entry.video, stat);
  assertStudyFresh({ videoMtimeMs: stat.mtimeMs, deepMtimeMs: deepStat.mtimeMs,
    profileMtimeMs: profileStat?.mtimeMs ?? null,
    recordedSha256: stored?.source?.sha256 ?? "", currentSha256: currentHash });
  const fingerprint = entry.status.fingerprintPath
    ? readJson<Record<string, unknown>>(entry.status.fingerprintPath) : null;
  const profile = buildReferenceStyleProfile({ id: entry.id, title: entry.title,
    video: entry.video, sha256: currentHash, deep, fingerprint });
  atomicWriteJson(profilePath, sanitizeRepresentativeFrames(profile, path.dirname(profilePath)));
  return profilePath;
}
export function persistReferenceDecision(entry: ReferenceEntry, decision: ReferenceDecision): string {
  const studyDir = entry.status.deepStudyPath
    ? path.dirname(entry.status.deepStudyPath) : canonicalStudyDir(entry.video);
  const decisionPath = path.join(studyDir, "reference.json");
  atomicWriteJson(decisionPath, decision);
  return decisionPath;
}
export function resolveReferenceStudy(id: string): {
  id: string; title: string; mode: "short" | "longform"; dir: string;
  profilePath: string; deepStudyPath: string; representativeFrames: string[];
} {
  const entry = findReferenceById(id);
  if (!entry.status.deepStudyPath || !entry.profile) throw new Error(`reference ${id} has no valid deep study`);
  if (!entry.decision) throw new Error(`reference ${id} has no confirmed operator decision`);
  const mode = entry.decision.mode;
  const profilePath = persistStyleProfile(entry);
  return { id, title: entry.title, mode, dir: entry.dir, profilePath,
    deepStudyPath: entry.status.deepStudyPath,
    representativeFrames: entry.profile.representativeFrames.filter((frame) => fs.existsSync(frame)) };
}
export function writeReferenceSource(dir: string, value: unknown): void {
  atomicWriteJson(path.join(dir, "reference-source.json"), value);
}
export function ignoreReferenceIds(ids: string[]): void {
  if (!ids.length || ids.some((id) => !/^ref_[0-9a-f]{16}$/.test(id))) {
    throw new Error("invalid reference id");
  }
  addIgnoredIds(path.join(workspaceRoot(), "_references"), ids);
}
export function videoExtensions(): ReadonlySet<string> { return VIDEO_EXTS; }
