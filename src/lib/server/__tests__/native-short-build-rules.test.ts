/**
 * The native Short build's structural rules, moved into `native-short-build-rules.ts` by M-068's
 * `native-short-project` stage (review X128 m2, X142). Each moved rule is reached through the build's own entry
 * points (`assembleNativeShortHtml`, and `writeNativeShortProject` for `verifyAssets`), so the build path's calls are
 * pinned, not only the shared functions. TEST bytes and a synthetic plan only.
 *
 * No child process starts. The one child these paths would start, the visual-source admission's Python, is replaced
 * by a stub that answers only that call (its interpreter is a TEST file that is never executed); every other
 * child-process API throws.
 */
import assert from "node:assert/strict";
import childProcess from "node:child_process";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, before, test } from "node:test";
import { VISUAL_SOURCE_POLICY } from "@/lib/producer/visual-source-policy";
import { fileSha256 } from "../auto-edit-hash";
import { loadDirectorCatalog } from "../native-director-library";
import { fillLocalHookTemplate } from "../native-hook-template";
import { centeredNativeCaptionView } from "../native-short-composition";
import { assembleNativeShortHtml, writeNativeShortProject, type NativeShortProjectInput } from "../native-short-project";
import type { NativeAssetBinding } from "../native-short-strategy";
import { refreshNativePacingFixture, refreshNativeRequestPacketFixture } from "./_native-short-project-fixture";

const ROOT = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-build-rules-")));
const PYTHON = path.join(ROOT, "TEST-venv", "bin", "python3");
const CHILD_APIS = ["execFileSync", "execSync", "spawnSync", "spawn", "exec", "execFile", "fork"] as const;
const saved = { env: process.env.SNIPER_PYTHON_VENV_ROOT, apis: Object.fromEntries(CHILD_APIS.map(name => [name, childProcess[name]])) };
/** `text` with its regular-expression syntax characters escaped. */
const escaped = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
/** The build's asset-rule refusal for `file`, as a whole-message pattern. */
const ASSET_TEXT = (file: string) => new RegExp(`^Error: Native asset is missing, changed or not canonical: ${escaped(file)}$`, "u");

before(() => {
  mkdirSync(path.dirname(PYTHON), { recursive: true });
  writeFileSync(PYTHON, "#!/bin/sh\nexit 97\n");  // a TEST file, never run: every child API is replaced below
  chmodSync(PYTHON, 0o755);
  writeFileSync(path.join(ROOT, "TEST-venv", "pyvenv.cfg"), "home = TEST\n");
  process.env.SNIPER_PYTHON_VENV_ROOT = path.join(ROOT, "TEST-venv");
  const mutable = childProcess as unknown as Record<string, unknown>;
  for (const name of CHILD_APIS) mutable[name] = () => { throw new Error(`TEST refused a child process (${name})`); };
  mutable.execFileSync = (file: string, args: string[]) => {
    if (file !== PYTHON || !args.includes("graphics.visual_source_receipt")) throw new Error(`TEST refused a child process (${file})`);
    return "";
  };
});

after(() => {
  Object.assign(childProcess as unknown as Record<string, unknown>, saved.apis);
  if (saved.env === undefined) delete process.env.SNIPER_PYTHON_VENV_ROOT; else process.env.SNIPER_PYTHON_VENV_ROOT = saved.env;
  rmSync(ROOT, { recursive: true, force: true });
});

/** A TEST file bound as a plan asset. */
function asset(directory: string, name: string, file: string, role: NativeAssetBinding["role"]): NativeAssetBinding {
  const source = path.join(directory, name);
  writeFileSync(source, `TEST-only synthetic bytes ${name}`);
  return { path: source, sha256: fileSha256(source)!, file, role };
}

