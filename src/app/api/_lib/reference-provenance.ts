export interface StudyFreshness {
  videoMtimeMs: number;
  deepMtimeMs: number;
  profileMtimeMs: number | null;
  recordedSha256: string;
  currentSha256: string;
}

export function assertStudyFresh(value: StudyFreshness): void {
  if (value.videoMtimeMs > value.deepMtimeMs) {
    throw new Error("reference source is newer than its deep study; rerun study before using it");
  }
  const recorded = /^[0-9a-f]{64}$/i.test(value.recordedSha256);
  if (!recorded || value.recordedSha256 === value.currentSha256) return;
  const reranAfterProfile = value.profileMtimeMs === null || value.deepMtimeMs > value.profileMtimeMs;
  if (!reranAfterProfile) {
    throw new Error("reference source hash changed after study; rerun study before using it");
  }
}
