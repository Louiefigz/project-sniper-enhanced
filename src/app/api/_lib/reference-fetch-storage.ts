import fs from "node:fs";
import path from "node:path";
import { slugify, workspaceRoot } from "./workspace";

function referencesRoot(): string {
  return path.resolve(workspaceRoot(), "_references");
}

export function createProvisionalReferenceDir(url: URL): string {
  const root = referencesRoot();
  fs.mkdirSync(root, { recursive: true });
  const host = slugify(url.hostname.replace(/^www\./, "")) || "reference";
  return fs.mkdtempSync(path.join(root, `.incoming-${host}-`));
}

function createDirectory(directory: string): boolean {
  try {
    fs.mkdirSync(directory);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") return false;
    throw error;
  }
}

function moveReferenceDirectory(provisional: string, destination: string): void {
  for (const name of fs.readdirSync(provisional)) {
    fs.renameSync(path.join(provisional, name), path.join(destination, name));
  }
  fs.rmdirSync(provisional);
}

export function promoteReferenceDir(provisional: string, title: string): string {
  const root = referencesRoot();
  const base = slugify(title) || "reference";
  for (let n = 1; ; n++) {
    const directory = path.join(root, n === 1 ? base : `${base}-${n}`);
    if (!createDirectory(directory)) continue;
    try {
      moveReferenceDirectory(provisional, directory);
      return directory;
    } catch (error) {
      cleanupFailedReferenceFetch(directory);
      throw error;
    }
  }
}

export function cleanupFailedReferenceFetch(directory: string): void {
  try {
    const clean = path.resolve(directory);
    if (path.dirname(clean) !== referencesRoot()) return;
    fs.rmSync(clean, { recursive: true, force: true });
  } catch {}
}
