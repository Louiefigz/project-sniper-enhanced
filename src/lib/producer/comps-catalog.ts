// Curated ELEMENTS catalog — the operator-insertable comp kinds. Each entry
// mirrors a template at templates/motion/compositions/<kind>.html (the Python
// renderer resolves kind → that file, so `kind` strings here are load-bearing).
//
// `ownScreen` kinds are full-frame CUTAWAYS (opaque, they hard-cut the frame —
// anchor "own-screen"); the rest are alpha overlays placed in the free band
// (anchor "free-band"). `canvas` is the aspect the comp authors on (from the
// planner's kind→canvas map) so the UI can flag vertical-only comps inside a
// 16:9 longform edit. `defaultSpec` = the comp's data-composition-variables
// with placeholder copy the operator overwrites in the properties panel.
//
// Data catalog — exempt from the logic-file line limit.

export type CompCanvas = "16:9" | "9:16";

/** One extra spec knob the properties panel exposes beyond the primary text key. */
export interface SpecField {
  key: string;
  label: string;
  type: "number" | "color";
  min?: number;
  max?: number;
  /** number fields: input step; < 1 = decimal field, else integer. Default 1. */
  step?: number;
}

export interface CompCatalogEntry {
  kind: string;
  label: string;
  description: string;
  ownScreen: boolean;
  canvas: CompCanvas;
  defaultSpec: Record<string, unknown>;
  /** Sectioned entries group after a divider in the ELEMENTS panel:
   *  "slideware" = the slideware reference pack (reel-study comps, all 9:16),
   *  "module" = the module card pack (MODULE_CARDS study, all 16:9
   *  longform — cream split-panel rails overlay footage, dark cards are
   *  own-screen takeovers),
   *  "primitives" = raw building blocks. */
  section?: "primitives" | "slideware" | "module";
  /** Extra editable spec fields (graphic-properties renders them generically). */
  specFields?: SpecField[];
}

/** The canvas a plan renders on — longform edits are 16:9, everything else 9:16. */
export function planCanvas(target?: { mode?: string }): CompCanvas {
  return target?.mode === "longform" ? "16:9" : "9:16";
}

