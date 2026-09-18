"""Original content of the packaged reference library (`resources/references`).

Authored for Project Sniper on 2026-09-18. Every case, lesson, beat and on-screen
string below was written for this library; topics and numbers are illustrations,
not anyone's results or words. `release/reference_library_writer.py` renders each
beat from Sniper's own motion templates and records the template, variables and
time beside every frame. Nothing here sets a colour: frames take palette and type
from the current templates, so a template redesign needs only a re-render. Every
visible text variable is set here, so no template default copy reaches a frame.

Identifier families (stable; consumers name some of them):
    SQnn  sequence case: several beats of one idea, may change composition
    DVnn  development case: one composition developing across beats
    MEnn  single-mechanism entry
    LGnn  long-form (16:9) case
Beat IDs are ``<case>-Bnn``.

Sequence beat tuple: (beat, spoken idea, what is visible, why this picture,
variables, frame times[, composition]). Development and long-form beat tuple:
(beat, idea, variables, frame times). Frame times follow each template's default
narration-paced land times, so every beat shows its own state settling.
"""
from __future__ import annotations

VERSION = "2026-09-18.1"

_SCOOP_BOARD = {"eyebrow": "Ten scoops, one spoon", "contextChips": "SAME BAG|SAME SPOON|KITCHEN SCALE",
                "heroValue": "7–11 g", "heroLabel": "RANGE ACROSS TEN SCOOPS",
                "tiles": "7 g~LIGHTEST|11 g~HEAVIEST|10~SCOOPS WEIGHED", "stripChips": "", "limitText": ""}
_ROUTES = {"eyebrow": "Five trips each", "headlineLines": "Old route or new?|Same start, same hour",
           "heroLabel": "NEW ROUTE", "heroValue": "26 min", "heroPct": "76",
           "compareLabel": "OLD ROUTE", "compareValue": "34 min", "comparePct": "100",
           "deltaChip": "8 MIN SHORTER", "chips": "SAME START|SAME HOUR|FIVE TRIPS EACH",
           "evidenceSource": "", "evidenceDate": ""}
_EDIT_HOUR = {"eyebrow": "One edit, timed", "headlineLines": "Where the hour goes|when I edit a Short",
              "explainer": "1 cutting · 2 captions · 3 export · 4 colour", "axisLabel": "MINUTES",
              "bars": "1~22 min~100|2~18 min~82|3~12 min~55|4~8 min~36",
              "verdict": "Captions take almost as long as cutting", "spectrum": ""}
_QUOTE_CHECKS = {"eyebrow": "Before you send a quote", "headlineLines": "Four checks|before you hit send",
                 "explainer": "", "contentMode": "checklist",
                 "rows": "1~Scope in writing~OK|2~Start date agreed~OK|3~Deposit stated~OK|4~What is not included~OK",
                 "footChip": "READY TO SEND", "footAccent": "result", "evidenceSource": "", "evidenceDate": ""}

