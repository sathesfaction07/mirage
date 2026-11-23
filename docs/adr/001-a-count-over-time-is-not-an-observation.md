# ADR 001 — A count over time is not an observation, so the output is a set of directions

**Status:** accepted
**Date:** 2026-09-18

## Context

The brief wants *"this pattern is increasing 3x over 3 months and affects 4 teams"* and treats
inconsistent categorisation as the obstacle, to be removed by an LLM normalisation pre-pass
before a pandas analysis.

Building the pieces made the obstacle look misplaced. A count of a category in a period is:

```
escalations that HAPPENED x reporting rate x categorisation policy x recording lag
                          x whether the category existed for the whole window
```

Only the first term is of interest, and **a change in any of the other four is
indistinguishable from a change in the first.** Worse, the normalisation pass is the third
term. It does not stand outside the analysis; it is one of the factors being multiplied.

Then the arithmetic produced three results that no amount of clean data addresses:

- Merging two synonymous labels took `delivery_timing` from 10→6 (falling) to 10→12 (rising).
  Same tickets.
- Counting by ticket gave 6→9 for `returns`; counting by case gave 6→4.
- February is 28 days to January's 31, so a constant rate produces a 10% lower February.

## Decision

**Compute the trend under every combination of the four choices, and publish the SET of
directions rather than the one the settings selected.**

- `Series` carries `unit`, `grain` and `mapping_version`, so no series can be compared with
  another unless every choice matches.
- `Sensitivity` runs all 24 readings per category and exposes `direction_is_a_choice`.
- `Direction` has three members. `FLAT` was removed once shown unreachable: the modal outcome
  under the null has p = 1.0, so "the rate did not change" cannot be concluded from this
  evidence at any alpha below 1.
- `UNKNOWN` (tested, unconvincing) is kept strictly apart from `no_comparison_possible`
  (nothing to test).
- Every count is printed beside its exposure; every ratio beside its p-value.

## Consequences

**Good.** The headline is honest and specific: of 4 categories, **0** show a direction that
survives every reading, **2** have their direction decided by the settings, and **2** were
tested under every reading and never convinced. A report that picked one configuration would
have published two trends.

**Good.** It caught a case the brief's framing hides entirely. `v3_split` **deletes**
`delivery_timing`, so 8 of its 24 readings cannot be run — its trend line does not fall, it
disappears. Reported rather than skipped, after an earlier version skipped it silently.

**Good.** Separating "unconvincing" from "untestable" produced a finding: the grain decides
whether `misc` is comparable at all, 12 readings of 24.

**Bad.** 24 readings per category is expensive and verbose. A tool that built one series would
run faster and have nothing to say, but the output is undeniably harder to skim.

**Bad.** The set of choices is *mine*. There are certainly more — timezone, whether a reopen
counts from the parent's date, how a multi-category ticket is attributed — and enumerating four
implies a completeness that is not there.

**Bad.** Nobody can act on "the direction depends on your configuration". The honest output is
less useful than the dishonest one, which is the trade being made deliberately.

## Alternatives

**Pick sensible defaults and report one direction.** What every such tool does. The defaults
then decide the conclusion and no reader can see it happening.

**Report a slope with a confidence interval.** More conventional and no better here: a slope
over three points is two differences wearing a decimal point, and the interval would still be
computed over whichever choices were made upstream.

**Normalise harder — stemming, embeddings, an LLM.** Improves the mapping and makes the
retroactive-edit problem worse, because a better mapping is a mapping more likely to be
revised, and every revision silently re-counts closed months.
