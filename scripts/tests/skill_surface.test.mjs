import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = process.cwd();
const SKILLS = ["clipper", "producer", "producer-study", "reference-editor", "segmenter"];
const COMMANDS = [
  "clip",
  "produce",
  "produce-palmier",
  "produce-studio",
  "producer-study",
  "reference-edit",
  "segment",
  "setup",
];

function directoriesWithSkill(relative) {
  const base = path.join(ROOT, relative);
  return fs.readdirSync(base).filter((name) => {
    const entry = path.join(base, name);
    assert.equal(fs.lstatSync(entry).isSymbolicLink(), false, `${relative}/${name} must not be a symlink`);
    return fs.statSync(entry).isDirectory() && fs.existsSync(path.join(entry, "SKILL.md"));
  }).sort();
}

assert.deepEqual(directoriesWithSkill(".claude/skills"), SKILLS);
assert.deepEqual(directoriesWithSkill(".agents/skills"), SKILLS);

const commands = fs.readdirSync(path.join(ROOT, ".claude/commands"))
  .filter((name) => name.endsWith(".md"))
  .map((name) => name.slice(0, -3))
  .sort();
assert.deepEqual(commands, COMMANDS);

for (const skill of SKILLS) {
  const adapter = fs.readFileSync(path.join(ROOT, ".agents/skills", skill, "SKILL.md"), "utf8");
  const metadata = fs.readFileSync(
    path.join(ROOT, ".agents/skills", skill, "agents", "openai.yaml"),
    "utf8",
  );
  if (skill !== "producer") {
    assert.match(adapter, new RegExp(`\\.claude/skills/${skill}/SKILL\\.md`));
  }
  assert.match(metadata, new RegExp(`\\$${skill}(?:\\s|\")`));
}

const readme = fs.readFileSync(path.join(ROOT, "README.md"), "utf8");
assert.match(readme, /5 focused video-editing skills/);
for (const skill of SKILLS) assert.match(readme, new RegExp(`\\.claude/skills/${skill}/SKILL\\.md`));
const documentedSkills = [...new Set(
  [...readme.matchAll(/\.claude\/skills\/([^/]+)\/SKILL\.md/g)].map((match) => match[1]),
)].sort();
assert.deepEqual(documentedSkills, SKILLS);

console.log("skill_surface.test.mjs: all assertions passed");
