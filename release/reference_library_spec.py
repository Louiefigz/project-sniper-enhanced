"""Original reference library: cases, beats and the renders that illustrate them.

Data catalog (exempt from the logic-file line limit). Every picture in the packaged
library is rendered from one of Project Sniper's own motion templates with copy written
here, at a recorded time. No footage, screenshot, brand or likeness of any third party
is used, and no creator is named. `release/build_reference_library.py` turns this spec
into `resources/references/`.

A beat's `render` is (composition, variable overrides, three times in seconds). The
three frames show the mechanism developing: start, middle, settled.
"""
from __future__ import annotations

VERSION = "2026-09-17.1"
ACCENT = "#054BC9"

# ---------------------------------------------------------------- sequences (N)
SEQUENCES: tuple[dict, ...] = (
    {
        "id": "N26",
        "title": "Change the route, keep the destination",
        "lesson": "When the speaker compares ways of reaching one goal, keep the goal fixed on "
                  "screen and change only the route, so the viewer compares like with like.",
        "opening": "The destination is named and placed first, before any route appears.",
        "story_arc": "goal fixed -> first route -> its cost -> second route -> its cost -> "
                     "the route the speaker recommends -> hand back to the speaker",
        "payoff": "The recommended route is the last one drawn and the only one still lit.",
        "beats": [
            ("B01", "The goal is stated", "Title appears alone.",
             "Name the destination before any option exists.",
             {"title": "Get the first client", "node1": "", "node2": "", "node3": "", "node4": ""},
             (0.2, 0.6, 1.0)),
            ("B02", "First route: cold outreach", "First node joins the fixed title.",
             "One option at a time; the goal stays where it was.",
             {"title": "Get the first client", "node1": "Cold outreach"}, (0.4, 0.8, 1.2)),
            ("B03", "What the first route costs", "Second node describes the cost.",
             "Attach the cost to the route, not to a separate slide.",
             {"title": "Get the first client", "node1": "Cold outreach", "node2": "Weeks of silence"},
             (1.0, 1.5, 2.0)),
            ("B04", "Second route: referrals", "Third node adds the alternative.",
             "The alternative arrives in the same frame as the first route.",
             {"title": "Get the first client", "node1": "Cold outreach", "node2": "Weeks of silence",
              "node3": "Ask past colleagues"}, (1.9, 2.4, 2.9)),
            ("B05", "Keep the destination while the route changes",
             "The fourth node completes the comparison under the unchanged title.",
             "The title never moves, so every node reads as a way to the same goal.",
             {"title": "Get the first client", "node1": "Cold outreach", "node2": "Weeks of silence",
              "node3": "Ask past colleagues", "node4": "First call this week"}, (2.6, 3.4, 4.2)),
            ("B06", "The recommendation is named", "Handoff text appears.",
             "State the choice in words once the picture has made the case.",
             {"title": "Get the first client", "node1": "Cold outreach", "node2": "Weeks of silence",
              "node3": "Ask past colleagues", "node4": "First call this week",
              "handoffText": "Start with who already trusts you", "handoffAt": 4.4}, (4.5, 5.0, 5.5)),
            ("B07", "Hold the finished map", "Everything is on screen; nothing moves.",
             "Give the viewer time to read the whole comparison.",
             {"title": "Get the first client", "node1": "Cold outreach", "node2": "Weeks of silence",
              "node3": "Ask past colleagues", "node4": "First call this week",
              "handoffText": "Start with who already trusts you", "handoffAt": 4.4}, (5.6, 6.1, 6.6)),
            ("B08", "A shorter variant for a tighter Short",
             "Two routes only, same fixed destination.",
             "When time is short, cut to the two routes that differ most.",
             {"title": "Get the first client", "node1": "Cold outreach", "node2": "Ask past colleagues",
              "node3": "", "node4": ""}, (0.6, 1.2, 1.8)),
            ("B09", "A different goal, same method",
             "The mechanism reused for a different destination.",
             "The method transfers; only the destination and routes change.",
             {"title": "Finish the first draft", "node1": "Write every day", "node2": "Write one long session",
              "node3": "Outline first", "node4": "Done by Friday"}, (2.6, 3.4, 4.2)),
        ],
        "composition": "whiteboard-map",
        "catalog": ["whiteboard-map", "module-rail", "glass-rail"],
    },
    {
        "id": "N27",
        "title": "Show value growing against time",
        "lesson": "When the claim is about how much something gains over time, show the amount "
                  "and the time together so the viewer sees the rate, not just the total.",
        "opening": "The starting value appears before any growth.",
        "story_arc": "starting value -> the number climbs -> the time bar fills -> the "
                     "comparison chart settles -> hand back",
        "payoff": "The final chart holds with the largest bar emphasised.",
        "beats": [
            ("B01", "The number climbs", "A counter rises to the stated figure.",
             "Let the number arrive; do not start on the total.",
             {"start": 0, "end": 43, "prefix": "", "suffix": " subscribers"}, (0.1, 1.2, 2.8), "count-up"),
            ("B02", "Time passes on the same screen", "A marker advances along a labelled bar.",
             "Pair the gain with the time it took.",
             {"label": "Days since posting"}, (0.4, 2.0, 3.9), "widget-gauge"),
            ("B03", "Compare periods", "Bars grow period by period and the last is emphasised.",
             "A comparison makes the rate readable at a glance.",
             {"data": "4, 11, 19, 43", "labels": "Day 1, Day 2, Day 4, Day 6", "emphasize": 3,
              "unit": ""}, (0.6, 2.2, 4.6), "chart-story"),
        ],
        "composition": "count-up",
        "catalog": ["count-up", "widget-gauge", "chart-story", "stat-card"],
    },
    {
        "id": "N10",
        "title": "Mark the one word that carries the point",
        "lesson": "When a sentence on screen has one word that matters, draw attention to that "
                  "word after the sentence has been read, not before.",
        "opening": "The full sentence appears unmarked.",
        "story_arc": "sentence read -> emphasis drawn on one word -> hold",
        "payoff": "The emphasised word is the last thing that changes.",
        "beats": [
            ("B01", "Read the sentence first", "The line appears plain.",
             "The viewer needs the whole thought before the emphasis means anything.",
             {"text": "The first line does the heavy lifting", "emphasisWord": "first line"},
             (0.3, 0.6, 0.85)),
            ("B14", "Focus the relevant detail", "A highlight is drawn behind the key phrase.",
             "Emphasis arrives after reading, on the phrase the speaker stresses.",
             {"text": "The first line does the heavy lifting", "emphasisWord": "first line"},
             (1.0, 1.6, 3.2)),
        ],
        "composition": "marker-highlight",
        "catalog": ["marker-highlight", "underline-circle", "hw-callout-circle"],
    },
    {
        "id": "N04",
        "title": "Zoom to the control that matters",
        "lesson": "When the speaker refers to one part of a busy screen, move the view to that "
                  "part instead of asking the viewer to find it.",
        "opening": "The whole screen is shown briefly so the viewer knows where they are.",
        "story_arc": "whole screen -> push in on the relevant control -> hold on it",
        "payoff": "The control fills the frame, with a halo marking it.",
        "beats": [
            ("B13", "Focus a relevant control", "The view pushes in on one region of the screen.",
             "Establish the whole screen, then move to the part being discussed.",
             {"anchorX": 57, "anchorY": 63, "zoom": 1.9, "zoomAt": 1.2}, (0.3, 1.6, 3.6)),
        ],
        "composition": "ui-focus-zoom",
        "catalog": ["ui-focus-zoom", "marker-highlight"],
        "needs_image": True,
    },
)

