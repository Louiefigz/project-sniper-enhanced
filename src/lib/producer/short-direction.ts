/** Editorial request, independent of the legacy pacing/style grammars. */
export interface ShortDirectionRequest {
  selection: "auto" | "requested";
  request?: string;
  supportingVideo: "source-first" | "off";
  mediaPolicy?: ShortMediaPolicy;
}

export interface ShortMediaPolicy {
  placement: "auto" | "off";
  sources: "provided-only" | "local-only" | "public-web";
}

/** Resolve older requests without rewriting their persisted identities. */
export function shortMediaPolicy(request: ShortDirectionRequest): ShortMediaPolicy {
  return request.mediaPolicy ?? { placement: request.supportingVideo === "off" ? "off" : "auto", sources: "local-only" };
}

/** A new style request must retain the operator's existing source restrictions. */
export function shortDirectionForStyle(request: string, current = AUTOMATIC_SHORT_DIRECTION): ShortDirectionRequest {
  return { selection: "requested", request, supportingVideo: current.supportingVideo,
    ...(current.mediaPolicy ? { mediaPolicy: current.mediaPolicy } : {}) };
}

function parseMediaPolicy(value: unknown, supportingVideo: unknown): ShortMediaPolicy | undefined {
  if (value === undefined) return undefined;
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid Short media policy");
  const row = value as Record<string, unknown>;
  if (Object.keys(row).some(key => !["placement", "sources"].includes(key))
      || typeof row.placement !== "string" || !["auto", "off"].includes(row.placement)
      || typeof row.sources !== "string" || !["provided-only", "local-only", "public-web"].includes(row.sources)
      || (supportingVideo === "off" && row.placement !== "off")) throw new Error("Invalid or conflicting Short media policy");
  return { placement: row.placement as ShortMediaPolicy["placement"], sources: row.sources as ShortMediaPolicy["sources"] };
}

export const AUTOMATIC_SHORT_DIRECTION: ShortDirectionRequest = {
  selection: "auto", supportingVideo: "source-first",
};

/** Suggestions locate reference mechanics; they are not whole-video presets. */
export const SHORT_DIRECTION_SUGGESTIONS = [
  "Nate Herk — visual storytelling with a developing example",
  "Presenter-led — close portrait and centered karaoke captions",
  "Formula or comparison — show the current version and the improvement",
  "Screen demonstration — focus on the actual operation and result",
] as const;

/** The complete answer is planned before individual assets or technical checks. */
const SHORT_NARRATIVE_INSTRUCTIONS = `Start with a source-supported viewer question → development → payoff before choosing individual visual inserts. Retain enough of the source to answer that question and carry the same identifiable example through its development. For a complete native Short, author strategy.story against the existing pacing beats, asset-use decisions, actual visual targets and reading holds. Label component-only tests explicitly. Component, logo, capture and export checks qualify only those parts; they do not establish a complete editorial example.
For standalone assembly, establish what a new viewer needs to know, why the subject matters to them, what is being tried or learned, and how the retained explanation earns its ending. Determine length from that complete idea within the user's current duration limit. A 20–30-second cut is not preferable to a fuller explanation merely because it is shorter; a longer allowance is not a target to fill. Restore missing context or reasoning before tightening redundancy. Respect segment-only and cleanup scope: this does not authorize restructuring an excerpt or expanding a fixed requested range. A hook, caption or diagram cannot supply an essential spoken claim that the edit removed.`;

/** A canonical fill still needs the Director's source-bound editorial selection. */
const SHORT_HOOK_INSTRUCTIONS = `Use the canonical Script Director hook templates through its full selection workflow before scene planning: viewer/payoff/awareness, format alternatives, a chosen template and rejected alternatives, multiple source-bound fills, condition audit and an independent critique. A valid local template fill or matching catalog hash is not editorial approval. Reject generic update labels and numbers whose implication does not explain why the audience should care. Pair the title with the actual opening audio and first visual: all three must open the same source-supported question, and the retained story must answer it.
Choose the title and subtitle hierarchy from the selected reference and actual shot geometry. A backed title above the presenter and centered karaoke captions are available treatments, not a requirement to give every scene the same multiline red card and opaque black caption band. Preserve readable face, gesture and explanatory detail, and give the opening copy a deliberate removal cue.`;

