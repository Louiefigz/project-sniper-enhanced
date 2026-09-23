# Reference style-pack review schema

Read this file before authoring either review or the template registry. The
compiler is strict: receipts must remain bound to the exact worklist and source.

## Shared classification

Both independent reviews must fill the same classification fields for every
worklist item:

```json
{
  "kind": "stable|cut|motion|transition|graphic|panel|title-card|lower-third|data-viz|caption|broll|ui|other",
  "informationForm": "none|thesis|comparison|process|evidence|list|identity|credibility|chapter|quote|demonstration|decorative|other",
  "layoutFamily": "none|full-frame|beside-presenter|around-presenter|presenter-inset|lower-third|center-card|screen-takeover|split-screen|other",
  "transitionFamily": "none|hard-cut|match-cut|light-leak|matte-wipe|camera-whip|fade-through-color|graphic-bridge|other",
  "animationFamily": "none|step|pop|fade|sweep|stagger|draw-on|eased-scale|eased-slide|kinetic-type|other"
}
```

Use `none` when a field truly does not apply. Do not use an empty string,
`unknown`, or a guessed named template.

## Review receipt

Generate the skeleton with `reference_style_cli.py init-review`; do not calculate
hashes manually. Each row must become:

```json
{
  "itemId": "event-window-0001",
  "verdict": "pass",
  "materialIssues": [],
  "confidence": 0.92,
  "classification": { "kind": "graphic", "informationForm": "comparison", "layoutFamily": "beside-presenter", "transitionFamily": "none", "animationFamily": "stagger" },
  "observations": {}
}
```

### Mechanics observations

Record concrete evidence where applicable:

```json
{
  "presenterPlacement": "right",
  "graphicBBoxNorm": [0.03, 0.12, 0.46, 0.70],
  "entranceFrames": 8,
  "holdFrames": 74,
  "exitFrames": 6,
  "easing": "power3-out",
  "buildOrder": ["rail", "heading", "row-1", "row-2"],
  "typography": {"roles": ["eyebrow", "headline", "label"], "contrastPass": true},
  "palette": {"relationship": "dark-blue footage with cream rail and lime accent"},
  "occlusion": "clear",
  "transitionBoundary": {"before": "talking-head", "seam": "cream sweep", "after": "split layout"}
}
```

Use measured frame counts rather than adjectives such as “quick.” Describe
color relationships; never promote a reference creator's brand colors.

### Editorial observations

Record the content relationship:

```json
{
  "spokenBeat": "contrasts prompts with a complete system",
  "whyItExists": "makes the two alternatives simultaneously comparable",
  "copyRelationship": "faithful paraphrase of the kept words",
  "progression": "first bar lands on prompts; second extends on system",
  "reusableStructure": "two-row comparison with one highlighted winner",
  "templateRecommendation": {"decision": "reuse|build", "templateId": "comparison-bars"},
  "risks": []
}
```

Do not copy reference words, identities, logos, UI, claims, footage, or music.

## Adjudication

Initialize an adjudication receipt only when compilation reports disagreement.
Review the disputed full-frame sequences again. The receipt still covers every
worklist item because that preserves exact-set validation, but copy the agreed
classifications for undisputed rows and change only evidence-backed disputes.

## Template registry

Bind only reviewed graphic-family items. The registry must use the canonical
worklist hash printed into either review receipt:

```json
{
  "schemaVersion": 1,
  "worklistHash": "<exact worklistHash>",
  "bindings": [
    {
      "itemId": "event-window-0001",
      "status": "matched",
      "templateId": "module-bullet-bars",
      "proofPath": "/absolute/path/to/verified-settled-frame.jpg",
      "structureOnly": true
    }
  ]
}
```

`proofPath` must exist. `built` means a new catalog composition passed realistic
render, animation-phase inspection, and pixel/alpha proof. `matched` means an
existing template passed a side-by-side structure and animation comparison.
