# ADR 002 — A ratio is scale-free, so its evidence must be computed and printed separately

**Status:** accepted
**Date:** 2026-09-18

## Context

The project's own aspiration is the phrase *"increasing 3x over 3 months"*. Written down, it is
a ratio of two counts, and a ratio divides out the counts — which are the only thing carrying
evidence about whether the change is real.

Probed exactly, over periods of equal length:

| | p-value under a constant rate | verdict |
|:--|--:|:--|
| 1 → 3 | 0.62 | nothing at all |
| 40 → 120 | 1.8e-10 | overwhelming |

Both are "3x". Both produce the identical sentence in a status update.

None of the sibling projects had machinery for this: `binomial`, `p_value`, `math.comb`, `linregress` and
confidence intervals were **zero files** across the sibling projects. And an approximation would not
have done, because the entire difficulty is that n is small — a normal approximation is least
trustworthy exactly where the question matters.

A second problem surfaced while implementing it. Testing whether a split is "even" assumes the
two periods are equally long. Calendar months are not, so the null hypothesis itself was wrong.

## Decision

**Compute an exact two-sided binomial p-value against an exposure-weighted null, and refuse to
report a direction without it.**

- `math.comb` and arithmetic. No scipy, no z-scores, nothing that needs large n.
- Two-sided by the method of small p-values, which is the definition that stays sensible when
  `p != 0.5` — and here it always is.
- The null is `days_after / (days_before + days_after)`, not 0.5.
- `RatioClaim` exposes `count_ratio` **and** `rate_ratio`, because they differ once exposure is
  honest: the corpus's "3x" is 3.0 by count and **3.32** by rate.
- `power_floor` answers a question reports never ask: *could this comparison have found
  anything?* For 4 escalations, no split whatsoever reaches alpha 0.05.

## Consequences

**Good.** The corpus's one apparent "3x increase" is reported as **not evidence of a change**,
and the tool says why in the same sentence as the number.

**Good, and unexpected.** The calendar correction is **asymmetric**. Because February earns
47.5% rather than 50%, ignoring month length makes a decline look more real and an increase
look less real — so an unadjusted monthly escalation report is systematically biased toward
good news. The smallest verdict flip is `1 -> 7`: p = 0.0703 (`UNKNOWN`) against an even split,
p = 0.0312 (`UP`) against the true exposures. Found by searching rather than asserted.

**Good.** `power_floor` turns a null result into a checkable statement. "We found no trend" and
"this comparison could not have produced one" read identically in a report and are entirely
different claims.

**Good.** It forced the deletion of `Direction.FLAT` (ADR 001), because the same arithmetic
shows the modal outcome always has p = 1.0.

**Bad.** `alpha = 0.05` is a convention with no basis in escalation management, and every
verdict depends on it. Exposed as a flag and printed by `doctor` as a convention, which
mitigates nothing — it just stops it being invisible.

**Bad.** The test assumes escalations are independent within a period. Reopens are the
counter-example living in the same corpus: one case produced six tickets, and those six are
plainly not six independent draws. Under `TICKET` the test is therefore anti-conservative, and
`units.py` reports the clustering rather than correcting for it.

**Bad.** A p-value is a poor instrument for an operational decision. It answers "would a
constant rate produce this" and not "should we staff for it".

## Alternatives

**Report the ratio alone.** The status quo, and the reason the phrase in the project brief survives
being computed from 1 and 3.

**Normal approximation or chi-squared.** Cheaper, standard, and wrong at the sample sizes where
the answer matters. `math.comb` on n < 200 costs nothing.

**Test against 0.5 and mention month length in a footnote.** Considered, and rejected once the
bias turned out to be directional: a footnote does not remove a systematic tilt toward
reporting improvement.

**Poisson rates with a likelihood ratio.** More natural for arrival processes and it requires
choosing a distribution for the rate. The binomial conditions on the observed total instead,
which assumes less, and matters more at n = 4 than any efficiency gain.
