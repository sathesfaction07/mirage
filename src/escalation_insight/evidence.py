"""Evidence for a ratio, computed exactly, with no dependency and no normal approximation.

A ratio is scale-free and its evidence is not. "3x" is the same phrase for 1 -> 3 and for
40 -> 120, and only one of them is a finding. Everything here exists to stop the first one
being published in the same sentence as the second.

The test: if the underlying rate never changed, then each of the `n` escalations across two
periods landed in the later one with probability equal to that period's share of the total
exposure. The count in the later period is then Binomial(n, p), and the question "is this
split surprising" has an exact answer -- `math.comb` and arithmetic, no scipy, no z-scores,
nothing that needs `n` to be large. It has to be exact, because the whole difficulty is that
`n` is small.

Two-sided by the method of small p-values: add up the probability of every outcome no more
likely than the one observed. That is the definition that stays sensible when `p != 0.5`,
which it always is here, because months are of unequal length.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field

from .models import Bucket, Direction, RatioClaim

TOLERANCE = 1e-12
"""Relative slack when asking "is this outcome no more likely than the observed one".

Without it, an outcome with mathematically identical probability to the observed one -- the
mirror-image count when p is exactly 0.5 -- is excluded or included depending on the last
bit of a float, and the p-value jumps discontinuously. The tolerance is not statistics; it
is the price of doing statistics in binary floating point.
"""


def pmf(k: int, n: int, p: float) -> float:
    """P(X = k) for X ~ Binomial(n, p). Exact up to float rounding of the powers."""
    if not 0 <= k <= n:
        return 0.0
    return math.comb(n, k) * (p**k) * ((1.0 - p) ** (n - k))


def two_sided_p(k: int, n: int, p: float) -> float:
    """P(an outcome at least as unlikely as k), for X ~ Binomial(n, p).

    Returns 1.0 for n == 0: with nothing observed, every hypothesis survives.
    """
    if n == 0:
        return 1.0
    observed = pmf(k, n, p)
    threshold = observed * (1.0 + TOLERANCE)
    total = sum(value for j in range(n + 1) if (value := pmf(j, n, p)) <= threshold)
    return min(1.0, total)


def claim(
    label: str,
    *,
    count_before: int,
    count_after: int,
    days_before: int,
    days_after: int,
    alpha: float,
) -> RatioClaim:
    """Build a ratio claim with its exact p-value under a constant-rate null.

    `days_*` are the EXPOSURES, and they are what makes the null hypothesis honest. Using
    0.5 instead would test "did the counts split evenly", which is a different and wrong
    question whenever the two periods differ in length -- which, for calendar months, is
    almost always.
    """
    if days_before <= 0 or days_after <= 0:
        raise ValueError(f"{label}: a period with no elapsed time is not comparable")
    share_after = days_after / (days_before + days_after)
    return RatioClaim(
        label=label,
        count_before=count_before,
        count_after=count_after,
        days_before=days_before,
        days_after=days_after,
        p_value=two_sided_p(count_after, count_before + count_after, share_after),
        alpha=alpha,
    )


def compare_buckets(label: str, before: Bucket, after: Bucket, *, alpha: float) -> RatioClaim:
    return claim(
        label,
        count_before=before.count,
        count_after=after.count,
        days_before=before.exposure.elapsed_days,
        days_after=after.exposure.elapsed_days,
        alpha=alpha,
    )


class ScaleDemo(BaseModel):
    """One ratio, two scales, and the two verdicts that follow.

    Built to be quoted: the ratio is identical, the headline sentence somebody would write
    is identical, and the evidence differs by orders of magnitude.
    """

    model_config = ConfigDict(frozen=True)

    ratio: float
    small: RatioClaim
    large: RatioClaim

    @property
    def verdicts_differ(self) -> bool:
        return self.small.direction is not self.large.direction

    def summary(self) -> str:
        return (
            f"Both of these are a {self.ratio:.0f}x increase, over periods of equal length.\n"
            f"  {self.small.count_before} -> {self.small.count_after}: "
            f"p = {self.small.p_value:.2f}, so {self.small.direction.value}\n"
            f"  {self.large.count_before} -> {self.large.count_after}: "
            f"p = {self.large.p_value:.2g}, so {self.large.direction.value}\n"
            f"The RATIO cannot tell them apart, because a ratio divides out the very thing "
            f"the evidence depends on. Writing \"{self.ratio:.0f}x\" in a report is therefore "
            "compatible with having found nothing at all."
        )


def scale_demo(*, ratio: int = 3, small_before: int = 1, large_before: int = 40,
               alpha: float = 0.05, days: int = 30) -> ScaleDemo:
    """The same multiplier at two scales, over EQUAL exposures so only `n` differs."""
    return ScaleDemo(
        ratio=float(ratio),
        small=claim(
            f"{small_before} -> {small_before * ratio}",
            count_before=small_before,
            count_after=small_before * ratio,
            days_before=days,
            days_after=days,
            alpha=alpha,
        ),
        large=claim(
            f"{large_before} -> {large_before * ratio}",
            count_before=large_before,
            count_after=large_before * ratio,
            days_before=days,
            days_after=days,
            alpha=alpha,
        ),
    )


class CalendarBias(BaseModel):
    """What ignoring month length does to a verdict, and in which direction.

    February is 28 days to January's 31, so under a constant rate February earns 47.5% of
    the pair's escalations rather than 50%. Testing against 50% therefore treats a perfectly
    ordinary February shortfall as evidence of improvement.

    The bias is ASYMMETRIC and that is the useful part: ignoring the calendar makes a
    DECLINE look more real than it is and an INCREASE look less real than it is. A monthly
    escalation report that never adjusts is biased toward good news.
    """

    model_config = ConfigDict(frozen=True)

    n: int
    count_after: int
    days_before: int
    days_after: int
    naive: RatioClaim
    adjusted: RatioClaim

    @property
    def verdict_flips(self) -> bool:
        return self.naive.direction is not self.adjusted.direction

    def summary(self) -> str:
        head = (
            f"{self.n - self.count_after} -> {self.count_after} over "
            f"{self.days_before} then {self.days_after} days.\n"
            f"  testing against an even 50/50 split : p = {self.naive.p_value:.4f} -> "
            f"{self.naive.direction.value}\n"
            f"  testing against the real exposures  : p = {self.adjusted.p_value:.4f} -> "
            f"{self.adjusted.direction.value}"
        )
        if not self.verdict_flips:
            return head + "\n  Same verdict here; the p-value still moved."
        return (
            head + "\n  The verdict FLIPS. The shorter month was doing the work, not the "
            "escalations."
        )


def calendar_bias(
    *, n: int, count_after: int, days_before: int = 31, days_after: int = 28,
    alpha: float = 0.05,
) -> CalendarBias:
    """Run the same split against an even null and against the true exposure null."""
    before = n - count_after
    naive_days = (days_before + days_after) // 2
    return CalendarBias(
        n=n,
        count_after=count_after,
        days_before=days_before,
        days_after=days_after,
        naive=claim(
            "assuming equal months",
            count_before=before,
            count_after=count_after,
            days_before=naive_days,
            days_after=naive_days,
            alpha=alpha,
        ),
        adjusted=claim(
            "using real month lengths",
            count_before=before,
            count_after=count_after,
            days_before=days_before,
            days_after=days_after,
            alpha=alpha,
        ),
    )


def smallest_flip(
    *, alpha: float = 0.05, days_before: int = 31, days_after: int = 28, limit: int = 400
) -> CalendarBias | None:
    """Search for the smallest total count at which ignoring the calendar flips the verdict.

    Searched rather than asserted, so the claim in the docs is whatever the arithmetic
    actually supports on the day it is run. Returns None if no such case exists below
    `limit`, which is a real possible answer and not an error.
    """
    for n in range(2, limit + 1):
        # Both counts must be non-zero: with a zero denominator there is no ratio, and the
        # verdict would come from the fallback branch rather than from the evidence, which
        # makes for a true but uninteresting example.
        for count_after in range(1, n):
            case = calendar_bias(
                n=n, count_after=count_after, days_before=days_before,
                days_after=days_after, alpha=alpha,
            )
            if case.verdict_flips:
                return case
    return None


class Underpowered(BaseModel):
    """The smallest change this pair of periods could ever have detected.

    Answers a question a report should be asked and never is: before looking at the data,
    was this analysis capable of finding anything? For tiny `n` the answer is no -- every
    possible split is unsurprising, so the study could not have produced a finding whatever
    happened, and its silence is not reassurance.
    """

    model_config = ConfigDict(frozen=True)

    total: int = Field(ge=0)
    days_before: int
    days_after: int
    alpha: float
    detectable: tuple[int, ...]
    """The counts in the later period that WOULD have been called a change."""

    @property
    def can_detect_anything(self) -> bool:
        return bool(self.detectable)

    def summary(self) -> str:
        if not self.can_detect_anything:
            return (
                f"With {self.total} escalations across the two periods, NO split would have "
                f"reached alpha {self.alpha:g} -- not even all of them landing in one period. "
                "This comparison could not have produced a finding, so finding none says "
                "nothing about the world."
            )
        return (
            f"With {self.total} escalations, a change would have been called only if the later "
            f"period held one of {list(self.detectable)}. Anything else was going to be "
            "reported as UNKNOWN before the data was looked at."
        )


def power_floor(
    *, total: int, days_before: int, days_after: int, alpha: float = 0.05
) -> Underpowered:
    """Which later-period counts, out of all possible, would have been called a change."""
    share_after = days_after / (days_before + days_after)
    detectable = tuple(
        k for k in range(total + 1) if two_sided_p(k, total, share_after) <= alpha
    )
    return Underpowered(
        total=total,
        days_before=days_before,
        days_after=days_after,
        alpha=alpha,
        detectable=detectable,
    )


def why_a_ratio_is_not_a_finding() -> str:
    return (
        "A ratio is scale-free: it divides out the count, which is the only thing carrying "
        "the evidence. So the phrase \"3x\" survives being computed from 1 and 3, where a "
        "constant rate produces that split about a third of the time. The number in a "
        "headline and the strength of the claim behind it are independent quantities, and "
        f"only one of them is usually printed. {Direction.UNKNOWN.value} exists in this "
        "codebase so the other answer has somewhere to go."
    )
