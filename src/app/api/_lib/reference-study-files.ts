import fs from "fs";
import path from "path";

const GENERATED = ["deep_study.json", "fingerprint.json", "report.md", "style_profile.json",
  "reference_style_pack.json", "mechanics-review.json", "editorial-review.json",
  "adjudication-review.json", "template-registry.json", "reference-review",
  "frames", "states", "events"] as const;

export function finishStudyBackup(studyDir: string, backup: string, keepNew: boolean): void {
  if (keepNew) {
    fs.rmSync(backup, { recursive: true, force: true });
    return;
  }
  for (const name of GENERATED) fs.rmSync(path.join(studyDir, name), { recursive: true, force: true });
  for (const name of fs.readdirSync(backup)) {
    fs.renameSync(path.join(backup, name), path.join(studyDir, name));
  }
  fs.rmSync(backup, { recursive: true, force: true });
}

function recoverInterruptedBackup(studyDir: string): void {
  const backups = fs.readdirSync(studyDir)
    .filter((name) => name.startsWith(".study-backup-")).sort();
  if (!backups.length) return;
  finishStudyBackup(studyDir, path.join(studyDir, backups.at(-1)!), false);
  backups.slice(0, -1).forEach((name) =>
    fs.rmSync(path.join(studyDir, name), { recursive: true, force: true }));
}

export function backupStudyOutputs(studyDir: string): string {
  recoverInterruptedBackup(studyDir);
  const backup = path.join(studyDir, `.study-backup-${Date.now().toString(36)}`);
  fs.mkdirSync(backup);
  for (const name of GENERATED) {
    const source = path.join(studyDir, name);
    if (fs.existsSync(source)) fs.renameSync(source, path.join(backup, name));
  }
  return backup;
}
