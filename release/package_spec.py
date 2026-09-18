"""Inspected allow-list for the buyer package (data catalog, not logic).

Every entry carries the reason it ships or is withheld. Nothing is included by a
blanket rule and nothing is withheld merely because an import graph missed it:
the agent surfaces (skills, commands, prompts, JSON contracts, subprocess paths,
retained tests) are treated as reachable.

Paths are POSIX, relative to the release source root. A directory entry ships
the whole subtree minus any DENY match.
"""
from __future__ import annotations

# --------------------------------------------------------------------------
# SHIP — application, runtime inputs and the agent instruction chain
# --------------------------------------------------------------------------
INCLUDE: tuple[tuple[str, str], ...] = (
    # --- Next application ---------------------------------------------------
    ("src", "the whole application surface: pages, API routes, libs, prompts"),
    ("public", "static assets served by Next"),
    ("package.json", "root dependency manifest and the npm entry points"),
    ("package-lock.json", "root dependency closure (npm ci)"),
    ("next.config.ts", "Next configuration"),
    ("tsconfig.json", "TypeScript project config (type-check)"),
    ("postcss.config.mjs", "Tailwind v4 pipeline"),
    ("eslint.config.mjs", "lint config referenced by npm run lint"),
    ("components.json", "shadcn component config"),

    # --- Python engine ------------------------------------------------------
    ("scripts", "Producer engine, Segmenter, Clipper, Text Review, supervisor"),
    ("requirements.txt", "declared floors (the installer uses the lock beside it)"),
    ("schemas", "Codex output schemas and the reference-profile schema"),

    # --- Render inputs ------------------------------------------------------
    ("templates/motion/package.json", "second dependency root"),
    ("templates/motion/package-lock.json", "second dependency closure"),
    ("templates/motion/hyperframes.json", "HyperFrames project layout"),
    ("templates/motion/meta.json", "project metadata"),
    ("templates/motion/index.html", "project entry the preview/render server serves"),
    ("templates/motion/tokens.css", "brand tokens with embedded OFL faces"),
    ("templates/motion/motion-tokens.js", "shared motion constants"),
    ("templates/motion/module-pipeline.js", "script the module-pipeline composition loads"),
    ("templates/motion/agenda-caption-layout.css", "caption layout used by comps"),
    ("templates/motion/comp_capabilities.json", "measured capability matrix (plan-time gate)"),
    ("templates/motion/compositions", "the render vocabulary"),
    ("templates/motion/icons", "icon set referenced by comps"),
    ("templates/motion/assets", "comp-local assets"),
    ("templates/motion/vendor", "pinned GSAP core + SplitText + DrawSVG (see PROVENANCE.md)"),
    ("templates/motion/PROVENANCE.md", "vendored-material record: GSAP terms, embedded fonts, "
                                       "ported compositions, icon sources"),
    ("templates/motion/AGENTS.md", "motion-project instructions for the agent"),
    ("templates/motion/CLAUDE.md", "same instructions for the Claude route"),
    ("templates/clip-review", "local clip review page used at handoff"),

    # --- Bundled cleared assets --------------------------------------------
    ("assets/fonts", "OFL faces plus their licence text"),
    ("assets/models", "YuNet face-detection weights"),
    ("assets/sfx", "bundled SFX and their PROVENANCE.md"),
    ("assets/music", "starter bed synthesized by scripts/producer/audio/default_bed.py; "
                     "the Auto Edit pipeline snapshot requires this set"),

    # --- Runtime contracts and data read by shipped code ----------------------
    # Loaded by path segments (render_effect_registry.py, program_mix_registry.py,
    # external_ingress_registry.py, current_render_calibration_source.py,
    # short-long-route-matrix.ts) and required by auto-edit-pipeline-assets.ts.
    # The retained development evidence beside them (p0-p5 receipts, rate matrix,
    # inventories) is not shipped.
    ("docs/producer/command-driven-editing/contracts/render-effect-registry-v1.json", "runtime registry"),
    ("docs/producer/command-driven-editing/contracts/program-audio-mix-registry-v1.json", "runtime registry"),
    ("docs/producer/command-driven-editing/contracts/external-ingress-registry-v1.json", "runtime registry"),
    ("docs/producer/command-driven-editing/contracts/current-render-codec-floor-calibration-v1.json",
     "runtime render calibration"),
    ("docs/producer/command-driven-editing/contracts/short-long-route-matrix-v1.json", "runtime route matrix"),
    ("docs/producer/catalog-study/catalog-study.json", "catalog discovery study read by graphics/catalog_discovery_sources.py"),

    # --- Agent instruction chain (reachable through skills, not imports) ----
    (".claude/skills", "the five canonical skills: producer, segmenter, clipper, "
                       "reference-editor, producer-study"),
    (".claude/commands", "explicit routing commands"),
    (".agents/skills", "Codex adapters for the same five skills"),
    ("AGENTS.md", "repo-root instructions (rewritten self-contained for the package)"),
    ("CLAUDE.md", "Claude-route instructions"),
    ("README.md", "developer-facing reference retained for the agent"),

    # --- Docs: the operational set only (release/operational-docs.json) -------
    # Computed by release/doc_closure.py: docs named in shipped code, docs linked
    # directly from shipped instruction surfaces, and the required workflow docs.
    # Dated development history is withheld (client work, internal evidence).
    ("@operational-docs", "release/operational-docs.json"),

    # --- Packaged original libraries -----------------------------------------
    ("resources/director", "original Director hook/format library (resources/director/README.md)"),
    ("resources/references", "original reference library rendered from Sniper templates"),

    # --- Read-only catalog mirror (reachable: catalog_discovery_sources.py) -
    ("vendor/hyperframes-catalog/README.md", "boundary statement"),
    ("vendor/hyperframes-catalog/catalog-index.json", "the searchable index discovery loads"),
    ("vendor/hyperframes-catalog/hyperframes-catalog-lock.json", "provenance lock discovery validates"),
    ("vendor/hyperframes-catalog/compositions", "item HTML sources discovery reads for mechanism selection "
                                                "(the media and script files inside are withheld below)"),

    # --- B-roll lane descriptor (clips are the buyer's own) -----------------
    ("broll/README.md", "explains that the operator supplies b-roll"),
    ("broll/broll_catalog.json", "empty-by-design catalog the lane reads"),

    # --- Config template ----------------------------------------------------
    (".env.local.example", "safe configuration template, no secrets"),
)

