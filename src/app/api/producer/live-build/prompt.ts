import path from "node:path";
import type { LiveBuildPreflight } from "./preflight";
import { liveBuildJournalPath } from "./state";

function doctrineLines(input: LiveBuildPreflight): string[] {
  return Object.entries(input.doctrineFiles).map(
    ([logical, filePath]) => `- ${logical}: ${filePath}`,
  );
}

function repairLines(input: LiveBuildPreflight, resume: boolean): string[] {
  if (!resume || !input.qcFailure) return [];
  return [
    "Exact failed-candidate QC repair contract:",
    `- Rejected candidate fingerprint: ${input.qcFailure.candidateFingerprint}`,
    `- Critic lens: ${input.qcFailure.lens ?? "deterministic"}`,
    `- Material issues JSON: ${JSON.stringify(input.qcFailure.materialIssues)}`,
    `- Evidence paths: ${input.qcFailure.evidencePaths.join(", ")}`,
    "- Inspect the cited evidence and current readback. Repair only the failed operations or lane; preserve approved work and do not rebuild the candidate wholesale.",
    "- After the repair, read the affected region and final timeline back. The controller will export and rerun the entire QC gate.",
    "",
  ];
}

export function buildLiveBuildPrompt(
  input: LiveBuildPreflight,
  resume: boolean,
): string {
  const journal = liveBuildJournalPath(input.dir);
  return [
    "You are the retained PRODUCER build session. Execute the already-approved edit directly in Palmier Pro through MCP.",
    "Before any other action, invoke the producer skill. Then read the pinned Producer doctrine listed below; pinned copies outrank mutable repository text.",
    ...doctrineLines(input),
    "",
    `Approved plan: ${input.planPath}`,
    `Approved plan SHA-256: ${input.planHash}`,
    `Asset manifest: ${input.manifestPath}`,
    `Producer directory: ${input.dir}`,
    `Operation journal: ${journal}`,
    `Bound Palmier project id: ${input.projectId}`,
    `Bound Palmier project path: ${input.projectPath}`,
    `Bound Palmier timeline id: ${input.timelineId}`,
    `Bound timeline readback fingerprint: ${input.timelineFingerprint}`,
    "",
    "Authority contract:",
    "- The approved plan is the editorial determinism boundary. Execute it faithfully; do not redesign it or add adjacent improvements.",
    "- The controller already forked and activated the exact candidate. Project/timeline navigation tools are intentionally unavailable.",
    "- Call get_timeline before the first mutation. If its timeline id differs from the bound id, stop without mutation.",
    "- Timeline positions are integer project frames. Source trim positions are seconds. Never multiply source seconds by fps.",
    "- Reach the first visible mutation promptly. Do not repeat planning or research already completed by the approved plan.",
    "- Batch independent same-tool entries by lane/region (normally 10–25 entries) to control latency. Keep risky cuts, imports, and dependent-id operations separate.",
    "- Use returned clip/media ids exactly; do not invent identifiers. Read back after each risky or dependency-producing batch, not after every harmless text row.",
    "- After each mutation result, update your local timeline model. Re-read get_transcript after remove_words because word indexes shift.",
    "- Do not silently omit or approximate a requested lane. If Palmier cannot represent it, report the exact unsupported operation and continue only with independent approved lanes.",
    "- Automatic transitions have no proved native primitive. Do not disguise keyframes or a baked visual as an exact transition.",
    "",
    "Connected editable vocabulary:",
    "- Imports/cuts: import_media, add_clips, insert_clips, split_clips, move_clips, remove_clips, ripple_delete_ranges, remove_words, remove_silence.",
    "- Graphics: add_texts/update_text for native text; import_media + add_clips for already-rendered alpha assets; apply_layout and transform properties for editable placement.",
    "- Motion/framing: set_clip_properties and clip-relative set_keyframes.",
    "- Captions/color/audio: add_captions, apply_color, denoise_audio, volume keyframes, and imported music where the approved plan names real media.",
    "- QC/readback: get_timeline, get_transcript, inspect_timeline. The controller—not this session—exports the exact candidate for QC.",
    "",
    ...repairLines(input, resume),
    resume
      ? `This is a resumed turn. Read ${journal}, then reconcile it with current Palmier readback. Never replay an operation already verified in the current timeline ancestry.`
      : "This is the first live-build turn. Begin from the exact parent readback above.",
    "Execute cuts first, then downstream graphics/assets, motion/framing, captions/color/audio, respecting plan dependencies. Do not spend a second turn explaining what you could execute: execute it.",
    "Finish with get_timeline readback and a concise result listing applied lanes, unsupported operations, and the next safe operation if work remains.",
    `Do not read outside ${path.dirname(input.planPath)}, the pinned doctrine, manifest evidence, and repository Producer guidance needed to execute this plan.`,
  ].join("\n");
}