SEQUENCES: tuple[dict, ...] = (
    {
        "id": "SQ01",
        "title": "State the claim, then show the measured spread and its limit",
        "lesson": ("A claim earns belief when the measurement behind it follows at once, with what was and was "
                   "not measured visible on the same screen."),
        "opening": "The claim alone, as one short statement with one accented word.",
        "story_arc": "Claim → the measured range and what was counted → the limit of the measurement.",
        "payoff": "The viewer sees the spread that supports the claim and the conditions it was measured under.",
        "composition": "module-scoreboard",
        "catalog": ["statement-card", "module-scoreboard", "stat-card"],
        "beats": [
            ("B01", "A scoop is not a measurement.",
             "One statement on its own, the key word accented.",
             "The claim is short enough to read in one glance before any evidence arrives.",
             {"text": "A scoop is not a *measurement*", "bg": "dark", "variant": "classic", "eyebrow": "",
              "iconFile": "", "headlineLines": "", "statements": "", "evidenceSource": "", "evidenceDate": ""},
             (0.4, 1.2, 2.4), "statement-card"),
            ("B02", "I weighed ten scoops from the same bag. They ranged from seven to eleven grams.",
             "The range lands as the hero figure; the lightest, the heaviest and the count arrive as tiles.",
             "The spread is the evidence, and the tiles say exactly what was counted.",
             dict(_SCOOP_BOARD), (0.6, 1.4, 2.6)),
            ("B03", "That is one spoon and one bag, so yours will differ. It will not be zero.",
             "The same board gains a limit footer naming the spoon and the bag.",
             "Putting the limit on screen stops one kitchen's numbers from reading as a universal result.",
             {**_SCOOP_BOARD, "limitLabel": "LIMIT", "limitText": "One spoon, one bag of beans; yours will differ"},
             (2.4, 3.4, 5.0)),
        ],
    },
    {
        "id": "SQ02",
        "title": "Let both bars land before naming the difference",
        "lesson": ("When two measured values are compared, show both before stating the difference, then show "
                   "the conditions that make the comparison fair."),
        "opening": "A two-line headline asks which option is faster; no bars yet.",
        "story_arc": "Question → both measured bars → the difference → the conditions both options shared.",
        "payoff": "The viewer reads the difference and knows the comparison was like for like.",
        "composition": "module-takeover",
        "catalog": ["module-takeover", "module-bullet-bars", "stat-card"],
        "beats": [
            ("B01", "Is the new route actually faster?",
             "The headline and its eyebrow, with the bar area still empty.",
             "Asking before answering gives the bars a question to settle.",
             dict(_ROUTES), (0.3, 0.6, 0.9)),
            ("B02", "Five trips each: thirty-four minutes the old way, twenty-six the new way.",
             "Both bars grow to their measured values; the difference is not shown yet.",
             "Seeing both values first lets the viewer judge the gap before hearing it.",
             dict(_ROUTES), (1.2, 1.7, 2.2)),
            ("B03", "Eight minutes shorter, from the same start at the same hour.",
             "The difference chip and the three shared conditions land last.",
             "The conditions come last because they are what makes the difference trustworthy.",
             dict(_ROUTES), (2.2, 3.0, 4.5)),
        ],
    },
    {
        "id": "SQ03",
        "title": "Rank every part on one axis before naming the largest",
        "lesson": ("When a total is broken into parts, put every part on one axis first and name the largest only "
                   "after the viewer can see that it is the largest."),
        "opening": "The headline names the total being broken down, with a one-line key to the parts.",
        "story_arc": "The hour → four parts on one axis → the verdict on the part worth fixing.",
        "payoff": "The viewer sees which part is largest before the speaker says so.",
        "composition": "module-bullet-bars",
        "catalog": ["module-bullet-bars", "module-ledger-dark", "module-takeover"],
        "beats": [
            ("B01", "Here is where one hour of editing goes.",
             "The headline and the key, before any bar.",
             "Naming the total first tells the viewer what the bars will add up to.",
             dict(_EDIT_HOUR), (0.3, 0.6, 1.0)),
            ("B02", "Twenty-two minutes cutting, eighteen on captions, twelve exporting, eight on colour.",
             "Four numbered bars grow on one axis, each value landing with its bar tip; a one-line key names the parts.",
             "A shared axis makes the ranking visible without any extra labels.",
             dict(_EDIT_HOUR), (1.2, 1.8, 2.6)),
            ("B03", "Captions take almost as long as the cut itself.",
             "The verdict line lands under the finished bars.",
             "The verdict names what the bars already show, so it confirms rather than asserts.",
             dict(_EDIT_HOUR), (2.2, 2.9, 4.2)),
        ],
    },
    {
        "id": "SQ04",
        "title": "Grow the checklist one row per spoken check, then mark it done",
        "lesson": ("A checklist the speaker walks through should gain one row per spoken check, keep earlier rows "
                   "in place and end on an explicit finished state."),
        "opening": "The headline says what the checklist is for.",
        "story_arc": "Purpose → four checks, one per sentence → the finished state.",
        "payoff": "The complete list stays readable and ends on a clear finished state.",
        "composition": "module-rail",
        "catalog": ["module-rail", "glass-rail", "list-build"],
        "beats": [
            ("B01", "Four checks before you send a quote. First, the scope in writing.",
             "The headline, then the first checklist row with its badge.",
             "The first row arrives with the first check, so the list and the speech stay together.",
             dict(_QUOTE_CHECKS), (0.4, 0.9, 1.4)),
            ("B02", "Then the start date, agreed with the client.",
             "The second row lands under the first.",
             "Earlier rows stay put, so the viewer sees the list accumulate.",
             dict(_QUOTE_CHECKS), (1.7, 2.1, 2.5)),
            ("B03", "The deposit, stated as an amount. And what the price does not include.",
             "The third and fourth rows land in turn.",
             "One row per spoken check, even when two checks come in one breath.",
             dict(_QUOTE_CHECKS), (2.8, 3.4, 4.1)),
            ("B04", "Then it is ready to send.",
             "A footer tag marks the list finished.",
             "An explicit finished state tells the viewer the list is complete, not cut off.",
             dict(_QUOTE_CHECKS), (4.6, 5.4, 6.6)),
        ],
    },
)

