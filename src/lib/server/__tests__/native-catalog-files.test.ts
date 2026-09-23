import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { nativeShortFixture, refreshNativePacingFixture } from "./_native-short-project-fixture";
import { writeNativeShortProject, readNativeShortProject } from "../native-short-project";
import { fileSha256 } from "../auto-edit-hash";
import { VISUAL_SOURCE_POLICY } from "@/lib/producer/visual-source-policy";
import { nativeCatalogFiles } from "../native-catalog-files";

test("native project stages a mounted catalog title and binds it on cold read", () => {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-catalog-project-")));
  try {
    const input = nativeShortFixture(directory), policy = VISUAL_SOURCE_POLICY.integrated["count-up"];
    const source = path.join(directory, "counter.html");
    // Real upstream source, with its network script dependency localized; no playback claim.
    writeFileSync(source, readFileSync(path.join(process.cwd(), policy.upstreamPath), "utf8")
      .replace(/https:\/\/cdn\.jsdelivr\.net\/npm\/gsap@[^"']+/gu, "../assets/gsap.min.js").replace('id="root"', 'id="root" data-width="1080" data-height="1920"'));
    const file = "compositions/counter.html";
    input.catalogFiles = [{ file, path: source, sha256: fileSha256(source)!, catalogId: "count-up", sourceSha256: policy.upstreamSha256 }];
    input.catalogTitle = { file, copy: input.canvas.titleCard!.copy };
    delete input.canvas.titleCard;
    input.extension = { markup: `<div id="catalog-counter" class="clip" data-composition-src="${file}" data-start="0" data-duration="1" data-track-index="1"></div>`, css: "", motion: "" };
    refreshNativePacingFixture(input);
    const output = path.join(directory, "project");
    writeNativeShortProject(input, output);
    assert.equal(readNativeShortProject(output).catalogTitle?.file, file);
    assert.equal(readFileSync(path.join(output, file), "utf8"), readFileSync(source, "utf8"));
    input.catalogFiles[0].sourceSha256 = "0".repeat(64);
    assert.throws(() => nativeCatalogFiles(input.catalogFiles), /source changed/);
    input.catalogFiles[0].sourceSha256 = policy.upstreamSha256;
    input.extension.markup = "";
    refreshNativePacingFixture(input);
    assert.throws(() => writeNativeShortProject(input, path.join(directory, "unmounted")), /mounted/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
