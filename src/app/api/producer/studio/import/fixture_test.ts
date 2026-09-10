import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import type { EditPlan } from "@/lib/producer/edit-plan";
import { jsonText } from "./files";

export function testPlan(): EditPlan {
  return { planVersion: 1, target: { mode: "longform", excerpt: true, scope: "light" },
    cutTrack: [{ sourceId: "raw-1", start: 0, end: 12, speed: 1 }],
    graphicsTrack: [{ id: "g-00000001", kind: "statement-card", outStart: 1, outEnd: 4,
      anchor: "own-screen", reason: "synthetic timing/copy check", spec: { variant: "classic", text: "Ship the *system*" } }],
  } as EditPlan;
}

export function emptyFixture(): { root: string; dir: string; plan: EditPlan } {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sniper-studio-import-test-")));
  const dir = path.join(root, "producer"); fs.mkdirSync(dir);
  fs.writeFileSync(path.join(root, "project.json"), jsonText({ origin: "raw", history: [], intent: { mode: "longform", scope: "light" } }));
  const plan = testPlan(); fs.writeFileSync(path.join(dir, "edit_plan.json"), jsonText(plan));
  return { root, dir, plan };
}

/** Tiny synthetic base only: no template render, models, network, or production fixtures. */
export function realFixture(): ReturnType<typeof emptyFixture> {
  const fixture = emptyFixture(); const base = path.join(fixture.dir, "base_final.mp4");
  execFileSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=160x90:d=12:r=10",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", base], { timeout: 10_000 });
  fs.writeFileSync(path.join(fixture.dir, "base_plan.json"), jsonText(fixture.plan));
  fs.writeFileSync(path.join(fixture.dir, "asset_manifest.json"), jsonText({ sources: [{ id: "raw-1", path: base, duration: 12 }] }));
  const script = String.raw`
import json,os,sys
sys.path.insert(0,sys.argv[1])
from studio.studio_project import GenerateRequest,generate_project
from fingerprints import fingerprint_record
d=sys.argv[2]; p=os.path.join(d,'edit_plan.json'); plan=json.load(open(p))
json.dump(fingerprint_record(plan),open(os.path.join(d,'base.fingerprint.json'),'w'))
generate_project(GenerateRequest(p,os.path.join(d,'base_final.mp4'),os.path.join(d,'studio')))
`;
  execFileSync(path.join(process.cwd(), ".venv/bin/python"), ["-c", script, path.join(process.cwd(), "scripts/producer"), fixture.dir], { timeout: 10_000 });
  fs.writeFileSync(path.join(fixture.dir, "final.mp4"), "existing-approved-final-fixture-bytes");
  return fixture;
}

export function patchCopy(dir: string, text: string): void {
  const file = path.join(dir, "studio/index.html");
  const html = fs.readFileSync(file, "utf8");
  fs.writeFileSync(file, html.replace(/data-variable-values='([^']*)'/u, (_match, raw: string) =>
    `data-variable-values='${JSON.stringify({ ...JSON.parse(raw), text })}'`));
}