# ------------------------------------------------------------ expansion (CR, LM)
EXPANSION: tuple[dict, ...] = (
    {
        "id": "CR07",
        "title": "Problem, solution, idea, angles — then back to the speaker",
        "message": "A single diagram that develops from the problem to the options, so the "
                   "viewer holds the whole argument in one picture.",
        "arc": "problem -> solution -> the idea -> angles on it -> return to the speaker",
        "execution": "Build the nodes in the order the speaker says them; light only the node "
                     "being discussed; return to the presenter when the diagram is complete.",
        "avoid": "Showing every node at once, or leaving the diagram up after the speaker moves on.",
        "typography": "Short node labels; one headline; no paragraph text in nodes.",
        "beats": [
            ("B01", "Name the problem", {"headlineLines": "Why posts get|no replies",
             "nodes": "1~Ends on a statement|2~Ask one question|3~Make it answerable|4~Reply within the hour",
             "activeIndex": 1}, (0.6, 1.4, 2.2)),
            ("B02", "Offer the solution", {"headlineLines": "Why posts get|no replies",
             "nodes": "1~Ends on a statement|2~Ask one question|3~Make it answerable|4~Reply within the hour",
             "activeIndex": 2}, (2.0, 2.8, 3.6)),
            ("B03", "Develop the idea", {"headlineLines": "Why posts get|no replies",
             "nodes": "1~Ends on a statement|2~Ask one question|3~Make it answerable|4~Reply within the hour",
             "activeIndex": 3}, (3.4, 4.2, 5.0)),
            ("B04", "Add the angles, then hand back", {"headlineLines": "Why posts get|no replies",
             "nodes": "1~Ends on a statement|2~Ask one question|3~Make it answerable|4~Reply within the hour",
             "activeIndex": 4}, (5.0, 6.2, 7.6)),
        ],
        "composition": "module-pipeline",
        "catalog": ["module-pipeline", "module-rail", "list-build"],
    },
    {
        "id": "LM06",
        "title": "Replace the headline on the same page",
        "message": "When the speaker corrects a common belief, keep the page and swap only the "
                   "line, so the change itself is the point.",
        "arc": "the common belief -> the swap -> the corrected line holds",
        "execution": "Hold the first line long enough to read, swap on the spoken turn, then "
                     "underline the word that changed the meaning.",
        "avoid": "Cutting to a new card; the continuity of the page is what makes it a correction.",
        "typography": "Two lines of equal size; the underline is the only accent.",
        "beats": [
            ("B01", "The belief", {"lineA": "You need a bigger audience",
             "lineB": "You need a clearer offer", "underlineWord": "clearer", "swapAt": 1.5},
             (0.3, 0.8, 1.3)),
            ("B02", "The correction", {"lineA": "You need a bigger audience",
             "lineB": "You need a clearer offer", "underlineWord": "clearer", "swapAt": 1.5},
             (1.6, 2.2, 3.2)),
        ],
        "composition": "line-swap",
        "catalog": ["line-swap", "statement-card"],
    },
)