# --------------------------------------------------------------------------
# WITHHOLD — each with the reason. "Withheld" is never "deleted upstream".
# --------------------------------------------------------------------------
EXCLUDE_DIRS: tuple[tuple[str, str], ...] = (
    ("artifacts", "459 GB of the owner's own footage, renders and app snapshots"),
    ("node_modules", "installed by the installer from the lockfile, never copied"),
    ("templates/motion/node_modules", "same; 371 MB"),
    ("templates/motion/.sniper-native-runtime", "23 GB machine cache; rebuilt from the "
                                                "shipped patch set by native_runtime.py"),
    ("templates/motion/renders", "7 GB of the owner's render output"),
    ("templates/motion/reference", "owner reference material, provenance unresolved"),
    ("templates/motion/container", "Docker/g2 container inputs; not the supported Mac route"),
    ("vendor/hyperframes-skills", "provenance-only archive; CLAUDE.md states it is not "
                                  "agent-discoverable and no code reads it; licence unverified"),
    ("vendor/hyperframes-catalog/assets", "catalog media (sfx, wallpapers, textures, fonts) "
                                          "is not read by discovery and its media terms are "
                                          "unverified"),
    ("vendor/hyperframes-catalog/compositions/assets",
     "catalog fonts (Barlow Condensed, Recursive and their OFL.txt) and the HyperFrames logo; "
     "graphics/catalog_discovery_sources.py reads only item HTML, the index and the lock, "
     "and no shipped composition loads them"),
    ("vendor/hyperframes-catalog/compositions/lib",
     "catalog script library (liquid-glass.iife.js); never read by discovery or loaded by a "
     "shipped composition; its terms were not reviewed"),
    ("scripts/producer/tests/.artifacts",
     "development screenshots of interface views left by a test run; not product"),
    ("docs/producer/evidence", "22 MB of the owner's render/audit evidence"),
    ("docs/audits", "internal development audits"),
    ("docs/studies/adrian-per", "study derived from paid teaching material, teacher-named"),
    ("docs/studies/shorts-visual-playbook",
     "creator-derived study (third-party Shorts, creator names); replaced by the original "
     "library in resources/references"),
    ("docs/studies/longform-visual-playbook",
     "creator-derived study; replaced by the original library in resources/references"),
    ("docs/marketing", "source of the buyer guides; the edited guides ship under manual/"),
    ("release", "maintainer release tooling"),
    ("scripts/producer/artifacts", "maintainer's retained acceptance evidence (gitignored)"),
    (".git", "history is not part of the product"),
    (".next", "build cache"),
    ("__pycache__", "byte cache"),
    (".pytest_cache", "test cache"),
    (".venv", "the installer creates the venv on the buyer's machine"),
)

EXCLUDE_GLOBS: tuple[tuple[str, str], ...] = (
    (".env", "secrets"),
    (".env.local", "secrets"),
    (".env.*.local", "secrets"),
    (".DS_Store", "Finder metadata"),
    ("*.pyc", "byte cache"),
    (".gitignore", "not part of the product"),
    (".mcp.json", "declares the palmier-pro MCP server; the optional integration is "
                  "not configured in the buyer package"),
    (".sniper-*", "machine-local control-plane state"),
    ("*.bundle", "git bundles"),
    ("docs/studies/GPT56_SOL_C0679_GAP_STUDY.md", "internal model-gap study"),
    ("vendor/hyperframes-catalog/compositions/components/*.png",
     "catalog texture images; discovery reads item HTML only and nothing renders them; "
     "their terms were not reviewed"),
    ("assets/fonts/ChunkFive-*", "ChunkFive and its licence: no longer used, the motion "
                                 "templates' display face is Bricolage Grotesque (tokens.css)"),
    ("public/file.svg", "create-next-app sample icon; nothing references it"),
    ("public/globe.svg", "create-next-app sample icon; nothing references it"),
    ("public/next.svg", "create-next-app sample logo (a third-party mark); nothing references it"),
    ("public/vercel.svg", "create-next-app sample logo (a third-party mark); nothing references it"),
    ("public/window.svg", "create-next-app sample icon; nothing references it"),
)