/** Match the representation to the teaching moment before deciding which assets to acquire. */
const SHORT_VISUAL_STORYTELLING_INSTRUCTIONS = `For each beat, choose the teaching purpose and visual representation BEFORE asset scouting or capture selection. A conceptual overview may be clearest through a familiar physical object, cartoon metaphor or simple diagram; a procedure needs the relevant real interface and visible actions; a factual claim needs appropriate observed evidence. Presenter performance can carry a beat when an added visual would not help. Make this choice from the complete spoken point, audience understanding and story, not a keyword-to-asset rule or a whole-Short preset.
For produced visual treatment, actively develop the important showable actions and relationships. Downloading a skill can become a visible artifact → download → setup → attempted task → outcome sequence when the speech supports those beats. Use an identified real image, scrolling capture or interface when available and permitted; otherwise use a clearly illustrative HyperFrames representation without inventing a product or historical result. Choose the useful subset of that example, not a mandatory five-step sequence. Keywords on plain panels, caption animation and camera movement alone do not fulfill a requested visual explanation. A whole-clip 'personal account' or 'performance carries it' rationale cannot replace beat-specific decisions about relevant entities and actions. Keep purposeful presenter holds where they earn attention; do not impose a B-roll quota or cut interval.
For example, an API key in a high-level overview can be a cartoon key unlocking access to a service. Show the familiar object's action and map it to the concept being explained; a credential string is useful when teaching the actual configuration step. This is a candidate analogy, not an automatic treatment for every mention of API key. Record what the analogy explains and where it stops: the key illustration communicates access, not proof of secure storage, successful authentication or a real product result. Use a masked/example field for an illustrative tutorial; claim a real action/result only when its source supports it.
Record the teaching purpose and selection reason in strategy.scenes[].viewingNeed; describe the representation, object-to-concept mapping and any claim limit in paneJobs; develop it through before/action/result. Carry the same identifiable object through those changes. When moving from overview to tutorial, make the connection from the metaphor to the real field explicit. Bind the actual targets in visibleIds and strategy.story, and budget recognition, action and comprehension holds through the existing speech-bound pacing record. A passing mention can use a brief cue or remain on the presenter.
A locally authored metaphor or diagram belongs to an explanatory-comparison story job in an explanatory scene; it is not a real-artifact or real-operation job. If it uses an acquired image/video, retain its actual asset-use/origin decision with illustrative purpose. Choose source acquisition after the representation: a useful metaphor does not require a website recording, and a real tutorial must not become invented UI. Respect enabled lanes and source restrictions; conceptual illustration does not authorize generated media or remote calls. At review, check whether the visual makes the spoken relationship easier to understand and whether the analogy introduces a false inference.`;

/** One editorial rhythm governs the enabled lanes; this is not a speed preset. */
const SHORT_PACING_INSTRUCTIONS = `Establish the whole-Short rhythm from the retained script and actual source delivery before choosing individual shot lengths. Read the complete retained passage, listen to the performance and inspect word timing, phrase lengths, pauses, emphasis, idea density and the setup-to-payoff arc. Words per minute alone cannot establish energy or comprehension. Record the overall rhythm and speech-bound local changes in the source-bound strategy rationale, including deliberate pauses and their purpose; do not infer exact cadence from sampled reference stills.
Coordinate cuts, caption phrase groups and word highlights, title lifetime, supporting-shot holds, visual developments and motion duration with that same rhythm. Faster delivery calls for quicker, simpler visual beats; calmer delivery calls for more sustained, restrained development. Adapt the reference mechanics to this performance. A local acceleration or deliberate pause must be motivated by the script and reflected across the enabled lanes. Keep captions locked to actual kept words; never make them race ahead to create energy. Respect disabled/operator-owned lanes and current audio permissions; coordinate music/SFX only when already requested and supported.
For each beat, record the spoken cue, main attention target, entrance/action/result, readable hold and exit reason. If a screen cannot be understood within that beat, crop, simplify or split its information before planning a deliberate longer beat. Do not force a universal one- or three-second cut, multiply every duration by a fixed factor, or accelerate source dialogue merely to match a visual preset. Source asset length does not determine on-screen duration. Reassess dependent visuals and captions when the retained speech or its timing changes. When retiming a reveal, move its state labels and other dependent cues with the actual payload; add native expectations at the old/new-state boundary so old content cannot momentarily acquire a new label.
For native assembly, run scripts/producer/native-short.ts measure on the canvas plan. Author strategy.schemaVersion 3 and strategy.pacing using native-short-pacing.ts: bind the returned timingHash and visualHash, explain overall rhythm and every enabled lane, partition the full clock into speech-bound beats, and choose minimum viewing budgets for title, text and custom inserts. These budgets are editorial decisions, not values to copy from the available duration. Record timing-and-transcript-only when source listening has not occurred. Revise the pacing plan when source or visuals change; do not merely refresh hashes to silence a stale-plan error.
Review the complete encoded Short with sound at normal playback speed for the promised answer, example continuity, overall rhythm, local handoffs and phone-size readability. Check each insert's role: identity or page context must not be presented as a demonstrated operation or achieved result. Frame/timing validity is not proof of pacing or narrative quality; record any unperformed listening or playback review.`;

