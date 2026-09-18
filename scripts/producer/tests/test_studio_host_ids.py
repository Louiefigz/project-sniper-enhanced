"""Opening a freshly generated Studio host must not rewrite its source."""
import json
import re
import shutil
import subprocess
import unittest
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path

from _common import *  # noqa: F401,F403
from studio.project_writer import ReviewBase, ReviewClip, build_index_html

_CLI = Path(__file__).resolve().parents[3] / "templates/motion/node_modules/hyperframes/dist/cli.js"
_EXCLUDED = {"script", "style", "template", "meta", "link", "noscript", "base"}
# Execute only the pinned parser and persistence functions, not the CLI entry
# point. Disk writes are replaced by a counter; no server or render is started.
_PINNED_PROBE = r"""
// Only the installed persistence declaration runs; never evaluate the CLI bootstrap.
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

function readSource(file) {
  const stat = fs.lstatSync(file);
  if (!stat.isFile() || stat.size > 16 * 1024 * 1024 || fs.realpathSync(file) !== file) {
    throw new Error("Unsupported installed SDK source");
  }
  return fs.readFileSync(file, "utf8");
}

function one(rows, label) {
  if (rows.length !== 1) throw new Error("Missing or ambiguous " + label);
  return rows[0];
}

function nodes(root) {
  const output = [], pending = [root];
  while (pending.length) {
    const node = pending.pop();
    if (!node || typeof node.type !== "string") continue;
    output.push(node);
    pending.push(...Object.values(node).flat().filter(value => value && typeof value === "object"));
  }
  return output;
}

function freeNames(fn) {
  const all = nodes(fn), bound = new Set([fn.id.name, ...fn.params.map(param => param.name)]);
  all.filter(node => node.type === "VariableDeclarator").forEach(node => bound.add(node.id.name));
  all.filter(node => node.type === "CatchClause").forEach(node => bound.add(node.param.name));
  const ignored = new Set(all.flatMap(node => {
    if (node.type === "MemberExpression" && !node.computed) return [node.property];
    if (node.type === "Property" && !node.computed) return [node.key];
    return [];
  }));
  return new Set(all.filter(node => node.type === "Identifier" && !ignored.has(node)
    && !bound.has(node.name)).map(node => node.name));
}

function persistence(tree) {
  const fn = one(tree.body.filter(node => node.type === "FunctionDeclaration"
    && node.id.name === "persistHfIdsIfNeeded"), "installed persistence function");
  if (fn.async || fn.generator || fn.params.length !== 2
      || fn.params.some(param => param.type !== "Identifier")) throw new Error("Unexpected persistence parameters");
  const init = fn.body.body[0]?.declarations?.[0]?.init;
  if (init?.type !== "CallExpression" || init.callee.type !== "Identifier"
      || init.arguments.length !== 1 || init.arguments[0].name !== fn.params[1].name) {
    throw new Error("Unexpected original normalizer call");
  }
  const normalizer = init.callee.name, free = freeNames(fn);
  one(tree.body.filter(node => node.type === "FunctionDeclaration" && node.id.name === normalizer),
    "called normalizer declaration");
  const imports = tree.body.filter(node => node.type === "ImportDeclaration"
    && ["fs", "node:fs"].includes(node.source.value)).flatMap(node => node.specifiers);
  const aliases = ["readFileSync", "writeFileSync"].map(name => one(imports.filter(node =>
    node.type === "ImportSpecifier" && node.imported.name === name && free.has(node.local.name)),
  "persistence " + name).local.name);
  const allowed = [normalizer, ...aliases, "console"];
  if (free.size !== allowed.length || [...free].some(name => !allowed.includes(name))) {
    throw new Error("Unexpected persistence dependency");
  }
  return { fn, normalizer, aliases };
}

const cli = fs.realpathSync(process.argv[1]);
const cliPackage = JSON.parse(readSource(path.resolve(path.dirname(cli), "../package.json")));
const project = createRequire(path.join(process.argv[2], "package.json"));
const parserPath = fs.realpathSync(project.resolve("@hyperframes/parsers/package.json"));
const parserPackage = JSON.parse(readSource(parserPath));
if (cliPackage.name !== "hyperframes" || cliPackage.version !== "0.8.31"
    || parserPackage.name !== "@hyperframes/parsers" || parserPackage.version !== cliPackage.version
    || parserPackage.exports?.["./hf-ids"]?.import !== "./dist/hfIds.js") {
  throw new Error("The probe requires the reviewed matching 0.8.31 parser export");
}
const requireParser = createRequire(parserPath);
const { parse } = requireParser("acorn");
const parserFile = path.resolve(path.dirname(parserPath), parserPackage.exports["./hf-ids"].import);
readSource(parserFile);
const { ensureHfIds } = await import(pathToFileURL(parserFile).href);
if (typeof ensureHfIds !== "function") throw new Error("Missing official hf-ids function");
const source = readSource(cli), tree = parse(source, { ecmaVersion: "latest", sourceType: "module" });
const { fn, normalizer, aliases } = persistence(tree);
const input = fs.readFileSync(0, "utf8");
let writes = 0;
const scope = { input, [normalizer]: ensureHfIds,
  [aliases[0]]: (file, encoding) => {
    if (file !== "unused" || encoding !== "utf-8") throw new Error("Unexpected TEST read");
    return input;
  },
  [aliases[1]]: (file, value, encoding) => {
    if (file !== "unused" || typeof value !== "string" || encoding !== "utf-8") throw new Error("Unexpected TEST write");
    writes += 1;
  },
  console: { warn: message => { throw new Error(message); } } };
vm.createContext(scope);
vm.runInContext(source.slice(fn.start, fn.end)
  + '\nresult = persistHfIdsIfNeeded("unused", input);', scope, { timeout: 3000 });
process.stdout.write(JSON.stringify({ writes, serialized: scope.result }));
"""


