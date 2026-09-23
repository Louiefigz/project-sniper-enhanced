/** Stage inspected catalog adaptations without adding a global template preset. */
import { readFileSync, realpathSync } from "node:fs";
import path from "node:path";
import { fileSha256 } from "./auto-edit-hash";
import { VISUAL_SOURCE_POLICY } from "@/lib/producer/visual-source-policy";
import { SCRIPTS_DIR } from "@/app/api/_lib/spawn-python";

export interface NativeCatalogFile {
  file: string; path: string; sha256: string;
  catalogId: string; sourceSha256: string;
}

/** Files are locally adapted for assets/timing; exact upstream and final bytes are bound. */
export function nativeCatalogFiles(rows: NativeCatalogFile[] = []): Record<string, string> {
  if (rows.length > 128 || new Set(rows.map(row => row.file)).size !== rows.length) throw new Error("Invalid catalog file inventory");
  const root = path.resolve(SCRIPTS_DIR, "..", "vendor/hyperframes-catalog");
  const index = JSON.parse(readFileSync(path.join(root, "catalog-index.json"), "utf8")) as Array<{ name: string; type: string }>;
  const files: Record<string, string> = {};
  for (const row of rows) {
    const item = index.find(item => item.name === row.catalogId);
    if (!item || !/^compositions\/[a-z0-9][a-z0-9-]*\.html$/u.test(row.file)
        || !path.isAbsolute(row.path) || realpathSync(row.path) !== row.path
        || fileSha256(row.path) !== row.sha256
        || Object.values(VISUAL_SOURCE_POLICY.retired).includes(row.sha256)) throw new Error("Catalog implementation is missing, changed or retired");
    const source = path.join(root, "compositions", item.type === "component" ? "components" : "", `${item.name}.html`);
    if (fileSha256(source) !== row.sourceSha256) throw new Error("Catalog upstream source changed");
    const html = readFileSync(row.path, "utf8");
    if (/(?:src|href)=["'](?:https?:|\/\/)|url\(["']?(?:https?:|\/\/)/iu.test(html)) {
      throw new Error("Stage catalog dependencies locally before native assembly");
    }
    if (!/<template[\s>]/iu.test(html) || !/<[^>]+data-width=["']\d+["'][^>]*data-height=["']\d+["']/iu.test(html)) {
      throw new Error("Adapt catalog root to the pinned native template contract with explicit width and height");
    }
    files[row.file] = html;
  }
  return files;
}
