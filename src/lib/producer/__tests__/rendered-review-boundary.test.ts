import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs, { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { PROVIDER_MEDIA_PROFILE, providerMediaJail, SANDBOX_EXEC } from "../../../app/api/_lib/provider-media-jail";
import { runCodex } from "../../../app/api/_lib/codex-cli";
import { runLegacyBrainProcess } from "../../../app/api/producer/auto-edit/brain-review-process";
import { frameLabel, framesPerAttachment, renderedReviewAttachments }
  from "../../../app/api/producer/auto-edit/rendered-review-attachments";
import { claudeRenderedInput } from "../../../app/api/producer/auto-edit/rendered-review-invocation";

const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");
const darwin = process.platform === "darwin";

function scratch(): string {
  return mkdtempSync(path.join(os.tmpdir(), "rendered-boundary-"));
}

function jailRun(scope: { project: string; review: string }, file: string) {
  const jail = providerMediaJail("/bin/cat", [file], scope);
  return spawnSync(jail.bin, jail.args, { encoding: "utf8" });
}

test("the provider media profile hides the project except the review folder and denies media names", { skip: !darwin }, () => {
  const dir = scratch();
  try {
    const project = path.join(dir, "producer"), review = path.join(project, ".sniper-qc", "round-1");
    mkdirSync(review, { recursive: true });
    const outside = path.join(dir, "elsewhere");
    mkdirSync(outside);
    const scope = { project, review };
    const cases: Array<[string, boolean]> = [
      [path.join(review, "frame.jpg"), true], [path.join(review, "sheet-01.PNG"), true],
      [path.join(outside, "notes.json"), true], [path.join(project, "edit_plan.json"), false],
      [path.join(review, "final.mp4"), false], [path.join(outside, "RAW.MOV"), false],
      [path.join(outside, "take.Mp4"), false], [path.join(outside, "voice.WAV"), false],
      [path.join(outside, "abc.media"), false], [path.join(outside, "clip.ogv"), false],
      [path.join(outside, "clip.nut"), false], [path.join(outside, "track.mka"), false],
      [path.join(outside, "book.m4b"), false], [path.join(outside, "raw.y4m"), false],
      [path.join(outside, "stream.hevc"), false], [path.join(outside, ".snapshot-1234.tmp"), false],
    ];
    for (const [file] of cases) writeFileSync(file, "x");
    for (const [file, readable] of cases) {
      const run = jailRun(scope, file);
      assert.equal(run.status === 0 && run.stdout === "x", readable, `${path.relative(dir, file)} readable=${readable}`);
    }
    const child = providerMediaJail("/bin/sh", ["-c", `/bin/cat '${path.join(outside, "RAW.MOV")}'`], scope);
    assert.notEqual(spawnSync(child.bin, child.args).status, 0, "children inherit the boundary");
    const master = path.join(project, "master.mp4");
    writeFileSync(master, "video");
    const writes: Array<[string, string]> = [
      ["create", `echo x > '${path.join(project, "new.txt")}'`],
      ["create in review", `echo x > '${path.join(review, "new.jpg")}'`],
      ["rename media into review", `/bin/mv '${master}' '${path.join(review, "moved.jpg")}'`],
      ["hardlink media into review", `/bin/ln '${master}' '${path.join(review, "linked.jpg")}'`],
      ["delete", `/bin/rm '${path.join(project, "edit_plan.json")}'`],
    ];
    const control = providerMediaJail("/bin/sh", ["-c", `echo x > '${path.join(outside, "new.txt")}'`], scope);
    assert.equal(spawnSync(control.bin, control.args).status, 0, "control: writing outside the project still works");
    for (const [label, command] of writes) {
      const jailed = providerMediaJail("/bin/sh", ["-c", command], scope);
      assert.notEqual(spawnSync(jailed.bin, jailed.args).status, 0, `${label} is denied inside the project`);
    }
    assert.ok(fs.existsSync(master) && fs.existsSync(path.join(project, "edit_plan.json")), "project files are untouched");
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("the jail wraps an absolute admitted binary with the scope and the shipped profile", { skip: !darwin }, () => {
  const dir = scratch();
  try {
    const project = path.join(dir, "p"), review = path.join(project, "r");
    mkdirSync(review, { recursive: true });
    const scope = { project, review };
    assert.deepEqual(providerMediaJail("/bin/echo", ["hi"], scope).args.slice(4), ["-f", PROVIDER_MEDIA_PROFILE, "/bin/echo", "hi"]);
    assert.equal(providerMediaJail("/bin/echo", [], scope).bin, SANDBOX_EXEC);
    assert.throws(() => providerMediaJail("echo", [], scope), /absolute/);
    assert.throws(() => providerMediaJail("/bin/echo", [], { project, review: project }), /inside the project/);
    assert.throws(() => providerMediaJail("/bin/echo", [], { project: review, review: project }), /inside the project/);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("a jailed review must be tool-less on both providers", async () => {
  const scope = { project: "/p", review: "/p/r" };
  await assert.rejects(runCodex({ prompt: "x", sandbox: "read-only", timeoutMs: 1000, tools: "default", jail: scope }),
    /only to tool-less Codex runs/);
  await assert.rejects(runLegacyBrainProcess({ args: ["-p", "x", "--tools", "default"], cwd: os.tmpdir(), timeoutMs: 1000, jail: scope }),
    /only to tool-less Claude runs/);
});

test("frames are attached individually up to 16, then in 2x2, 3x3 or 4x4 sheets; never dropped", () => {
  assert.equal(framesPerAttachment(1, 24), 1);
  assert.equal(framesPerAttachment(16, 24), 1);
  assert.equal(framesPerAttachment(17, 24), 4);
  assert.equal(framesPerAttachment(96, 24), 4);
  assert.equal(framesPerAttachment(137, 24), 9);
  assert.equal(framesPerAttachment(137, 20), 9);
  assert.equal(framesPerAttachment(384, 24), 16);
  assert.throws(() => framesPerAttachment(385, 24), /cannot run/);
  assert.throws(() => framesPerAttachment(0, 24), /at least one/);
  assert.equal(frameLabel("/x/graphic3_t012.500.jpg"), "graphic3 @ 12.5s");
});

test("many frames become labelled contact sheets that cover every frame", async () => {
  const dir = scratch();
  try {
    const frames = Array.from({ length: 30 }, (_, index) => {
      const frame = path.join(dir, `card${index}_t${String(index).padStart(3, "0")}.000.png`);
      writeFileSync(frame, PNG);
      return frame;
    });
    mkdirSync(path.join(dir, "work"));
    const result = await renderedReviewAttachments(frames, path.join(dir, "work"));
    assert.equal(result.frames.length, 8);
    assert.deepEqual(result.frames.flatMap((sheet) => sheet.labels).length, 30);
    assert.equal(result.frames[0].labels[0], "#1 card0 @ 0s");
    const input = JSON.parse(claudeRenderedInput("TEXT", result)) as { message: { content: Array<{ type: string; source?: { media_type: string } }> } };
    assert.deepEqual(input.message.content.map((block) => block.type), ["text", ...Array(8).fill("image")]);
    assert.equal(input.message.content[1].source?.media_type, "image/jpeg");
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("non-image attachments are refused before any provider call", () => {
  const dir = scratch();
  try {
    const bogus = path.join(dir, "frame.jpg");
    writeFileSync(bogus, "not an image");
    assert.throws(() => claudeRenderedInput("x", { frames: [{ path: bogus, labels: ["#1"] }], reference: [] }), /not a JPEG or PNG/);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
