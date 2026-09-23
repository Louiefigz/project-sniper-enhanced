/** Preserve a selected long-form study's entire event sequence and available reviewed grammar. */
import { existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { pythonInterpreter, SCRIPTS_DIR } from "@/app/api/_lib/spawn-python";
import { validStoredReferenceDecision } from "@/app/api/_lib/reference-decision";
import type { ResolvedReferenceStudy } from "@/app/api/producer/auto-edit/stream";
import { objectValue } from "@/lib/producer/contracts/validation";
import { canonicalJson } from "./auto-edit-hash";
import { strategyFile, type StrategyFilePin } from "./reference-strategy-library";
import { longformInputPin } from "./longform-strategy-packet";

function savedBindings(study: ResolvedReferenceStudy, evidence: StrategyFilePin[]) {
  const file = path.join(path.dirname(study.deepStudyPath), "reference_catalog_matches.json");
  if (!existsSync(file)) return null;
  const held = strategyFile(file), value = objectValue(JSON.parse(held.text), "saved reference matches");
  const references = value.references;
  if (!Array.isArray(references) || !references.some(row => row?.id === study.id
      && evidence.some(pin => pin.path === row.path && pin.sha256 === row.sha256))) {
    throw new Error("Saved matches do not bind this selected reference study");
  }
  const raw = execFileSync(pythonInterpreter(), [path.join(SCRIPTS_DIR, "producer/graphics/reference_reuse_cli.py"), "check-study", file],
    { encoding: "utf8", timeout: 45_000, maxBuffer: 16 * 1024 * 1024 });
  const checked = objectValue(JSON.parse(raw), "checked study matches");
  if (checked.status !== "study-bindings-current" || checked.sha256 !== held.pin.sha256) throw new Error("Saved reference matches changed");
  const pins = Object.entries(objectValue(checked.inputPins, "study match inputs")).map(([file, hash]) => {
    const pin = longformInputPin(file);
    if (pin.sha256 !== hash) throw new Error("Saved study match input changed");
    return pin;
  });
  return { text: held.text, pins: [held.pin, ...pins], blockedMatches: checked.blockedMatches };
}

function savedPack(study: ResolvedReferenceStudy, deep: StrategyFilePin) {
  const file = path.join(path.dirname(study.deepStudyPath), "reference_style_pack.json");
  if (!existsSync(file)) return null;
  const pack = strategyFile(file), content = objectValue(JSON.parse(pack.text), "reference style pack");
  const provenance = objectValue(content.provenance, "style pack provenance");
  if (content.referenceId !== study.id || provenance.deepStudyHash !== deep.sha256) {
    throw new Error("Reference style pack is stale or belongs to another reference");
  }
  return pack;
}

/** Raw per-frame arrays stay on disk; every event, word timing and interpretation is retained. */
export function nativeReferenceInputs(study?: ResolvedReferenceStudy) {
  const files: Record<string, string> = {}, pins: StrategyFilePin[] = [];
  if (!study) return { files, pins, selected: null };
  const profile = strategyFile(study.profilePath), deep = strategyFile(study.deepStudyPath);
  pins.push(profile.pin, deep.pin);
  const profileValue = objectValue(JSON.parse(profile.text), "reference profile");
  if (profileValue.referenceId !== study.id) throw new Error("Selected profile identity changed");
  const source = objectValue(profileValue.source, "reference source");
  if (typeof source.video !== "string" || typeof source.sha256 !== "string") throw new Error("Reference source identity missing");
  const video = longformInputPin(source.video);
  if (video.sha256 !== source.sha256) throw new Error("Selected reference video changed after study");
  pins.push(video);
  const value = objectValue(JSON.parse(deep.text), "deep study");
  if (value.video !== source.video || !Array.isArray(value.events)) throw new Error("Deep study does not match the selected source");
  const { signals: _signals, ...interpretable } = value; void _signals;
  files["SELECTED-REFERENCE-PROFILE.json"] = profile.text;
  files["SELECTED-REFERENCE-STUDY.json"] = canonicalJson({ ...interpretable,
    rawSignals: { path: deep.pin.path, sha256: deep.pin.sha256, omitted: ["signals"] } });
  const decision = strategyFile(path.join(path.dirname(study.deepStudyPath), "reference.json"));
  const choice: unknown = JSON.parse(decision.text);
  if (!validStoredReferenceDecision(choice, study.id) || choice.mode !== study.mode) {
    throw new Error("Selected reference decision changed or is invalid");
  }
  pins.push(decision.pin); files["SELECTED-REFERENCE-DECISION.json"] = decision.text;
  for (const file of study.representativeFrames) pins.push(longformInputPin(file));
  const pack = savedPack(study, deep.pin), packAvailable = pack !== null;
  if (pack) { pins.push(pack.pin); files["SELECTED-REFERENCE-PACK.json"] = pack.text; }
  const bindings = savedBindings(study, [profile.pin, deep.pin]);
  if (bindings) { files["SELECTED-REFERENCE-MATCHES.json"] = bindings.text; pins.push(...bindings.pins); }
  return { files, pins, selected: { id: study.id, title: study.title,
    eventCount: value.events.length, eventsTruncated: false, packAvailable, catalogBindingsAvailable: bindings !== null,
    catalogBlockedMatches: bindings?.blockedMatches ?? [],
    representativeFrames: study.representativeFrames,
    editorialStudy: packAvailable ? "saved-pack-requires-current-evidence-review" : "whole-video-editorial-study-required",
    verifiedMimicQualified: false } };
}

/** Keep the Long request entry strict while sharing current-reference pins with Shorts. */
export function longformReferenceInputs(study?: ResolvedReferenceStudy) {
  if (study && study.mode !== "longform") throw new Error("Selected reference mode must remain longform");
  return nativeReferenceInputs(study);
}