export const COMPS_CATALOG: CompCatalogEntry[] = [
  {
    kind: "statement-card",
    label: "Statement card",
    description: "Full-frame card for one thesis line — wrap the key words in *asterisks* to accent them.",
    ownScreen: true,
    canvas: "16:9",
    defaultSpec: {
      variant: "classic",
      text: "Make the *key point* land",
      bg: "dark",
      accent: "#7FB4FF",
    },
  },
  {
    kind: "kinetic-quote-wide",
    label: "Kinetic quote",
    description: "Full-frame quote that builds word by word; emphasis words land in yellow.",
    ownScreen: true,
    canvas: "16:9",
    defaultSpec: {
      words: "your quote builds word by word",
      emphasisWords: "quote",
    },
  },
  {
    kind: "glass-lower-third",
    label: "Glass lower third",
    description: "Frosted-glass title bar over the talking head — eyebrow, title, optional highlight pill.",
    ownScreen: false,
    canvas: "16:9",
    defaultSpec: {
      eyebrow: "CONTEXT",
      titleBase: "Your headline here",
      titleHighlight: "",
      side: "left",
      accent: "#054BC9",
    },
  },
  {
    kind: "icon-badge-wide",
    label: "Icon badges",
    description: "Up to three brand icons staged around the subject (icons must exist in templates/motion/icons).",
    ownScreen: false,
    canvas: "16:9",
    defaultSpec: {
      icon1: "openai-color.svg",
      icon2: "claude-color.svg",
      icon3: "gemini-color.svg",
      x1: 421, y1: 402, x2: 958, y2: 143, x3: 1497, y3: 402,
      at1: 0.25, at2: 0.7, at3: 1.15,
      size: 168,
    },
  },
  {
    kind: "whiteboard-list",
    label: "Whiteboard list",
    description: "Full-frame whiteboard checklist — a title pill plus up to five items that tick in.",
    ownScreen: true,
    canvas: "16:9",
    defaultSpec: {
      title: "The plan",
      item1: "First step",
      item2: "Second step",
      item3: "Third step",
      at1: 0.4, at2: 1.2, at3: 2.0,
      accent: "#054BC9",
    },
  },
  {
    kind: "stat-card",
    label: "Stat card",
    description: "Full-frame number card — a big value counts up over its label.",
    ownScreen: true,
    canvas: "9:16",
    defaultSpec: {
      value: "10+ years",
      label: "of experience",
      count_up: true,
      accent: "#054BC9",
    },
  },
  {
    kind: "chip-row",
    label: "Chip row",
    description: "A row of up to four labelled chips (with optional icons) that pop in on beat.",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      chip1: "First",
      chip2: "Second",
      chip3: "Third",
      at1: 0.2, at2: 0.55, at3: 0.9,
      accent: "#054BC9",
    },
  },
  {
    kind: "list-build",
    label: "List build",
    description: "Three checklist items that land one by one — the compact vertical list.",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      item1: "Point one",
      item2: "Point two",
      item3: "Point three",
      at1: 0.2, at2: 0.9, at3: 1.6,
      chip_style: "check",
      accent: "#054BC9",
    },
  },
  {
    kind: "section-marker",
    label: "Section marker",
    description: "Headroom overlay — an eyebrow number, a serif accent title, and a qualifier over the live footage.",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      num: "No.1",
      line1: "Section",
      line2: "Title",
      side: "left",
      accent: "#054BC9",
      readability: "plates",
    },
  },
  {
    kind: "versus-split",
    label: "Versus split",
    description: "Full-frame before/after column contrast — up to three row pairs land on beat.",
    ownScreen: true,
    canvas: "9:16",
    defaultSpec: {
      leftTitle: "Before",
      rightTitle: "After",
      left1: "Old way",
      right1: "New way",
      left2: "", right2: "", left3: "", right3: "",
      at1: 0.5, at2: 1.0, at3: 1.5,
      accent: "#054BC9",
    },
  },
  {
    kind: "underline-circle",
    label: "Underline / circle",
    description: "Hand-drawn accent stroke over the frame — underline or circle at a fixed x/y box.",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      shape: "underline",
      x: 240, y: 880, w: 600, h: 150,
      drawAt: 0.2,
      accent: "#054BC9",
    },
  },
  {
    kind: "stroke-draw-badge",
    label: "Stroke-draw badge",
    description:
      "Icon outline stroke-draws in like a marker, floods with fill, and an optional label pops with the flood — the save-CTA move (icon must exist in templates/motion/icons; path-only SVGs).",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      icon: "youtube.svg",
      label: "Subscribe",
      atS: 0.2,
      slotX: 0.5,
      slotY: 0.5,
      accent: "#F5E960",
    },
    specFields: [
      { key: "atS", label: "draw at s", type: "number", min: 0, max: 30, step: 0.05 },
      { key: "slotX", label: "center x", type: "number", min: 0.05, max: 0.95, step: 0.01 },
      { key: "slotY", label: "center y", type: "number", min: 0.05, max: 0.95, step: 0.01 },
      { key: "accent", label: "accent", type: "color" },
    ],
  },
  {
    kind: "widget-gauge",
    label: "Gauge widget",
    description: "Milestone gauge — a labelled progress bar whose marker advances to timed positions.",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      label: "Progress",
      pos1: 0.15, at1: 0.3,
      pos2: 0.45, at2: 1.4,
      pos3: 0.72, at3: 2.6,
      accent: "#054BC9",
    },
  },

  // ---- SLIDEWARE PACK — comps decomposed from the slideware reel study (top 4 by
  // rank). All 9:16; templates at compositions/slideware-*.html. The lime accent
  // (#C9FB00) is ONE token per reel — override it once, everywhere.
  {
    kind: "slideware-takeover-deck",
    label: "Takeover deck",
    description:
      "Full-frame lime slide deck — header + caption pill ON at the cut, card-white sheets page carousel-style (exit-left / enter-right).",
    ownScreen: true,
    canvas: "9:16",
    section: "slideware",
    defaultSpec: {
      header: "For Carousel Posts",
      headerInk: "white",
      slide1: "Call out the exact viewer|Show the receipt on screen|Say the payoff in 5 words",
      slide2: "Post before 9am|Reply to the first 10 comments",
      pill1: "steal this structure",
      pill2: "then do this",
      pageAt2: 2.0,
      accent: "#C9FB00",
    },
    specFields: [
      { key: "pageAt2", label: "page 2 at s", type: "number", min: 0, max: 30, step: 0.05 },
      { key: "pageAt3", label: "page 3 at s", type: "number", min: 0, max: 30, step: 0.05 },
      { key: "accent", label: "lime", type: "color" },
    ],
  },
  {
    kind: "slideware-staircase-lockup",
    label: "Staircase lockup",
    description:
      "Kicker / lime ALL-CAPS payload / co-word staircase — word-locked 0-frame pops, in-place replace-chain, never a fade.",
    ownScreen: false,
    canvas: "9:16",
    section: "slideware",
    defaultSpec: {
      kicker: "Step *#1:* do this every day",
      payload: "Post Daily",
      coWord: "for 30 days",
      band: "headroom",
      payloadSize: 106,
      kickerAt: 0,
      payloadAt: 0.35,
      coAt: 0.75,
      accent: "#C9FB00",
    },
    specFields: [
      { key: "payloadSize", label: "payload px", type: "number", min: 60, max: 152, step: 2 },
      { key: "payloadAt", label: "payload at s", type: "number", min: 0, max: 30, step: 0.05 },
      { key: "coAt", label: "co-word at s", type: "number", min: 0, max: 30, step: 0.05 },
      { key: "accent", label: "lime", type: "color" },
    ],
  },
  {
    kind: "slideware-receipt-cell",
    label: "Receipt cells",
    description:
      "Proof-stamp thumb cells — olive label chip over a 9:16 media slot with an eye-count view chip; strip / grid / showcase, per-cell pops.",
    ownScreen: false,
    canvas: "9:16",
    section: "slideware",
    defaultSpec: {
      layout: "strip",
      label1: "Day 1", label2: "Day 7", label3: "Day 14", label4: "Day 30",
      views1: "1.2M", views2: "847K", views3: "2.1M", views4: "3.4M",
      at1: 0.2, at2: 0.55, at3: 0.9, at4: 1.25,
      corner: "rounded",
    },
    specFields: [
      { key: "at1", label: "cell 1 at s", type: "number", min: 0, max: 30, step: 0.05 },
      { key: "at2", label: "cell 2 at s", type: "number", min: 0, max: 30, step: 0.05 },
      { key: "at3", label: "cell 3 at s", type: "number", min: 0, max: 30, step: 0.05 },
      { key: "at4", label: "cell 4 at s", type: "number", min: 0, max: 30, step: 0.05 },
    ],
  },
  {
    kind: "slideware-caption-dual-mode",
    label: "Whisper captions",
    description:
      "Whisper caption chain — hard replace-per-cue, footage skin (white, chest band) or canvas pill skin (for lime takeovers); *bold* is the only emphasis.",
    ownScreen: false,
    canvas: "9:16",
    section: "slideware",
    defaultSpec: {
      mode: "footage",
      cue1: "here is the",
      cue2: "one *mistake*",
      cue3: "everyone makes",
      at1: 0, at2: 0.8, at3: 1.6,
    },
    specFields: [
      { key: "at2", label: "cue 2 at s", type: "number", min: 0, max: 30, step: 0.05 },
      { key: "at3", label: "cue 3 at s", type: "number", min: 0, max: 30, step: 0.05 },
    ],
  },

  // ---- MODULE PACK — the card library decomposed from the module
  // longform study (docs/studies/MODULE_CARDS.md; templates compositions/
  // module-*.html). All 16:9 LONGFORM. Two chassis (§1.1): the CREAM
  // split-panel (alpha rail beside the live face — NOT own-screen) and the
  // DARK takeover (own-screen full-frame). His cream/ink/lime/cyan are the
  // CSS-var fallbacks; brand tokens override (--rail-cream, --accent-result,
  // --accent-process, --accent-warn). Variety doctrine (§2): tokens repeat,
  // layouts don't — the planner should drain distinct forms before reuse.
  {
    kind: "module-rail",
    label: "Cream rail (chassis)",
    description:
      "Cream split-panel that wipes in from the left edge (33%W) beside the live face — eyebrow, thesis headline, and a modular zone: KV ledger, status/queue cards, numbered steps, checklist with OK badges, or a dated vertical timeline (contentMode).",
    ownScreen: false, // overlays footage — the face stays full-frame right
    canvas: "16:9",
    section: "module",
    defaultSpec: {
      eyebrow: "LONG-HORIZON WORK",
      headlineLines: "One thread.|Every handoff.",
      explainer: "Long, messy work that crosses tools.",
      contentMode: "steps",
      rows: "01~Research~SOURCE|02~Code~BUILD|03~APIs~CALL|04~Wait~RESUME|05~Inspect~VERIFY",
      evidenceSource: "OPENAI · BEST CODING MODEL YET",
    },
  },
  {
    kind: "module-takeover",
    label: "Dark takeover (face PIP)",
    description:
      "Near-black takeover with the face in a rounded PIP card right — eyebrow, two-line accent headline, hero-vs-comparison bars with a delta chip, chip sweep, evidence ribbon. Longform-only (the renderer fills the face hole).",
    ownScreen: true,
    canvas: "16:9",
    section: "module",
    defaultSpec: {
      eyebrow: "ULTRA ORCHESTRATION",
      headlineLines: "ONE RUN.|FOUR AGENTS.",
      heroLabel: "GPT-5.6 SOUL",
      heroValue: "92.4",
      heroPct: "92",
      compareLabel: "PREV BEST",
      compareValue: "86.1",
      comparePct: "86",
      deltaChip: "+6.3 POINTS",
      evidenceSource: "OPENAI GPT-5.6 RELEASE",
      evidenceDate: "JUL 09 2026",
    },
  },
  {
    kind: "module-ledger-dark",
    label: "Dark ledger + fan-out",
    description:
      "Dark config/parallel-process card — KV ledger rows with status tags (model → VERIFIED), an optional wide ledger bar, and a fan-out under a cyan connector tree: numbered chips or parallel-agent columns with lime underlines (grid).",
    ownScreen: true,
    canvas: "16:9",
    section: "module",
    defaultSpec: {
      eyebrow: "ULTRA ORCHESTRATION",
      headlineLines: "ONE RUN.|FOUR AGENTS.",
      barLabel: "DEFAULT PARALLELISM",
      barValue: "4",
      barStatus: "COORDINATING",
      grid: "columns",
      gridItems: "AGENT 01~RESEARCH|AGENT 02~SCRIPT|AGENT 03~PRODUCTION|AGENT 04~VERIFICATION",
      footChip: "OPENAI: FOUR AGENTS IN PARALLEL BY DEFAULT",
    },
  },
  {
    kind: "module-scoreboard",
    label: "Big-number scoreboard",
    description:
      "Dark hero-metric payoff card — giant lime number, outlined stat tiles, a color-coded per-item chip strip (win/tie/loss sweep), and the amber LIMIT caveat footer that lands last.",
    ownScreen: true,
    canvas: "16:9",
    section: "module",
    defaultSpec: {
      eyebrow: "SMALL LOCAL CHECK",
      contextChips: "ONE RUN|13 TASKS|THIS MACHINE",
      heroValue: "97%",
      heroLabel: "AVAILABLE OBJECTIVE POINTS",
      tiles: "7~WINS|5~TIES|1~LOSS",
      stripChips: "01~win|02~win|03~win|04~win|05~win|06~win|07~win|08~tie|09~tie|10~tie|11~tie|12~tie|13~loss",
      limitLabel: "LIMIT",
      limitText: "Not proof it wins everything.",
    },
  },
  {
    kind: "module-bullet-bars",
    label: "Bullet bars vs limit",
    description:
      "Cream rail with measured lime bullet bars against an amber threshold tick — measurements vs a limit, with a lime verdict footnote and an optional spectrum rail. Overlays footage (face stays full-frame right).",
    ownScreen: false, // overlays footage — same cream-chassis law as the rail
    canvas: "16:9",
    section: "module",
    defaultSpec: {
      eyebrow: "VOICE CONSISTENCY",
      headlineLines: "Four short generations.",
      explainer: "Each section stayed below a self-imposed 60-second production cap.",
      axisLabel: "60 SEC PRODUCTION CAP",
      bars: "01~40.4~67|02~48.1~80|03~47.4~79|04~45.4~76",
      threshPct: 100,
      verdict: "4 OF 4 UNDER 60 SEC",
      spectrum: "BEGINNING|VOICE HELD|END",
    },
    specFields: [
      { key: "threshPct", label: "limit tick %", type: "number", min: 0, max: 100, step: 1 },
    ],
  },
  {
    kind: "module-pipeline",
    label: "Node pipeline",
    description:
      "Dark process-summary card — 2-8 connected pipeline tiles (num + label) with a cyan you-are-here dot on the active node; the whole chain in one glance.",
    ownScreen: true,
    canvas: "16:9",
    section: "module",
    defaultSpec: {
      eyebrow: "ONE INSTRUCTION TO FINISHED VIDEO",
      headlineLines: "The chain changed.|The outcome held.",
      nodes: "01~PROMPT|02~ELEVENLABS VOICE|03~HEYGEN AVATAR V|04~HYPERFRAMES EDIT|05~INDEPENDENT QA|06~FINISHED VIDEO",
      activeIndex: 5,
    },
    specFields: [
      { key: "activeIndex", label: "active node", type: "number", min: 0, max: 8, step: 1 },
    ],
  },

  // ---- STUDIED LONGFORM FORMS — production templates that already render
  // under templates/motion/compositions. These used to be absent from this
  // catalog, which made them invisible to both the editor brain and Elements.
  {
    kind: "agenda-slide",
    label: "Agenda slide",
    description: "Opaque chapter agenda with up to five numbered steps and subtitles that land as a structured roadmap.",
    ownScreen: true,
    canvas: "16:9",
    defaultSpec: {
      eyebrow: "The plan", title: "3 Steps",
      num1: "1", title1: "Pick your target", sub1: "the next 90 days",
      num2: "2", title2: "Get help", sub2: "even cheap help",
      num3: "3", title3: "Ship weekly", sub3: "one every week",
      num4: "4", title4: "", sub4: "", num5: "5", title5: "", sub5: "",
      accent: "#054BC9",
    },
  },
  {
    kind: "avatar-bio-card",
    label: "Animated credibility bio",
    description: "Full-frame credibility sequence: avatar or initials, a word-built credential, then a recomposed second proof line.",
    ownScreen: true,
    canvas: "16:9",
    defaultSpec: {
      avatarSrc: "", initials: "PS", line1: "", line2: "", at2: 3,
      accentColor: "#054BC9",
    },
  },
  {
    kind: "canvas-pip-list",
    label: "Canvas + speaker list",
    description: "Opaque studio canvas reserving a speaker PIP while up to eight transcript-locked list items build beside it.",
    ownScreen: true,
    canvas: "16:9",
    defaultSpec: {
      title: "", item1: "", item2: "", item3: "", item4: "",
      item5: "", item6: "", item7: "", item8: "",
      at1: 0.6, at2: 2.4, at3: 4.2, at4: 6, at5: 7.8, at6: 9.6,
      at7: 11.4, at8: 13.2, accentColor: "#054BC9",
    },
  },
  {
    kind: "fragment-payoff",
    label: "Fragment → payoff",
    description: "Transparent two-tier lockup: a small verbatim setup followed by a large word-built payoff on the emptier side.",
    ownScreen: false,
    canvas: "16:9",
    defaultSpec: {
      fragment: "", payoff: "", accentColor: "#7FB4FF",
      payoffAt: 0.8, wordGapMs: 130, align: "center",
    },
  },
  {
    kind: "glass-rail",
    label: "Glass process rail",
    description: "Transparent left/right process rail with up to six numbered rows, transcript-locked row lands, and measured rail-push motion.",
    ownScreen: false,
    canvas: "16:9",
    defaultSpec: {
      eyebrow: "", num1: "", title1: "", sub1: "", icon1: "",
      num2: "", title2: "", sub2: "", icon2: "",
      num3: "", title3: "", sub3: "", icon3: "",
      num4: "", title4: "", sub4: "", icon4: "",
      num5: "", title5: "", sub5: "", icon5: "",
      num6: "", title6: "", sub6: "", icon6: "", rowLands: "",
      side: "left", accent: "#054BC9", build: "stamp", exit: "fade",
      entrance: "slide", theme: "glass",
    },
  },
  {
    kind: "logo-card",
    label: "Logo proof card",
    description: "Opaque widescreen identity beat with one verified icon asset and a restrained brand glow.",
    ownScreen: true,
    canvas: "16:9",
    defaultSpec: { iconFile: "notion.svg", accent: "#054BC9" },
  },
  {
    kind: "section-takeover",
    label: "Section takeover",
    description: "Warm-white chapter takeover whose numeral, title, and subline build in three transcript-locked states.",
    ownScreen: true,
    canvas: "16:9",
    defaultSpec: {
      num: "", title: "", sub: "", accentColor: "#054BC9",
      at1: 0.3, at2: 1.5, at3: 2.5,
    },
  },
  {
    kind: "whiteboard-connector",
    label: "Whiteboard connector",
    description: "Floating wide whiteboard overlay with a labelled connector drawing toward a transcript-backed statement.",
    ownScreen: false,
    canvas: "16:9",
    defaultSpec: {
      label: "And in that time", text: "I built the whole content pipeline",
      accent: "#054BC9",
    },
  },
  {
    kind: "whiteboard-map",
    label: "Whiteboard map",
    description: "Full-frame map whose title, connectors, icons, and up to four nodes build progressively with optional value handoff.",
    ownScreen: true,
    canvas: "16:9",
    defaultSpec: {
      title: "", node1: "", node2: "", node3: "", node4: "",
      at1: 0.5, at2: 1.4, at3: 2.3, at4: 3.2, accent: "#054BC9",
      handoffText: "", handoffAt: 1.2,
      icon1: "", icon2: "", icon3: "", icon4: "", panX: 0,
    },
  },
  {
    kind: "glass-takeover-bg",
    label: "Glass takeover canvas",
    description: "Opaque widescreen grid-and-glass canvas for a coordinated face-PIP or rail composition; content stays empty unless authored.",
    ownScreen: true,
    canvas: "16:9",
    defaultSpec: { eyebrow: "", title: "", accent: "#054BC9" },
  },
  {
    kind: "color-wash",
    label: "Color wash seam",
    description: "Transparent widescreen color sweep for an earned world-change seam; not a generic card transition.",
    ownScreen: false,
    canvas: "16:9",
    defaultSpec: { accent: "#054BC9", accent2: "#6D3BE0", dir: "ltr" },
  },
  {
    kind: "glitch-hit",
    label: "Glitch hit",
    description: "Very brief transparent widescreen glitch punctuation for a specifically motivated hit.",
    ownScreen: false,
    canvas: "16:9",
    defaultSpec: { durMs: 400 },
  },
  {
    kind: "blur-tease",
    label: "Blur tease",
    description: "Vertical image tease that stays obscured or sharpens at a timed reveal, with a short expectation-setting label.",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      image: "", label: "wait for it…", revealAt: 0, accent: "#054BC9",
    },
  },
  {
    kind: "icon-badge",
    label: "Icon badge row",
    description: "Vertical row of up to four verified icon marks that land one at a time with an optional micro-label.",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      icon1: "codex", icon2: "gemini", icon3: "cursor", icon4: "",
      at1: 0.2, at2: 0.55, at3: 0.9, at4: 1.25, label: "",
    },
  },
  {
    kind: "punch-shout-lockup",
    label: "Shout lockup",
    description: "Measured vertical kicker/payload/co-word typography with hard pops or tightly timed word appends.",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      kicker: "", payload: "", coword: "", kicker2: "", build: "pop",
      splitText: false, atS: 0, appendS: 0.15, slotY: 0.19, slotX: 0.3,
      payloadPctH: 5, accent: "#F5E960",
    },
  },
  {
    kind: "kinetic-quote",
    label: "Kinetic quote (vertical)",
    description: "Vertical full-frame quote whose words build into a single highlighted term.",
    ownScreen: true,
    canvas: "9:16",
    defaultSpec: {
      quote: "AI made this buildable.", bg: "dark",
      highlight: "buildable", accent: "#054BC9",
    },
  },
  {
    kind: "schedule-stack",
    label: "Schedule stack",
    description: "Vertical stack of up to four semantically colored schedule cards, positioned opposite the subject.",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      title1: "Ideation", time1: "8-10am", color1: "#2FBF71",
      title2: "Filming", time2: "10-2pm", color2: "#3B82F6",
      title3: "Distribution", time3: "2-3pm", color3: "#F2724B",
      title4: "", time4: "", color4: "#7C5CF0",
      side: "right", accent: "#054BC9",
    },
  },
  {
    kind: "stinger-wipe",
    label: "Chapter stinger",
    description: "Full-frame vertical chapter stinger with a solid sweep, gleam, title, and underline.",
    ownScreen: true,
    canvas: "9:16",
    defaultSpec: { title: "The Six Shifts", accent: "#054BC9" },
  },
  {
    kind: "widget-pills",
    label: "Value pill sequence",
    description: "Vertical left/right value pills that update through four transcript-locked states with an optional staged arrow.",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      l1: "10k", r1: "50k", at1: 0.3,
      l2: "50k", r2: "100k", at2: 1.6,
      l3: "100k", r3: "200k", at3: 2.9,
      l4: "", r4: "", at4: 4.2,
      arrowInAt: 0, rightInAt: 0, accent: "#054BC9",
    },
  },

  // ---- CATALOG PORT PACK (2026-08-28) — comps ported from the HyperFrames
  // catalog study (docs/producer/catalog-study/CATALOG_STUDY.md): the
  // hand-drawn annotation family plus the data/hook/screen wave. Templates
  // at compositions/<kind>.html; slot contracts in template_hw_contract /
  // template_catalog_contract.
  {
    kind: "marker-highlight",
    label: "Marker highlight",
    description:
      "Cream paper panel with one spoken line — a hand-drawn marker stroke (highlight/circle/underline/scribble) draws over the emphasis word on cue (whole-word match).",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      text: "The hook does the heavy lifting",
      emphasisWord: "hook",
      style: "highlight",
      drawAt: 0.9,
      accent: "#054BC9",
    },
    specFields: [
      { key: "drawAt", label: "draw at s", type: "number", min: 0, max: 30, step: 0.05 },
      { key: "accent", label: "ink", type: "color" },
    ],
  },
  {
    kind: "hw-callout-circle",
    label: "Callout circle",
    description:
      "Hand-wobbled ellipse draws around an x/y/w/h region of the frame with an optional scribble hatch and a connected handwritten label; the whole callout boils like marker ink.",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      x: 240, y: 780, w: 600, h: 300,
      label: "look here",
      labelAt: "below",
      scribble: false,
      seed: 4,
      drawAt: 0.2,
      accent: "#054BC9",
    },
    specFields: [
      { key: "x", label: "region x", type: "number", min: 0, max: 1080, step: 1 },
      { key: "y", label: "region y", type: "number", min: 0, max: 1920, step: 1 },
      { key: "w", label: "region w", type: "number", min: 20, max: 1080, step: 1 },
      { key: "h", label: "region h", type: "number", min: 20, max: 1920, step: 1 },
      { key: "drawAt", label: "draw at s", type: "number", min: 0, max: 30, step: 0.05 },
    ],
  },
  {
    kind: "hw-scribble-transition",
    label: "Scribble transition",
    description:
      "Seam cover for a hard subject switch — fat hand-drawn zigzag bands scribble across the frame over a solid backstop, then clear the other way ({} spec is legitimate).",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      bands: 12,
      strokeScale: 1,
      seed: 17,
      accent: "#054BC9",
    },
    specFields: [
      { key: "bands", label: "bands", type: "number", min: 3, max: 18, step: 1 },
      { key: "strokeScale", label: "stroke scale", type: "number", min: 0.5, max: 2, step: 0.05 },
      { key: "accent", label: "ink", type: "color" },
    ],
  },
  {
    kind: "chart-story",
    label: "Chart story",
    description:
      "Evidence card with four chart forms (bars/line/donut/progress) that builds in reading order and lands the exact supplied values; the emphasized datum takes the accent callout. Plan it as a panel, not a takeover.",
    ownScreen: false,
    canvas: "16:9",
    defaultSpec: {
      type: "bars",
      data: "12, 28, 45, 64",
      labels: "Q1, Q2, Q3, Q4",
      emphasize: 3,
      unit: "%",
      accent: "#054BC9",
    },
    specFields: [
      { key: "emphasize", label: "emphasize idx", type: "number", min: 0, max: 7, step: 1 },
      { key: "accent", label: "accent", type: "color" },
    ],
  },
  {
    kind: "count-up",
    label: "Count up",
    description:
      "One hero number on the house card accelerates from start and lands exactly on the integer end value with a restrained pulse; prefix/suffix state the unit.",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      start: 0,
      end: 100,
      prefix: "",
      suffix: "%",
      accent: "#054BC9",
    },
    specFields: [
      { key: "start", label: "start", type: "number", step: 1 },
      { key: "end", label: "end", type: "number", step: 1 },
      { key: "accent", label: "accent", type: "color" },
    ],
  },
  {
    kind: "line-swap",
    label: "Line swap",
    description:
      "Setup-then-subvert hook card — line A holds center in a masked slot, exits up on the swap beat as line B slams in, and an accent underline draws under the matched word.",
    ownScreen: false,
    canvas: "9:16",
    defaultSpec: {
      lineA: "You do not need more footage",
      lineB: "You need a sharper first line",
      swapAt: 1.5,
      underlineWord: "sharper",
      accent: "#054BC9",
    },
    specFields: [
      { key: "swapAt", label: "swap at s", type: "number", min: 0, max: 30, step: 0.1 },
      { key: "accent", label: "accent", type: "color" },
    ],
  },
  {
    kind: "ui-focus-zoom",
    label: "UI focus zoom",
    description:
      "Screen/tutorial cutaway that points — the framed screenshot establishes, then the camera zooms and pans to the anchored region on cue and holds (screenshot must live under templates/motion/assets).",
    ownScreen: true,
    canvas: "16:9",
    defaultSpec: {
      image: "assets/sample-screen.png",
      anchorX: 64,
      anchorY: 36,
      zoom: 1.6,
      zoomAt: 1.4,
      accent: "#054BC9",
    },
    specFields: [
      { key: "anchorX", label: "anchor x %", type: "number", min: 0, max: 100, step: 1 },
      { key: "anchorY", label: "anchor y %", type: "number", min: 0, max: 100, step: 1 },
      { key: "zoom", label: "zoom", type: "number", min: 1.05, max: 3, step: 0.05 },
      { key: "zoomAt", label: "zoom at s", type: "number", min: 0, max: 30, step: 0.1 },
    ],
  },

  // ---- PRIMITIVES — raw building blocks (drag/scale them into a layout).
  // specFields mirror each template's data-composition-variables clamps.
  {
    kind: "text-element",
    label: "Text",
    description: "Bare text primitive — one placeable text block with a brief fade/slide-in; size, weight and color are editable.",
    ownScreen: false,
    canvas: "9:16",
    section: "primitives",
    defaultSpec: {
      text: "Your hook line here",
      fontSize: 64,
      weight: 700,
      color: "#FFFFFF",
      align: "center",
    },
    specFields: [
      { key: "fontSize", label: "size px", type: "number", min: 24, max: 220, step: 2 },
      { key: "weight", label: "weight", type: "number", min: 100, max: 900, step: 100 },
      { key: "color", label: "color", type: "color" },
    ],
  },
  {
    kind: "text-element-wide",
    label: "Text (wide)",
    description: "Bare text primitive on the 16:9 canvas — one placeable text block with a brief fade/slide-in.",
    ownScreen: false,
    canvas: "16:9",
    section: "primitives",
    defaultSpec: {
      text: "Your hook line here",
      fontSize: 64,
      weight: 700,
      color: "#FFFFFF",
      align: "center",
    },
    specFields: [
      { key: "fontSize", label: "size px", type: "number", min: 24, max: 220, step: 2 },
      { key: "weight", label: "weight", type: "number", min: 100, max: 900, step: 100 },
      { key: "color", label: "color", type: "color" },
    ],
  },
  {
    kind: "container-shape",
    label: "Container",
    description: "Rounded-rectangle container primitive — a flat color panel with a subtle scale-in; layer text elements on top.",
    ownScreen: false,
    canvas: "9:16",
    section: "primitives",
    defaultSpec: {
      bg: "#FFFFFF",
      radiusPx: 28,
      opacity: 1,
      widthPx: 640,
      heightPx: 360,
    },
    specFields: [
      { key: "bg", label: "bg", type: "color" },
      { key: "radiusPx", label: "radius px", type: "number", min: 0, max: 400, step: 2 },
      { key: "opacity", label: "opacity", type: "number", min: 0, max: 1, step: 0.05 },
      { key: "widthPx", label: "w px", type: "number", min: 20, max: 1080, step: 2 },
      { key: "heightPx", label: "h px", type: "number", min: 20, max: 1920, step: 2 },
    ],
  },
  {
    kind: "container-shape-wide",
    label: "Container (wide)",
    description: "Rounded-rectangle container primitive on the 16:9 canvas — a flat color panel with a subtle scale-in.",
    ownScreen: false,
    canvas: "16:9",
    section: "primitives",
    defaultSpec: {
      bg: "#FFFFFF",
      radiusPx: 28,
      opacity: 1,
      widthPx: 640,
      heightPx: 360,
    },
    specFields: [
      { key: "bg", label: "bg", type: "color" },
      { key: "radiusPx", label: "radius px", type: "number", min: 0, max: 400, step: 2 },
      { key: "opacity", label: "opacity", type: "number", min: 0, max: 1, step: 0.05 },
      { key: "widthPx", label: "w px", type: "number", min: 20, max: 1920, step: 2 },
      { key: "heightPx", label: "h px", type: "number", min: 20, max: 1080, step: 2 },
    ],
  },
];

