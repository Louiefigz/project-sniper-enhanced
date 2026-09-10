/** Tiny fresh capture fixture: real TS/model bytes, inert assets, no native tools or source admission. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import type { TestContext } from "node:test";
import { GUIDED_SOURCE_COLOR_TS_FILES } from "../guided-source-color-staging";
import { sourceColorIntentFixture } from "./_guided-opening-source-color-intent-fixture";

export const SOURCE_COLOR_CAPTURE_HOLES = ["src/app/api/producer/studio/import/files.ts",
  "src/app/api/producer/studio/import/evidence.ts", "src/app/api/producer/studio/import/model.ts", "src/lib/debug.ts"];
const ANCHORS = ["package.json", "package-lock.json", "tsconfig.json", "next.config.ts",
  "scripts/producer/headless/node_isolated_user.cjs", "docs/producer/command-driven-editing/contracts/render-effect-registry-v1.json",
  "schemas/producer/render-effect-registry-v1.schema.json", "templates/motion/hyperframes.json", "templates/motion/index.html",
  "templates/motion/motion-tokens.js", "templates/motion/package.json", "templates/motion/tokens.css",
  "templates/motion/vendor/gsap/gsap.min.js", "templates/motion/compositions/TEST-card.html",
  "assets/fonts/TEST.ttf", "assets/models/TEST.onnx", "assets/music/TEST.mp3", "assets/sfx/TEST.wav",
  "src/app/api/producer/auto-edit/TEST.ts", "src/app/api/producer/ai-edit/TEST.ts",
  "src/app/api/producer/live-build/TEST.ts", "src/app/api/producer/palmier/TEST.ts", "src/app/api/_lib/TEST.ts",
  "src/lib/producer/TEST.ts", "src/lib/server/TEST.ts"];
const LEGACY_CONTROLLERS = ["guided-opening-launch-store", "guided-opening-launcher", "guided-opening-controller",
  "guided-opening-execution", "opening-handoff-clock"].map(name => `src/lib/server/${name}.ts`);

/** Every publication is new-only under the already canonical disposable TEST root. */
function publish(root: string, relative: string, bytes: Buffer | string): void {
  assert(!path.isAbsolute(relative)); assert(!relative.split("/").includes(".."));
  const file = path.join(root, relative); fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  fs.writeFileSync(file, bytes, { flag: "wx", mode: 0o600 });
}

/** Source code is read boundedly, without executing it; the exact admitted model hash is unchanged. */
function originalBytes(relative: string): Buffer {
  const file = path.join(process.cwd(), relative), stat = fs.lstatSync(file);
  assert(stat.isFile()); assert(!stat.isSymbolicLink()); assert(stat.size <= 8 * 1024 * 1024);
  return fs.readFileSync(file);
}

/** Fresh pipeline capture sees a complete tiny repository, not a manually retrofitted pipeline.files list. */
export function sourceColorPipelineFixture(t: TestContext, extraSources: readonly string[] = []) {
  const f = sourceColorIntentFixture(t), repository = path.join(f.root, "TEST-repository");
  fs.mkdirSync(repository, { mode: 0o700 });
  const sourceNames = [...new Set([...GUIDED_SOURCE_COLOR_TS_FILES, ...SOURCE_COLOR_CAPTURE_HOLES, ...LEGACY_CONTROLLERS, ...extraSources])];
  for (const relative of sourceNames) publish(repository, relative, originalBytes(relative));
  for (const relative of ANCHORS.filter(name => !sourceNames.includes(name))) publish(repository, relative, `TEST inert capture anchor ${relative}\n`);
  const model = "scripts/producer/audio/models/bd.rnnn"; publish(repository, model, originalBytes(model));
  publish(repository, "scripts/producer/__tests__/TEST-excluded.ts", "TEST excluded\n");
  publish(repository, "scripts/producer/TEST-excluded.mp4", "TEST not media, excluded bytes\n");
  publish(repository, "src/lib/server/node_modules/TEST-excluded.ts", "TEST excluded\n");
  return { ...f, repository, sourceNames };
}

/** Fault only this exact copied TS file, never the actual repository dependency. */
export function removeCapturedPipelineFixtureSource(f: ReturnType<typeof sourceColorPipelineFixture>, relative: string): void {
  assert(SOURCE_COLOR_CAPTURE_HOLES.includes(relative)); const file = path.join(f.repository, relative);
  assert(file.startsWith(fs.realpathSync(f.root) + path.sep)); assert.equal(fs.realpathSync(file), file);
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  fs.unlinkSync(file);
}
