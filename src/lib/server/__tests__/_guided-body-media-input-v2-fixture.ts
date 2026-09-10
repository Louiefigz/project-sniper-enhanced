/** Exact TEMP metadata only. No admission/source/runtime authority or native execution is simulated. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { bodyMediaTestV2 } from "@/lib/producer/__tests__/_guided-body-media-v2-fixture";
import { BODY_MEDIA_REFERENCES } from "@/lib/producer/contracts/guided-body-media-v1";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { canonicalJson } from "../auto-edit-hash";

/** Publish original fixture paths new-only before any reader hold exists. */
function write(file: string, bytes: string | Buffer): void {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  fs.writeFileSync(file, bytes, { mode: 0o600, flag: "wx" });
}

/** No source/tool path is accepted: all future mutations use these three literal original TEST metadata roles. */
export function bodyMediaInputV2Fixture(t: TestContext) {
  const root = fs.realpathSync(fs.mkdtempSync("/private/tmp/TEST-body-media-input-v2-"));
  t.after(() => { assert.equal(fs.realpathSync(root), root); fs.rmSync(root, { recursive: true }); });
  const value = bodyMediaTestV2(root);
  for (const name of BODY_MEDIA_REFERENCES) {
    const ref = value.references[name]; write(ref.path, canonicalJson({ TEST: name }));
    ref.sha256 = observeCutPreviewFile(ref.path, 4096).sha256;
  }
  for (const ref of [value.sourceColorReplay.input, value.sourceColorReplay.reservationArchive]) {
    write(ref.path, "TEST raw metadata; intentionally not a payload or JSON admission\n");
    Object.assign(ref, observeCutPreviewFile(ref.path, 4096)); delete (ref as { bytes?: Buffer }).bytes;
  }
  const file = path.join(root, "body-media-input.json"); write(file, canonicalJson(value));
  const paths = Object.freeze({ invocation: file, input: value.sourceColorReplay.input.path,
    archive: value.sourceColorReplay.reservationArchive.path });
  return { root, value, file, paths, sha256: observeCutPreviewFile(file, 128 * 1024).sha256 };
}
export type BodyMediaInputV2Fixture = ReturnType<typeof bodyMediaInputV2Fixture>;

/** Replace only one allowlisted original single-link user-owned TEMP metadata file, never an inventory path. */
export function replaceBodyMediaInputV2File(f: BodyMediaInputV2Fixture, role: keyof BodyMediaInputV2Fixture["paths"], bytes?: string | Buffer): void {
  const file = f.paths[role]; assert.ok(file.startsWith(f.root + path.sep)); assert.equal(fs.realpathSync(file), file);
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const temp = path.join(path.dirname(file), `TEST-replacement-${randomUUID()}.json`);
  fs.writeFileSync(temp, bytes ?? fs.readFileSync(file), { mode: 0o600, flag: "wx" }); fs.renameSync(temp, file);
}

/** Rewrite a new test-case declaration on the original input path and return its actual raw hash. */
export function publishBodyMediaInputV2Case(f: BodyMediaInputV2Fixture, value: unknown): string {
  replaceBodyMediaInputV2File(f, "invocation", canonicalJson(value));
  return observeCutPreviewFile(f.file, 128 * 1024).sha256;
}