/** The synthetic Short `_native-short-project-fixture` builds, without its Python-written visual plan binding. */
function plan(): { input: NativeShortProjectInput; directory: string } {
  const directory = realpathSync(mkdtempSync(path.join(ROOT, "plan-")));
  const source = asset(directory, "source.mp4", "", "source");
  source.file = `assets/${source.sha256}.mp4`;
  const bindings = [source, asset(directory, "gsap.min.js", "assets/gsap.min.js", "runtime"),
    asset(directory, "Inter-Bold.ttf", "assets/Inter-Bold.ttf", "runtime"),
    asset(directory, "selected.jpg", "references/selected.jpg", "reference"), asset(directory, "alternate.jpg", "references/alternate.jpg", "reference")];
  const request = { selection: "auto", supportingVideo: "source-first" } as const;
  const copy = fillLocalHookTemplate(loadDirectorCatalog(), { anchor: "steps-toward-goal", slots: { count: "Two", goal: "test a saved plan" } });
  const input = { schemaVersion: 1, request, assets: bindings,
    canvas: { title: "TEST native contract", frameRate: "25/1", totalFrames: 50, background: "#111111",
      sourceSize: { w: 1920, h: 1080 }, sourceFile: source.file, cuts: [{ start: 0, end: 2, speed: 1 }],
      segments: [{ startFrame: 0, endFrameExclusive: 50 }], occurrences: [[0, 0, 0, 0, 20, "Test", 0], [1, 0, 1, 20, 45, "words.", 0]],
      captionGroups: [[0], [1]], pictureViews: [{ startFrame: 0, endFrame: 50, crop: [500, 0, 607.5, 1080], box: [0, 0, 1080, 1920] }],
      captionViews: [centeredNativeCaptionView({ startFrame: 0, endFrame: 50, top: 1000 })], text: [], shapes: [], motion: [],
      titleCard: { copy, lines: [copy.text], palette: "paper-on-ink", endFrame: 25, top: 80, fontSize: 64 } },
    strategy: { schemaVersion: 1, request, selectedTreatment: "TEST presenter", selectionReason: "TEST source performs the explanation",
      rejectedTreatment: "TEST diagram has no distinct relationship to show", viewerBenefit: "TEST understand saved-plan consistency",
      hookReasonToWatch: "TEST concrete contract goal", payoff: "TEST source words only",
      references: [3, 4].map(index => ({ assetFile: bindings[index].file, referenceId: `TEST-${index}`,
        observed: "TEST fixture observation, not actual visual review", adaptation: "TEST binding only" })),
      supportingSearch: { searchedSourceFiles: [source.file], candidates: [], conclusion: "TEST synthetic source has no supplemental evidence" },
      scenes: [{ startFrame: 0, endFrame: 50, viewingNeed: "TEST follow the speaker", format: "presenter", paneJobs: "TEST full portrait",
        before: "TEST opening state", action: "TEST spoken explanation", result: "TEST words retained", holdFrames: 5,
        visibleIds: ["source-0-0"], occurrenceIds: [0, 1], referenceIds: ["TEST-3"], exitReason: "TEST complete thought" }],
      review: { method: "local-editorial", findings: ["TEST binding-only fixture; no real creative review occurred"] } } } as unknown as NativeShortProjectInput;
  refreshNativeRequestPacketFixture(input);
  refreshNativePacingFixture(input);
  return { input, directory };
}

