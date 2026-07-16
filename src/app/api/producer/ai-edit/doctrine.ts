import path from "path";
import type { SurgicalEditLane, SurgicalEditScope } from "@/lib/producer/surgical-edit";

export const REPO_ROOT = path.resolve(process.cwd());
export const PRODUCER_SKILL = path.join(REPO_ROOT, ".claude", "skills", "producer", "SKILL.md");
export const FAILURE_LEDGER = path.join(
  REPO_ROOT, "scripts", "producer", "docs", "findings", "FAILURE_LEDGER.md",
);

const PRODUCER = path.join(REPO_ROOT, "scripts", "producer");
const FINDINGS = path.join(PRODUCER, "docs", "findings");

const LANE_DOCTRINE: Record<SurgicalEditLane, readonly string[]> = {
  cuts: [
    path.join(PRODUCER, "plan_lint.py"),
    path.join(PRODUCER, "transcript_cut_contract.py"),
    path.join(FINDINGS, "PRO_INTRO_ENVELOPE.md"),
  ],
  graphics: [
    path.join(PRODUCER, "plan_lint_visual.py"),
    path.join(PRODUCER, "graphics", "template_contract.py"),
    path.join(REPO_ROOT, "src", "lib", "producer", "comps-catalog.ts"),
    path.join(PRODUCER, "operator_intent_contract.py"),
    path.join(PRODUCER, "hook_contract.py"),
    path.join(FINDINGS, "FULL_SCREEN_MEANS_DELIVERY_PIXELS.md"),
    path.join(FINDINGS, "QC_CHECKLIST.md"),
  ],
  motion: [
    path.join(PRODUCER, "plan_lint_motion.py"),
    path.join(PRODUCER, "plan_lint_smooth.py"),
    path.join(PRODUCER, "intro_transition_contract.py"),
    path.join(PRODUCER, "operator_intent_contract.py"),
    path.join(PRODUCER, "hook_contract.py"),
  ],
  captions: [path.join(PRODUCER, "plan_lint.py"), path.join(PRODUCER, "plan_lint_visual.py")],
  broll: [
    path.join(PRODUCER, "plan_lint_broll.py"),
    path.join(FINDINGS, "ASSET_AVAILABILITY_IS_NOT_SELECTION.md"),
  ],
  audio: [
    path.join(PRODUCER, "plan_lint_audio.py"),
    path.join(FINDINGS, "AUDIO_AUTHORITY_AT_NLE_HANDOFF.md"),
  ],
  music: [path.join(PRODUCER, "plan_lint_audio.py")],
  reframe: [path.join(PRODUCER, "plan_lint_reframe.py"), path.join(FINDINGS, "FACE_ANCHORED_RECOMPOSE.md")],
};

export function doctrinePaths(scope: SurgicalEditScope): string[] {
  return [
    PRODUCER_SKILL,
    FAILURE_LEDGER,
    ...new Set(scope.lanes.flatMap((lane) => LANE_DOCTRINE[lane])),
  ];
}

export function doctrinePromptLines(scope: SurgicalEditScope): string[] {
  return doctrinePaths(scope).map((file) => `- ${file}`);
}
