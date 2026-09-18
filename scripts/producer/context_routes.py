"""Progressive instruction and route links for the read-only Sniper context entry."""

BASE_READS = ("AGENTS.md", "docs/PIPELINE.md")
ROUTE_READS = {
    "overview": (),
    "code": ("CLAUDE.md", "scripts/producer/CLAUDE.md"),
    "producer": (".claude/skills/producer/SKILL.md",
                 "docs/producer/command-driven-editing/12_SHORT_LONG_EXECUTABLE_MATRIX.md"),
    "native": (".claude/skills/producer/SKILL.md",
               "docs/producer/NATIVE_PREBUILD_STRATEGY_2026-09-10.md",
               "docs/producer/NATIVE_PREFLIGHT.md",
               "docs/producer/STUDIO_REVIEW_LANE.md"),
    "native-short": (".claude/skills/producer/SKILL.md",
                     "docs/producer/NATIVE_SHORTS_WORKFLOW.md",
                     "docs/producer/NATIVE_PREBUILD_STRATEGY_2026-09-10.md",
                     "docs/producer/STUDIO_REVIEW_LANE.md"),
    "native-long": (".claude/skills/producer/SKILL.md",
                    "docs/producer/NATIVE_LONG_EXPORT.md",
                    "docs/producer/NATIVE_LONG_SELECTED_SOURCES.md",
                    "docs/producer/NATIVE_PREBUILD_STRATEGY_2026-09-10.md",
                    "docs/producer/STUDIO_REVIEW_LANE.md"),
}

COMMANDS = {
    "catalogSearch": "python3 scripts/producer/graphics/catalog_discovery_cli.py --format text search 'your visual need'",
    "catalogInventory": "python3 scripts/producer/graphics/catalog_discovery_cli.py inventory",
    "nativeExportHelp": "python3 scripts/producer/studio/native_export.py --help",
    "nativePreview": "python3 scripts/producer/studio/managed_preview.py open /absolute/native-project",
    "legacyStudioContext": "python3 scripts/producer/studio/studio_review.py context /absolute/producer-dir",
}

REVIEW_REQUIREMENTS = (
    "Read the selected route and its applicable references before dependent work.",
    "For produced evidence-rich edits, scout real assets and obtain independent strategy review before assembly.",
    "A native export needs the current complete-project prebuild review and shared supervised exporter.",
    "Review encoded picture, continuous motion, source correspondence and sound; technical checks do not certify listening.",
    "Default video handoff includes both checked local MP4 playback and the matching live editable Studio project.",
    "Existing reviews are historical claims until their bindings and actual required checks are verified.",
)

PROJECT_FILES = (
    "AGENTS.md", "CLAUDE.md", "BRIEF.md", "WORKING-NOTES.md", "next.md", "HANDOFF.md",
    "README.md", "STORYBOARD.md", "SCRIPT.md", "project.json", "index.html",
    "hyperframes.json", "LONG-PROJECT.json", "SHORT-PROJECT.json", "plan.json",
    "edit_plan.json", "asset_manifest.json", "PREBUILD-REVIEW.json", "delivery.json",
    "FINAL-HANDOFF-QA.json", "LIVE-REVIEW.json", ".sniper-auto-edit-job.json",
    "producer/edit_plan.json", "producer/asset_manifest.json",
)