_DESK = {"eyebrow": "Before the first task", "num1": "1", "title1": "Clear the desk", "sub1": "Only today's work stays out",
         "num2": "2", "title2": "Pick one task", "sub2": "Write it where you can see it",
         "num3": "3", "title3": "Start a timer", "sub3": "Twenty-five minutes, phone in a drawer",
         "title4": "", "title5": "", "title6": "", "rowLands": "0.4|1.6|2.8", "side": "left"}
_DECK = {"header": "REHEARSE A TALK", "headerInk": "white",
         "slide1": "Read it aloud once|Time every section",
         "slide2": "Cut what you skipped|Rework where you stumbled",
         "slide3": "Say it to one person|Watch where they look away",
         "pill1": "Part 1", "pill2": "Part 2", "pill3": "Part 3", "pageAt2": 2.0, "pageAt3": 4.0}

EXPANSION: tuple[dict, ...] = (
    {
        "id": "DV01",
        "title": "Reveal each point beside the speaker on the word that names it",
        "message": ("A routine of three or four points is easiest to follow when each point appears as it is "
                    "spoken and the earlier points stay visible beside the speaker."),
        "arc": "Eyebrow → point one → point two → point three, then the full rail held.",
        "execution": ("Set one land time per row from its spoken cue, keep the rail on the side away from the "
                      "speaker, and hold the full rail through the last sentence."),
        "avoid": "Rows that land on a fixed rhythm ahead of the speech, or more rows than a side rail can show at phone size.",
        "typography": "Short titles with an optional one-line subtitle; numbers live in the chips, not the titles.",
        "composition": "glass-rail",
        "catalog": ["glass-rail", "module-rail", "list-build"],
        "beats": [
            ("B01", "First, clear the desk.", dict(_DESK), (0.5, 0.9, 1.4)),
            ("B02", "Then pick one task and write it down.", dict(_DESK), (1.7, 2.1, 2.6)),
            ("B03", "Then start a timer and put the phone away.", dict(_DESK), (2.9, 3.3, 3.8)),
        ],
    },
    {
        "id": "DV02",
        "title": "Turn one page per step of the argument",
        "message": ("A three-part argument reads well as a short deck: one page per part, a constant header and a "
                    "caption pill that says which part the viewer is on."),
        "arc": "Header and page one → page two → page three.",
        "execution": ("Keep the header fixed, turn the page on the spoken transition, and put no more than two "
                      "short rows on a page."),
        "avoid": "Pages that turn before the speaker finishes the point, or pages with more than two rows.",
        "typography": "An all-caps header of three words or fewer; rows of two to five words.",
        "composition": "slideware-takeover-deck",
        "catalog": ["slideware-takeover-deck", "statement-card", "module-rail"],
        "beats": [
            ("B01", "First, read it aloud once and time every section.", dict(_DECK), (0.5, 1.0, 1.7)),
            ("B02", "Then cut what you skipped and rework where you stumbled.", dict(_DECK), (2.3, 2.8, 3.6)),
            ("B03", "Finally, say it to one person and watch where they look away.", dict(_DECK), (4.3, 4.9, 5.7)),
        ],
    },
)

