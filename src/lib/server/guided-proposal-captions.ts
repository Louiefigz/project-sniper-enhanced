import { canonicalJsonSha256 } from "./auto-edit-hash";
import { enumValue, exactKeys, objectValue, sha256 } from "@/lib/producer/contracts/validation";
import { parseTreatmentProposalV5, type TreatmentProposalV5 } from "@/lib/producer/contracts/treatment-proposal-v5";
import { DIRECTIVE_WORDS, resolveLanes, SCOPES } from "@/lib/producer/intent-presets";

const AUTHORITY_FIELDS = ["captionsTrack", "captionStyles", "captionCorrectionLedger", "captionChapters", "dialogueCaptionAuthority"];
export const GUIDED_CAPTION_CONFIG_FILES = ["scripts/producer/producer_config.py",
  "scripts/producer/captions/caption_plan_pipeline.py", "scripts/producer/captions/caption_grouping.py"] as const;

/** The selected renderer resolves these named presets from its captured Producer configuration. */
export const GUIDED_CAPTION_POLICY = Object.freeze({
  schemaVersion: 1,
  scope: "explicit-pinned-producer-caption-presets-not-rendered-or-listened-proof",
  coverage: "all-kept-transcript-words", suppression: "none",
  presets: [
    { id: "producer-config-line-v1", defaultPolicy: "line" },
    { id: "producer-config-karaoke-v1", defaultPolicy: "karaoke" },
  ],
  typography: "captured-producer-config-and-caption-style-resolver",
  customTypography: false, customPlacement: false, textCorrections: false,
});

/** Bind the actual captured preset/style/group defaults; no live defaults are supplied on old evidence readback. */
export function guidedCaptionPolicy(configuration: Array<{ name: string; sha256: string }>) {
  if (configuration.length !== GUIDED_CAPTION_CONFIG_FILES.length) throw new Error("Caption configuration closure is incomplete");
  for (const [index, row] of configuration.entries()) {
    exactKeys(row, ["name", "sha256"], ["name", "sha256"], "caption configuration source");
    if (row.name !== GUIDED_CAPTION_CONFIG_FILES[index]) throw new Error("Caption configuration closure is reordered or unexpected");
    sha256(row.sha256, "caption configuration SHA");
  }
  return { ...structuredClone(GUIDED_CAPTION_POLICY), configuration: structuredClone(configuration) };
}

function assertCaptionDestination(plan: Record<string, unknown>): void {
  const target = objectValue(plan.target, "caption target");
  const size = target.mode === "short" ? [1080, 1920] : target.mode === "longform" ? [1920, 1080] : [];
  if (!size.length || target.width !== size[0] || target.height !== size[1]) {
    throw new Error("Caption presets require an exact1080x1920 short or1920x1080 longform destination; no inferred resizing");
  }
  const scope = Object.hasOwn(target, "scope") ? enumValue(target.scope, SCOPES, "accepted caption scope")
    : target.treatment == null ? "produced"
      : enumValue(target.treatment, ["clean-cut", "produced"], "accepted treatment") === "clean-cut" ? "trim" : "produced";
  const lanes = target.lanes == null ? {} : objectValue(target.lanes, "accepted caption lane ownership");
  const captions = enumValue(Object.hasOwn(lanes, "captions") ? lanes.captions : "auto", DIRECTIVE_WORDS, "accepted caption directive");
  if (resolveLanes(scope, { captions }).captions !== "auto") {
    throw new Error("Accepted intent does not assign captions to the system; an explicit treatment-intent revision is required before caption authoring");
  }
}

function assertFreshCaptionLane(plan: Record<string, unknown>): void {
  if (AUTHORITY_FIELDS.some((name) => Object.hasOwn(plan, name))) {
    throw new Error("Existing caption authority requires an explicit scoped caption revision; it cannot be replaced by a full-program preset");
  }
  if (Object.hasOwn(plan, "captions")) {
    const captions = objectValue(plan.captions, "inherited captions");
    exactKeys(captions, ["burn"], ["burn"], "inherited captions");
    if (captions.burn !== false) throw new Error("Existing caption burn intent cannot be replaced by a new full-program preset");
  }
  if (Array.isArray(plan.chapters) ? plan.chapters.length : plan.chapters) {
    throw new Error("Legacy output-time chapters need source-bound captionChapters before caption authoring");
  }
}

/** Pure unapproved plan projection. Source timing/coverage and font/media authority remain renderer obligations. */
export function applyGuidedCaptionOperations(plan: Record<string, unknown>, proposal: TreatmentProposalV5): Record<string, unknown> {
  const current = parseTreatmentProposalV5(proposal);
  const requested = current.operations.filter((operation) => operation.type === "captions-full-program");
  if (!requested.length) return structuredClone(plan);
  const presets = new Set(requested.map((operation) => operation.captions!.preset));
  if (presets.size !== 1) throw new Error("Full-program caption clauses request conflicting presets; no last-writer-wins resolution");
  assertCaptionDestination(plan);
  assertFreshCaptionLane(plan);
  const preset = GUIDED_CAPTION_POLICY.presets.find((row) => row.id === requested[0].captions!.preset);
  if (!preset) throw new Error("Caption preset is absent from the declared policy");
  const candidate = { ...structuredClone(plan), captions: { burn: true },
    captionsTrack: { schemaVersion: 1, source: "kept-transcript", defaultPolicy: preset.defaultPolicy, groups: [] } };
  const { captions: _before, ...before } = plan;
  const { captions: _after, captionsTrack: _track, ...after } = candidate;
  void _before; void _after; void _track;
  if (canonicalJsonSha256(before) !== canonicalJsonSha256(after)) throw new Error("Caption projection changed a non-caption plan field");
  return candidate;
}
