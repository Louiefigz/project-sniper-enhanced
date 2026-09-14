# Template compliance is not a strong hook

Aaron liked the WildFireVlog3 offer Short's visual storytelling and actual dog
footage, but rejected its hook: “Use this offer formula to get specific.” That
sentence correctly filled the canonical `value-formula` template and passed its
layout checks. It still gave the viewer a weak reason to watch.

Specificity is the mechanism. More buyers is the desired benefit. The requested
revision is **“Use this offer formula to get more buyers.”** The accepted story
then explains how the outcome/timeframe formula makes the offer clearer. The
benefit names the aim of the lesson; it does not assert a measured conversion lift.

The members example had a related problem: “How to plan a $1K month” led with
planning and a number that was not inherently surprising. The revised question,
**“Who else wants $1K/mo in their first 30 days?”**, adds a concrete desired
outcome and the timeframe actually stated in the recording. Its arithmetic
explains the 26-member target; it does not claim acquiring those members is easy.

## Apply this before assembly

1. Name what this audience wants in ordinary language.
2. Name the mechanism separately. A viewer may care about a mechanism directly
   in a technical lesson; establish that, rather than assuming it.
3. Point to the exact hook words that create relevance or curiosity: stakes,
   a supported timeframe, a surprising relationship or a meaningful question.
4. Trace the opening's promise through the retained explanation and payoff.
   Distinguish a goal from an achieved result. Avoid adding ease, proof or a
   complete acquisition method that is absent from the material.
5. Apply the actual canonical template, then test its copy and its pixels
   separately. A template hash and readable text do not prove audience appeal.

`native-director-prompt.ts` now asks both author and critic for this distinction
inside the existing relevance audit. It does not introduce another model call,
schema, hook catalog or invented efficacy score. This prompt change has local
regression coverage from the existing Director tests; live model behavior and
retention are not tested by those tests.

The prior eight-word validator would also reject both revised hooks despite
their verified two-line title fit. Prompt and validator now share a 12-word cap,
with the existing 120-character and two-line bounds retained. Short copy remains
preferred; benefit and timeframe may justify more words when phone-size layout
and reading time support them. A regression accepts these two actual revised
strings and rejects 13 words or three lines. This removes a mechanical obstacle
without treating length compliance as evidence of a strong hook.

The operator's positive feedback applies to example 2's existing story and real
footage. Preserve those accepted choices while revising its hook. Search the
available recording for relevant B-roll before assuming an external or generated
asset is needed; use footage for what it actually shows.
