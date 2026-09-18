# Director training pairs — solution-aware viewers

The viewer already knows fixes exist and is comparing them, or doubts the one they
use. Openings for this viewer name the options, test a belief about a fix or show
a fix working; they do not need to establish the problem. Recordings and numbers
were written for Project Sniper on 2026-09-18 as teaching material; they are not
real people or real results. Never reuse an output as copy.

### T707

- Viewer start: solution_aware — they plan with either a paper planner or a calendar app and wonder whether to switch.
- Recording: "Paper planner or calendar app? I used both for a month. The app won for reminders; paper won for weekly planning, because I actually looked at it."
- Format: `side_by_side`. Rejected `lived_moment`: the month is the method, not a story with a turn.
- Anchor: `compare-two-options`, using this entry's formula. Rejected `compare-when-each`: the speaker judges one job, weekly planning, more than the other.
- Slots: first option ← "Paper planner"; second option ← "calendar app"; job ← "weekly planning".
- Output: "Paper planner or calendar app for weekly planning?"
- Rejected fill: "The best planner for you" — hides both options and claims a universal best.
- Criteria: supportedClaim is a question, answered only for one person's month; answerablePromise is answered by "paper won for weekly planning"; viewerStake is a viewer choosing tools; concreteDetail names both tools; channelAgreement needs both objects in the first picture if filmed; glanceReadable is eight words.

### T708

- Viewer start: solution_aware — they feed their tomato plants and the leaves stay pale.
- Recording: "More fertiliser won't fix pale tomato leaves when the soil is still cold. I waited until the bed warmed up and the new leaves came in darker."
- Format: `assumption_check`. Rejected `one_change`: the belief that more feed helps is what the speaker tests.
- Anchor: `assumption-more-wont`. Rejected `moment-what-changed`: the recording's point is the misplaced fix.
- Slots: thing ← "fertiliser"; problem ← "pale tomato leaves".
- Output: "More fertiliser won't fix pale tomato leaves"
- Rejected fill: "Stop feeding your tomatoes" — the speaker never says to stop.
- Criteria: supportedClaim keeps the condition "when the soil is still cold" for the payoff; answerablePromise is answered by waiting for warmer soil; viewerStake is pale plants despite effort; concreteDetail is "pale tomato leaves"; channelAgreement needs the pale leaves in the first picture when filmed; glanceReadable is seven words.

### T709

- Viewer start: solution_aware — they know their audio is echoey and have looked at buying a new microphone.
- Recording: "Two steps to cleaner audio in ten minutes: move the mic closer to your mouth, then hang a blanket behind you."
- Format: `ordered_steps`. Rejected `side_by_side`: no microphones are compared.
- Anchor: `steps-toward-goal` with the optional timeframe clause, because a timeframe is spoken. Rejected `assumption-no-need`: the speaker never says a new microphone is unnecessary.
- Slots: count ← "Two", written as "2"; goal ← "cleaner audio"; timeframe ← "ten minutes".
- Output: "2 steps to cleaner audio (in ten minutes)"
- Rejected fill: "Pro audio without buying anything" — "pro" is unsupported and the blanket may have to be found or bought.
- Criteria: supportedClaim keeps the speaker's ten minutes; answerablePromise is answered by the two steps; viewerStake is echo the viewer already hears; concreteDetail is the step count and time; channelAgreement needs the mic position visible early; glanceReadable is seven words.

### T710

- Viewer start: solution_aware — they believe they already back up their files.
- Recording: "A backup isn't a copy in the same folder. If the drive fails, both copies go with it. It has to live on a different device."
- Format: `plain_definition`. Rejected `mistake_and_fix`: the misunderstanding of the term is the whole point.
- Anchor: `define-is-not`, using this entry's formula. Rejected `mistake-looks-right`: no hidden technical problem is revealed, only a definition.
- Slots: term ← "backup"; misreading ← "a copy in the same folder".
- Output: "A backup isn't a copy in the same folder"
- Rejected fill: "You're losing your files" — asserts a loss that has not happened.
- Criteria: supportedClaim uses the speaker's definition only; answerablePromise is answered by "a different device"; viewerStake is files the viewer thinks are safe; concreteDetail is "the same folder"; channelAgreement pairs the written line with the spoken first sentence; glanceReadable is nine words on two lines.

### T711

- Viewer start: solution_aware — they already use invoice templates and wonder whether it is worth setting one up properly.
- Recording: "Watch this: with the template set up, an invoice takes me forty seconds from blank to sent."
- Format: `live_demonstration`. Rejected `worked_numbers`: there is no calculation, only a timed operation.
- Anchor: `result-in-duration`. Rejected `number-took-not`: no expected figure is spoken.
- Slots: task ← "an invoice", written as "An invoice"; duration ← "forty seconds", written as "40 seconds".
- Output: "An invoice in 40 seconds"
- Rejected fill: "Never waste time on invoices again" — an absolute promise the recording cannot support.
- Criteria: supportedClaim holds only if the retained footage runs in real time; if it was sped up or trimmed, this fill fails and the anchor is disqualified; answerablePromise is answered by the timed operation; viewerStake is time spent on each invoice; concreteDetail is forty seconds; channelAgreement needs the blank invoice as the first picture; glanceReadable is five words.

### T712

- Viewer start: solution_aware — they keep their books in a spreadsheet and hear that they should move to an accounting app.
- Recording: "Use a spreadsheet while the numbers change weekly. Once you send more than ten invoices a month, an accounting app starts to save you time."
- Format: `side_by_side`. Rejected `assumption_check`: the speaker does not say either option is wrong.
- Anchor: `compare-when-each`. Rejected `compare-two-options`: the speaker gives a condition for each option rather than one winner.
- Slots: first option ← "a spreadsheet"; second option ← "an accounting app", written as "an app".
- Output: "When to use a spreadsheet, when to use an app"
- Rejected fill: "Spreadsheets are holding you back" — contradicts the first half of the recording.
- Criteria: supportedClaim keeps both conditions for the payoff; answerablePromise is answered by the ten-invoice threshold; viewerStake is a viewer deciding whether to switch; concreteDetail arrives in the payoff, so this fill relies on the named tools, and a fill that includes "10 invoices a month" is worth comparing; channelAgreement needs both tools on screen early; glanceReadable is ten words on two lines.