# --------------------------------------------------------------------------
# DENY — a match anywhere in the staged tree fails the build closed.
# Patterns describe shape, never a secret value; nothing here is printed.
# --------------------------------------------------------------------------
# Lengths are set above every real key prefix's minimum and well above the short
# fixtures the product's own tests use to prove the trace writer REFUSES a key
# (see scripts/producer/tests/test_attempt_trace.py). This is a shape scan with
# no entropy model: it catches a pasted credential, not an obfuscated one.
DENY_CONTENT: tuple[tuple[str, str], ...] = (
    (r"sk-ant-[A-Za-z0-9_\-]{32,}", "Anthropic API key"),
    (r"sk-proj-[A-Za-z0-9_\-]{32,}", "OpenAI project key"),
    (r"\bntn_[A-Za-z0-9]{24,}", "Notion token"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
    (r"ghp_[A-Za-z0-9]{28,}", "GitHub personal token"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----", "private key"),
    (r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.", "JWT"),
    (r"xox[abposr]-[A-Za-z0-9\-]{10,}", "Slack token"),
    # The maintainer's own home path. Generic fixtures like /Users/test and
    # /Users/me are deliberately NOT matched; this is an identity leak rule.
    (r"/Users/aaronfigueroa/", "maintainer home path"),
    # A downloaded third-party creator video referenced by URL is source material,
    # not a shippable component.
    # A real creator video id is long (YouTube/Instagram ~11 chars, TikTok ~19
    # digits). The 8-character floor keeps the URL-parser fixtures in
    # src/lib/producer/__tests__/reference-fetch-policy.test.ts ("…/shorts/abc")
    # out of the way while still catching a link to someone's actual video.
    (r"(?:instagram\.com/(?:reel|p)|youtube\.com/shorts|youtu\.be|tiktok\.com/@[^/\s]+/video)"
     r"/[A-Za-z0-9_-]{8,}",
     "third-party creator source URL (study material, not a shippable component)"),
)

DENY_PATH: tuple[tuple[str, str], ...] = (
    (r"(?i)(?:^|/)\.env(?:\.local)?$", "environment file with secrets"),
    (r"(?i)(?:^|/)id_(?:rsa|ed25519|ecdsa)$", "private ssh key"),
    (r"(?i)(?:^|/)\.netrc$", "credential file"),
    (r"(?i)(?:^|/)credentials?\.json$", "credential file"),
    (r"(?i)(?<![a-z0-9])(?:caleb|jadenly|jaden|angela|nateherk|nate[- ]herk|nate|mudrich|lewis|ralston|kallaway|hormozi|trevor|odom|wendt|adrian[_ -]?per|iampunch|personalbrandlaunch|world ?pet|pet achievers)(?![a-z0-9])",
     "teacher name in a shipped path (accepted decision: no teacher names in the product)"),
)

# Buyer-visible text must not carry these. Checked over the staged manual and
# guides only — source identifiers are handled by the separate rename migration.
DENY_BUYER_TEXT: tuple[tuple[str, str], ...] = (
    (r"(?i)first edit in (?:a few )?minutes", "unsupported speed claim"),
    (r"(?i)student[- ]kit", "meaningless internal term"),
    (r"(?i)hands[- ]off", "unsupported autonomy claim"),
    (r"(?i)about fifteen minutes|in (?:a few|fifteen) minutes", "unmeasured setup-time claim"),
    (r"(?i)nothing leaves your (?:computer|machine)", "false privacy claim"),
    (r"(?i)only the \*{0,2}text\*{0,2} .{0,40}is sent", "false privacy claim"),
    (r"(?i)(?<![a-z0-9])(?:caleb|jadenly|jaden|angela|nateherk|nate[- ]herk|nate|mudrich|lewis|ralston|kallaway|hormozi|trevor|odom|wendt|adrian[_ -]?per|iampunch|personalbrandlaunch|world ?pet|pet achievers)(?![a-z0-9])", "creator, course or client name"),
    (r"/Users/[A-Za-z0-9._-]+/", "developer machine path"),
    (r"\{[A-Z_]{3,}\}", "unresolved placeholder"),
)


# Teacher names in the TEXT of shipped source/docs. Recorded in the same pending
# class as the path rule: the accepted decision covers the distributed product,
# and these move only with the identifier migration in release/RENAME_SPEC.md.
DENY_SHIPPED_TEXT: tuple[tuple[str, str], ...] = (
    (r"(?i)(?<![a-z0-9])(?:caleb|jadenly|jaden|angela|nateherk|nate[- ]herk|nate|mudrich|lewis|ralston|kallaway|hormozi|trevor|odom|wendt|adrian[_ -]?per|iampunch|personalbrandlaunch|world ?pet|pet achievers)(?![a-z0-9])",
     "creator, course or client name in shipped text"),
)