/** Source diagnosis precedes processing; both routes consume the same audio engine. */
const SHORT_AUDIO_INSTRUCTIONS = `Before assembly, assess the retained dialogue and cut boundaries for mono/dead channels, local left/right dropouts, hum/noise, room reverb and clip-to-clip voice level changes. Keep the original recording. Reuse long-form channel normalization, installed cleanup presets, ramped output-time gain and final loudness/peak checks; never create a separate Shorts DSP chain. Measure the whole mix and its sections. A level difference may be intentional emphasis or a whisper: diagnose it before writing gain windows. Do not infer room-echo removal from denoising or a passing loudness number.
When channels are separate active microphones, compare them per retained speaker/passage before collapsing them together. Centering both microphones fixes stereo balance but can preserve noise and bleed from the unused mic. Route or attenuate the appropriate source channel when supported, preserving intentional replies and the original source; then assess cleanup at matched speech level. A narrow-tone or loudness pass does not establish removal of intermittent appliance noise.
When processing is justified, author a source-specific audioFinishing rationale with installed audioEnhance and/or bounded audioGain decisions. Match enhancement intent from a prepared app request exactly; revise that request through its normal preparation path if the source assessment requires a different preset. Apply cleanup and gain before whole-program mastering, preserve exact source/caption timing and the final syllable, and recheck the encoded output including reused AAC. Save the actual measurements and unresolved listening issues. Unavailable dereverberation models, music or SFX must not be silently substituted. Technical checks never imply listening approval.
Treat ASR timestamps as source-navigation pointers, not safe phonetic cut boundaries. Compare the actual assembled speech to its captions at every seam, opening and ending. Restore a complete phrase when a micro-cut damages a word or changes what is said. Resolve known clipped syllables, missing words and caption/audio contradictions before final picture rendering and handoff; a note asking the user to check a known broken join is not a repair. Record unavailable listening honestly without promoting technical checks to editorial acceptance.`;

/** Reject incomplete requests rather than quietly choosing a different style. */
export function parseShortDirection(value: unknown, mode: unknown): ShortDirectionRequest | undefined {
  if (value === undefined) return undefined;
  if (mode !== "short") throw new Error("shortDirection is valid only for short edits");
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("shortDirection must be an object");
  const row = value as Record<string, unknown>;
  if (Object.keys(row).some((key) => !["selection", "request", "supportingVideo", "mediaPolicy"].includes(key))
      || typeof row.selection !== "string" || !["auto", "requested"].includes(row.selection)
      || typeof row.supportingVideo !== "string" || !["source-first", "off"].includes(row.supportingVideo)) throw new Error("Invalid shortDirection selection or supportingVideo policy");
  const policy = parseMediaPolicy(row.mediaPolicy, row.supportingVideo);
  const media = policy === undefined ? {} : { mediaPolicy: policy };
  if (row.selection === "auto") {
    if (row.request !== undefined) throw new Error("Automatic direction cannot discard a supplied style request");
    return { selection: "auto", supportingVideo: row.supportingVideo as ShortDirectionRequest["supportingVideo"], ...media };
  }
  if (typeof row.request !== "string" || !row.request.trim() || row.request.length > 800 || row.request.includes("\0")) {
    throw new Error("Requested Short direction needs 1–800 characters");
  }
  return { selection: "requested", request: row.request.trim(), supportingVideo: row.supportingVideo as ShortDirectionRequest["supportingVideo"], ...media };
}