# ------------------------------------------------------------------ entries (A)
ENTRIES: tuple[dict, ...] = (
    {"id": "A01", "title": "A numbered list that builds as it is spoken",
     "story_job": "Let the viewer count along with the speaker.",
     "use_when": "The speaker names three short, parallel items.",
     "do_not_use_when": "The items are long sentences, or not parallel.",
     "composition": "list-build",
     "vars": {"item1": "Write the promise", "item2": "Show the proof", "item3": "Ask one question"},
     "times": (0.4, 1.1, 2.6)},
    {"id": "A02", "title": "Before and after, side by side",
     "story_job": "Make a change visible by putting both states in one frame.",
     "use_when": "The speaker contrasts a before and an after with concrete details.",
     "do_not_use_when": "The 'after' is a claim the source does not support.",
     "composition": "versus-split",
     "vars": {"leftTitle": "Before", "rightTitle": "After", "left1": "Two-hour edit",
              "right1": "Forty minutes", "left2": "Every take reviewed", "right2": "Best takes first",
              "left3": "Guessing the cut", "right3": "Plan, then cut"},
     "times": (0.3, 1.1, 2.4)},
    {"id": "A03", "title": "One statement with one emphasis",
     "story_job": "Give a single line the whole screen when it is the thesis.",
     "use_when": "The line is the point the rest of the Short supports.",
     "do_not_use_when": "The line is setup rather than the thesis.",
     "composition": "statement-card",
     "vars": {"text": "Show the result *before* the method"},
     "times": (0.3, 1.2, 3.0)},
)

# ---------------------------------------------------------------- long-form (LF)
LONGFORM: tuple[dict, ...] = (
    {"id": "LF01", "title": "Chapter a long explanation into steps",
     "status": "original-reference",
     "summary": "For a long-form section with ordered steps, show the whole path once, then "
                "light one step at a time as the speaker reaches it.",
     "composition": "module-pipeline",
     "beats": [
         ("B01", "Show the whole path", {"headlineLines": "Plan a video|in four steps",
          "nodes": "1~Pick one viewer|2~Name their problem|3~Write the promise|4~Outline the proof",
          "activeIndex": 1}, (0.6, 1.8, 3.0)),
         ("B02", "Light the current step", {"headlineLines": "Plan a video|in four steps",
          "nodes": "1~Pick one viewer|2~Name their problem|3~Write the promise|4~Outline the proof",
          "activeIndex": 3}, (3.4, 4.4, 5.4)),
     ]},
)