const BY_KIND = new Map(COMPS_CATALOG.map((c) => [c.kind, c]));

/** The extra editable spec fields for a kind ([] for kinds without any). */
export function specFieldsFor(kind: string): SpecField[] {
  return BY_KIND.get(kind)?.specFields ?? [];
}

/**
 * Vocabulary block for the Ask-Claude AND auto-edit authoring prompts: one line
 * per comp (kind, canvas, description) plus a hard canvas rule — a comp authored
 * on the wrong canvas composites half-frame, and the fast assemble path has no
 * lint. Pass `null` when the plan's canvas isn't known at prompt time (auto-edit
 * before target.mode is decided): the rule is phrased against target.mode.
 */
export function catalogPromptLines(canvas: CompCanvas | null): string[] {
  const rule = canvas
    ? `Only insert comps whose canvas matches this plan (${canvas})`
    : `Only insert comps whose canvas matches your target.mode (longform → 16:9, short → 9:16)`;
  return [
    ...COMPS_CATALOG.map(
      (c) =>
        `- ${c.kind} [canvas ${c.canvas}] — ${c.description}${c.ownScreen ? " (own-screen full-frame cutaway)" : " (free-band overlay)"}`,
    ),
    `${rule} — a mismatched-canvas comp composites half-frame and there is no lint on the fast assemble path.`,
  ];
}