ENTRIES: tuple[dict, ...] = (
    {
        "id": "ME01",
        "title": "A short rule as one typographic lockup",
        "story_job": "Give a rule the speaker stresses a single, memorable visual form above the speaker.",
        "use_when": "The speaker states a rule of two to four words and stresses or repeats it.",
        "do_not_use_when": "The rule needs a qualification to be true, or another text layer already occupies the frame.",
        "composition": "punch-shout-lockup",
        "vars": {"kicker": "the rule is", "payload": "MEASURE", "coword": "first", "kicker2": ""},
        "times": (0.1, 0.5, 1.5),
    },
    {
        "id": "ME02",
        "title": "List the items, then the total they make",
        "story_job": "Make a total believable by showing the items it is made of.",
        "use_when": "The speaker adds up a handful of items and states the total.",
        "do_not_use_when": "The items are estimates shown as exact amounts, or there are more than six of them.",
        "composition": "module-ledger-dark",
        "vars": {"eyebrow": "One week of lunches", "headlineLines": "Five lunches|add up fast", "explainer": "",
                 "barLabel": "WEEK TOTAL", "barValue": "$62", "barStatus": "",
                 "rows": ("Monday~$12~LUNCH~process|Tuesday~$14~LUNCH~process|Wednesday~$11~LUNCH~process|"
                          "Thursday~$13~LUNCH~process|Friday~$12~LUNCH~process"),
                 "gridItems": "", "footChip": ""},
        "times": (0.5, 2.4, 5.0),
    },
    {
        "id": "ME03",
        "title": "Mark the start of a new part",
        "story_job": "Tell the viewer the Short has moved on to its next part.",
        "use_when": "The speaker clearly moves from one part to the next, for example from the problem to the fix.",
        "do_not_use_when": "The Short has only one part, or the marker would cover the speaker's face.",
        "composition": "section-marker",
        "vars": {"num": "Part 2", "line1": "The fix", "line2": "", "side": "left"},
        "times": (0.3, 0.9, 2.0),
    },
)

_CHAPTERS = {"eyebrow": "Chapters", "headlineLines": "Fix one thing|at a time", "explainer": "",
             "contentMode": "timeline", "footChip": "", "evidenceSource": "", "evidenceDate": ""}

LONGFORM: tuple[dict, ...] = (
    {
        "id": "LG01",
        "title": "A chapter timeline that fills in as the video advances",
        "status": "original-reference",
        "summary": ("In a long video, a vertical timeline of chapters with the finished ones marked tells a viewer "
                    "who joined late, or drifted, where the argument is and what remains."),
        "composition": "module-rail",
        "beats": [
            ("B01", "That was chapter one. Next, change one thing at a time.",
             {**_CHAPTERS, "rows": "01~Measure what you have~result|02~Change one thing~process|03~Measure again~process"},
             (1.0, 2.5, 4.0)),
            ("B02", "Two chapters done. Last, measure again the same way.",
             {**_CHAPTERS, "rows": "01~Measure what you have~result|02~Change one thing~result|03~Measure again~process"},
             (1.0, 2.5, 4.0)),
        ],
    },
)
