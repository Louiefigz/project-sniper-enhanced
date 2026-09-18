# Director slot formulas

The formula index turns a reference or training example into exact slots. When the
Director selects an example that has a formula here, it must bind **every slot of
that formula** to contiguous retained words; an example without a formula uses the
named anchor's slots instead. `disqualify-if` names the source condition under
which the example must not be chosen, however close the topic looks.

Authored for Project Sniper on 2026-09-18 (see `README.md`). Every ID below has a
matching entry in `hook-references.md` or a training file.

### R501 · Habit with its consequence
- anchor: `situation-if-you`
- formula: "If you [habit], [consequence]"
- disqualify-if: the consequence is the Director's inference rather than the speaker's words, or the target viewer does not have the habit.

### R502 · Audience named by its symptom
- anchor: `situation-for-anyone-whose`
- formula: "For anyone whose [thing] [symptom]"
- disqualify-if: the symptom is not described in the retained cut, or the audience can only be named by job title.

### R503 · A check before an action
- anchor: `situation-before-you`
- formula: "Before you [action], check [thing] for [sign]"
- disqualify-if: the recording names no concrete sign to look for.

### R504 · Why an everyday observation happens
- anchor: `gap-cause-behind`
- formula: "Why do [things] [observation] first?"
- disqualify-if: the recording states the observation but not its cause, or the order ("first") is not part of what the speaker describes.

### R505 · A controlled change with a visible result
- anchor: `gap-what-happens-when`
- formula: "What happens when you [change] on [condition]?"
- disqualify-if: the result of the change is neither shown in the footage nor stated by the speaker.

### R506 · A quantity the viewer has dismissed
- anchor: `gap-how-much`
- formula: "How much [resource] does [small thing] waste?"
- disqualify-if: the recording contains no quantity with a unit, or the quantity depends on a measurement the speaker did not make.

### R507 · One missing element
- anchor: `gap-what-is-missing`
- formula: "What is missing from your [artifact]?"
- disqualify-if: the speaker names more than one missing element, or the viewer would not own the artifact.

### R508 · Counted steps to a named goal
- anchor: `steps-toward-goal`
- formula: "[count] steps to [goal]"
- disqualify-if: the steps are not counted in the recording, or the goal is an outcome the speaker does not show or state.

### R509 · An order with a reason
- anchor: `steps-order-matters`
- formula: "[first step] before you [second step]"
- disqualify-if: the speaker does not explain why the order matters.

### R510 · A bounded checklist
- anchor: `steps-checks-before`
- formula: "[count] checks before you [action]"
- disqualify-if: fewer than two checks survive in the retained cut.

### R511 · A small amount that adds up
- anchor: `number-adds-up`
- formula: "[small amount] a [period] is [total] a [longer period]"
- disqualify-if: the total is not spoken, the units change between the two amounts, or the speaker hedged ("about") and the hedge would be lost.

### R512 · A familiar number decoded
- anchor: `number-here-is-what`
- formula: "[number] [term]: here is what that means"
- disqualify-if: the recording does not explain what the number measures.

### R513 · Actual against expected
- anchor: `number-took-not`
- formula: "It took [actual], not [expected]"
- disqualify-if: either figure is missing from the speech.

### R514 · A recognisable mistake
- anchor: `mistake-you-might-be`
- formula: "You might be [mistake]"
- disqualify-if: the retained cut gives no fix.

### R515 · A mistake with a stated cost
- anchor: `mistake-can-cost`
- formula: "[mistake] can cost you [cost]"
- disqualify-if: the cost is not stated by the speaker.

### R516 · Looks right, then fails
- anchor: `mistake-looks-right`
- formula: "[thing] look [state], then [problem]"
- disqualify-if: the recording does not explain why the problem appears.

### R517 · A requirement removed
- anchor: `assumption-no-need`
- formula: "You don't need [requirement] for [goal]"
- disqualify-if: the speaker does not name or show the alternative.

### R518 · A rule that is only partly right
- anchor: `assumption-half-true`
- formula: "[rule]? Only half true"
- disqualify-if: the speaker does not say which part of the rule holds.

### R519 · Quantity is not the fix
- anchor: `assumption-more-wont`
- formula: "More [thing] won't fix [problem]"
- disqualify-if: the speaker does not name what does fix the problem.

### R520 · Two options, one job
- anchor: `compare-two-options`
- formula: "[first option] or [second option] for [purpose]?"
- disqualify-if: fewer than two comparison points are spoken.

### R521 · The same thing done two ways
- anchor: `compare-same-task`
- formula: "Same [thing], two [variants]"
- disqualify-if: only one version is in the recording.

### R522 · One day with a concrete detail
- anchor: `moment-the-day`
- formula: "The day [event]"
- disqualify-if: the event has no concrete detail in the recording.

### R523 · A first-person observation
- anchor: `moment-i-noticed`
- formula: "I noticed [observation] when I [action]"
- disqualify-if: the observation is not the speaker's own.

### R524 · A term answered plainly
- anchor: `define-what-means`
- formula: "What [term] actually means"
- disqualify-if: the recording uses the term without defining it.

### R525 · A hidden setting located
- anchor: `result-where-to-find`
- formula: "Where to find [setting] in [place]"
- disqualify-if: the setting is not visible and legible in the screen recording.

### T701 · Symptom with its usual cause
- anchor: `situation-if-you`
- formula: "If your [thing] comes out [symptom], it's usually [cause]"
- disqualify-if: the speaker names no cause, or names several without saying which is usual.

### T704 · Daily amount against a yearly total
- anchor: `number-adds-up`
- formula: "[daily amount] a day is [yearly total] a year"
- disqualify-if: the yearly total is not spoken by the speaker.

### T707 · Two tools for one job
- anchor: `compare-two-options`
- formula: "[first option] or [second option] for [job]?"
- disqualify-if: the speaker does not say which option wins for that job.

### T710 · A term against its misreading
- anchor: `define-is-not`
- formula: "A [term] isn't [misreading]"
- disqualify-if: the misreading is not stated in the recording.