class _HostParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_body = False
        self.hosts: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "body":
            self.in_body = True
        elif self.in_body and tag not in _EXCLUDED:
            self.hosts.append(dict(attrs))

    def handle_endtag(self, tag: str) -> None:
        if tag == "body":
            self.in_body = False


def _fixture() -> tuple[ReviewBase, list[ReviewClip]]:
    base = ReviewBase(1920, 1080, 12.0, 30.0, "assets/base.mp4", True)
    clip = ReviewClip(
        "gfx-01", "gfx-01-statement-card", "statement-card", "compositions/one.html",
        {"text": "Aaron's \"quality\" & <speed>"}, 1.0, 3.0, 3.0,
        1, 10, 1920, 1080, "own-screen", "thesis", None, ())
    second = replace(clip, slot_id="gfx-02", instance_id="gfx-02-statement-card")
    return base, [clip, second]


def _hosts(source: str) -> list[dict]:
    parser = _HostParser()
    parser.feed(source)
    return parser.hosts


class StudioHostIdTests(unittest.TestCase):
    def test_every_eligible_body_element_has_a_unique_id(self) -> None:
        base, clips = _fixture()
        hosts = _hosts(build_index_html(base, clips, "Review", True))
        self.assertEqual(len(hosts), 5)
        ids = [host["data-hf-id"] for host in hosts]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertTrue(all(re.fullmatch(r"hf-[a-z0-9-]+", value) for value in ids))

    def test_ids_survive_copy_timing_and_audio_changes(self) -> None:
        base, clips = _fixture()
        before = _hosts(build_index_html(base, clips, "Review", False))
        changed = [replace(clip, spec={"text": "Revised"}, out_start=2.0) for clip in clips]
        after = _hosts(build_index_html(replace(base, has_audio=False), changed, "Other", True))
        identities = {host["id"]: host["data-hf-id"] for host in before}
        self.assertTrue(all(identities[host["id"]] == host["data-hf-id"] for host in after))

    def test_raw_json_contract_is_preserved(self) -> None:
        base, clips = _fixture()
        source = build_index_html(base, clips, "Review", False)
        values = re.findall(r"data-variable-values='([^']*)'", source)
        self.assertEqual(len(values), len(clips))
        self.assertEqual([json.loads(value) for value in values], [clip.spec for clip in clips])
        self.assertNotIn("&quot;", source)

    def test_base_video_is_a_timed_clip_without_an_extra_wrapper(self) -> None:
        base, clips = _fixture()
        source = build_index_html(base, clips, "Review", False)
        video = next(host for host in _hosts(source) if host["id"] == "review-base")
        self.assertIn("clip", video["class"].split())
        self.assertEqual(video["data-start"], "0")
        self.assertEqual(video["data-duration"], "12")
        self.assertEqual(video["data-track-index"], "0")
        self.assertRegex(source, r'<div id="review-root"[^>]*>\s*<video id="review-base"')

    @unittest.skipUnless(shutil.which("node") and _CLI.is_file(), "pinned CLI and Node required")
    def test_pinned_initial_preview_does_not_write_but_missing_id_does(self) -> None:
        base, clips = _fixture()
        source = build_index_html(base, clips, "Review", False)
        for text, expected in [(source, 0), (source.replace(' data-hf-id="hf-review-root"', ''), 1)]:
            with self.subTest(expected_writes=expected):
                result = subprocess.run(
                    ["node", "--input-type=module", "-e", _PINNED_PROBE, str(_CLI),
                     str(Path(__file__).resolve().parents[3])], input=text,
                    capture_output=True, text=True, timeout=5, check=True)
                row = json.loads(result.stdout)
                self.assertEqual(row["writes"], expected)
                self.assertIn("&quot;", row["serialized"])


if __name__ == "__main__":
    unittest.main()