/** Stage the vendored count-up (read, never changed) as a mounted catalog title, as `native-catalog-files.test.ts` does. */
function withCatalog(input: NativeShortProjectInput, directory: string, mounted: boolean): void {
  const policy = VISUAL_SOURCE_POLICY.integrated["count-up"], source = path.join(directory, "counter.html");
  writeFileSync(source, readFileSync(path.join(process.cwd(), policy.upstreamPath), "utf8")
    .replace(/https:\/\/cdn\.jsdelivr\.net\/npm\/gsap@[^"']+/gu, "../assets/gsap.min.js").replace('id="root"', 'id="root" data-width="1080" data-height="1920"'));
  const file = "compositions/counter.html";
  input.catalogFiles = [{ file, path: source, sha256: fileSha256(source)!, catalogId: "count-up", sourceSha256: policy.upstreamSha256 }];
  input.catalogTitle = { file, copy: input.canvas.titleCard!.copy };
  delete input.canvas.titleCard;
  input.extension = { markup: mounted ? `<div id="catalog-counter" class="clip" data-composition-src="${file}" data-start="0" `
    + 'data-duration="1" data-track-index="1"></div>' : "", css: "", motion: "" };
  refreshNativePacingFixture(input);
}

test("the build refuses a script, frame or audio element in the scene extension", () => {
  const { input } = plan();
  for (const extension of [{ markup: "<script>x</script>", css: "", motion: "" }, { markup: "<iframe></iframe>", css: "", motion: "" },
    { markup: "<audio></audio>", css: "", motion: "" }, { markup: "", css: "", motion: "</script>" }]) {
    assert.throws(() => assembleNativeShortHtml({ ...input, extension }),
      /^Error: Native scene extension contains an unsupported script, audio or frame element$/u, JSON.stringify(extension));
  }
});

test("the build mounts the extension into the page its id and URL rules read", () => {
  const { input } = plan(), extension = (markup: string, css = "") => ({ ...input, extension: { markup, css, motion: "" } });
  assert.throws(() => assembleNativeShortHtml(extension('<div id="caption-0-0"></div>')), /duplicates a shared element identity/u);
  assert.throws(() => assembleNativeShortHtml(extension('<div id="d"></div><div id="d"></div>')), /duplicates a shared element identity/u);
  assert.throws(() => assembleNativeShortHtml(extension('<img src="references/x.png">')), /must use staged local assets/u);
  assert.throws(() => assembleNativeShortHtml(extension("", "<style>b{background:url(https://example.com/x.png)}</style>")),
    /must use staged local assets/u);
});

test("the build refuses a staged catalog file that no mount uses", () => {
  const unmounted = plan();
  withCatalog(unmounted.input, unmounted.directory, false);
  assert.throws(() => assembleNativeShortHtml(unmounted.input), /^Error: Catalog file must be mounted in the authored scene$/u);
  const mounted = plan();
  withCatalog(mounted.input, mounted.directory, true);
  assert.doesNotThrow(() => { try { assembleNativeShortHtml(mounted.input); } catch (error) {
    if (/must be mounted/u.test(String(error))) throw error;  // a later rule may refuse; this one may not
  } });
});

/** `writeNativeShortProject` as a review draft (no plan review needed), which reaches `verifyAssets` first. */
function writeDraft(input: NativeShortProjectInput, directory: string): () => unknown {
  delete input.prebuildReview;
  input.draft = { schemaVersion: 1, state: "review-pending" };
  return () => writeNativeShortProject(input, path.join(directory, "project"));
}

test("the build's verifyAssets refuses an asset that is not a canonical regular file with its bound bytes", () => {
  const cases: Array<[string, (row: NativeAssetBinding, directory: string) => void]> = [
    ["symlinked path", (row, directory) => { symlinkSync(row.path, path.join(directory, "linked.js")); row.path = path.join(directory, "linked.js"); }],
    ["relative path", row => { row.path = path.relative(process.cwd(), row.path); }],
    ["directory path", (row, directory) => { row.path = directory; }],
    ["changed bytes", row => { writeFileSync(row.path, "TEST changed after binding"); }],
    ["unknown role", row => { row.role = "illustration" as NativeAssetBinding["role"]; }],
    ["unsafe name", row => { row.file = "assets/My Font$&.js"; }]];
  for (const [name, change] of cases) {
    const { input, directory } = plan(), row = input.assets[1];
    change(row, directory);
    assert.throws(writeDraft(input, directory), ASSET_TEXT(row.file), name);
    assert.equal(existsSync(path.join(directory, "project")), false, name);
  }
  const { input, directory } = plan();  // references/ rows with the reference role are canonical
  assert.doesNotThrow(() => { try { writeDraft(input, directory)(); } catch (error) {
    if (/Native asset is missing, changed or not canonical/u.test(String(error))) throw error;
  } });
});