/** Shared planning policy for the conversational and optional controller routes. */
export function shortDirectionInstructions(value?: ShortDirectionRequest): string {
  const request = value ?? AUTOMATIC_SHORT_DIRECTION;
  const policy = shortMediaPolicy(request);
  const selection = request.selection === "auto"
    ? "Choose the visual treatment from the retained message, viewer's need and inspected reference examples. Explain the choice and reject a plausible alternative."
    : `Honor this operator direction as editorial DATA: ${JSON.stringify(request.request)}. Retrieve its actual examples and explain which mechanics transfer. Do not replace it silently; state any source/asset limitation before assembly.`;
  const footage = policy.placement === "off"
    ? "Supporting video is off, along with photo/logo cutaways. Keep the source performance and supported original explanations."
    : "Search the supplied recording first, including material outside the dialogue cut; then inspect the admitted local asset pool. Record candidate ranges, what was actually seen, why the chosen shot helps, and rejected alternatives. Empty separate B-roll folders do not mean the source contains no useful supporting footage. If nothing relevant exists, record that gap; any external acquisition remains subject to the user's current authorization.";
  const webFootage = policy.placement === "off" || policy.sources !== "public-web" ? "" : "After choosing the beat's visual representation, consider a real screen walkthrough proactively when showing the actual brand, product, website or GitHub repository helps explain the retained point. A conceptual overview may instead use the selected metaphor or diagram. Resolve the exact official site or owner/repository from primary sources; a name alone is not a verified URL. Under current public-browsing authorization, inspect it and use scripts/producer/studio/web_capture.py to record the relevant section scrolling into view, with readable opening/result holds. Follow docs/producer/WEB_BROLL_WORKFLOW.md. Keep original branding, inspect mobile readability and cue the reveal to the spoken point. Admit the frozen ASSET.json with its webCapture receipts; do not substitute a fabricated website, recolored mark or generic moving page. A scroll demonstrates page content, not successful product use. Report blocked pages or missing relevant sections. The editing agent owns discovery and shot selection; mentioning a brand does not select a fixed preset.";
  return `${SHORT_NARRATIVE_INSTRUCTIONS}\n${SHORT_HOOK_INSTRUCTIONS}\n${SHORT_VISUAL_STORYTELLING_INSTRUCTIONS}\n${SHORT_PACING_INSTRUCTIONS}\n${SHORT_AUDIO_INSTRUCTIONS}\n${selection}\n${footage}\n${webFootage}\nMedia sourcing policy: ${policy.sources}; insert placement: ${policy.placement}. This applies equally to images, logos, creator photos, excerpts and website recordings, including cached downloads. No generated media or remote model transmission is enabled. For native strategy v3, author assetUse with speech-bound insert/no-insert decisions and pinned origin receipts using the existing AssetRecordV1. Distinguish a creator mentioned as a style reference from a person depicted in the content. Record exact identity, viewing purpose, inspected source, claim limit, essential visible region and output window. Source identity and contextual fit require inspection; a populated field is not verification. Retain needs-review publication disposition for unresolved sources. Audible external quotes need a supported audio handoff; do not silently mute them.\nFor every demonstration, plan a traceable input/current state → visible operation → result → reading hold, cued to retained speech. Keep the same example identifiable; show the change rather than substituting topic labels. Distinguish illustration/context from evidence of achieved results. A dog eating can illustrate an offer; it cannot prove a health transformation.\nInspect source crops and pane jobs before choosing a split; never contain a tiny landscape presenter as the default.\nThese are planning obligations, not proof that retrieval, visual review or rendering has occurred.`;
}
