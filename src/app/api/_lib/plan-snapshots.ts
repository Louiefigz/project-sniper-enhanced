import fs from "fs";
import path from "path";

// Plan snapshots — before any writer overwrites edit_plan.json (the save-plan
// route, or the ai-edit route right before it hands the file to the claude
// CLI), copy the CURRENT plan into <dir>/plan-history/<planVersion>-<stamp>.json
// so a bad edit is always recoverable by hand. Newest 20 kept, older pruned.

const KEEP = 20;

function stamp(d: Date): string {
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return (
    `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}` +
    `-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
  );
}

function prune(historyDir: string): void {
  const files = fs
    .readdirSync(historyDir)
    .filter((f) => f.endsWith(".json"))
    .map((f) => ({ f, mtime: fs.statSync(path.join(historyDir, f)).mtimeMs }))
    .sort((a, b) => b.mtime - a.mtime);
  for (const { f } of files.slice(KEEP)) fs.unlinkSync(path.join(historyDir, f));
}

/**
 * Snapshot the plan file at `planPath` (if it exists) into its plan-history/
 * dir, prune to the newest 20, and return how many snapshots are on disk.
 * A missing plan file snapshots nothing and returns the current count.
 */
export function snapshotPlan(planPath: string): number {
  const historyDir = path.join(path.dirname(planPath), "plan-history");
  if (fs.existsSync(planPath)) {
    fs.mkdirSync(historyDir, { recursive: true });
    let version = 0;
    try {
      const plan = JSON.parse(fs.readFileSync(planPath, "utf-8")) as { planVersion?: number };
      version = Number(plan.planVersion) || 0;
    } catch {
      /* unparseable plan still gets snapshotted, versioned 0 */
    }
    fs.copyFileSync(planPath, path.join(historyDir, `${version}-${stamp(new Date())}.json`));
    prune(historyDir);
  }
  if (!fs.existsSync(historyDir)) return 0;
  return fs.readdirSync(historyDir).filter((f) => f.endsWith(".json")).length;
}
