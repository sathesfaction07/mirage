"""Turning a series into a direction, and reporting how little that direction is worth.

A trend is the last thing computed and the first thing quoted, which is the wrong way round.
Every input to it is a choice made earlier -- which mapping version, which unit, which grain,
whether the unfinished bucket is included -- and this module's job is to run the same
question under all of them and print the set of answers.

The claim being refuted is PROJECT_LOGIC's own aspiration: "this pattern is increasing 3x
over 3 months and affects 4 teams". Three of those four numbers are choices and the fourth
is a ratio with no evidence attached.
"""

from __future__ import annotations

import itertools

from pydantic import BaseModel, ConfigDict

from . import evidence
from .models import Direction, RatioClaim, Series


def endpoints(series: Series, *, complete_only: bool) -> tuple | None:
    """The two buckets a first-versus-last trend actually compares.

    `complete_only` drops the unfinished newest bucket. That is not a detail: it changes
    which two numbers the whole claim rests on, and dropping it makes the report silent
    about the current month.
    """
    pool = series.complete_buckets if complete_only else series.buckets
    usable = [b for b in pool if b.exposure.elapsed_days > 0]
    if len(usable) < 2:
        return None
    return usable[0], usable[-1]


def trend(series: Series, *, alpha: float, complete_only: bool = True) -> RatioClaim | None:
    pair = endpoints(series, complete_only=complete_only)
    if pair is None:
        return None
    before, after = pair
    return evidence.compare_buckets(
        f"{series.category} {before.label}->{after.label}", before, after, alpha=alpha
    )


class Choice(BaseModel):
    """One combination of settings, and the direction it produces."""

    model_config = ConfigDict(frozen=True)

    mapping_version: str
    unit: str
    grain: str
    complete_only: bool
    direction: Direction
    counts: tuple[int, int] | None
    p_value: float | None

    @property
    def comparable(self) -> bool:
        """Whether a comparison could be formed at all.

        False means the category has fewer than two usable buckets, so there was nothing to
        test. That is NOT the same as UNKNOWN, which means a test ran and found nothing.
        """
        return self.counts is not None

    def label(self) -> str:
        newest = "excluded" if self.complete_only else "INCLUDED"
        return (
            f"{self.mapping_version:9s} {self.unit:7s} {self.grain:6s} newest={newest:8s}"
        )


class Sensitivity(BaseModel):
    """Every combination of the four choices, and the set of directions they produce.

    The number worth reading is `distinct_directions`. One means the finding survives every
    reading of the data. More than one means the report's conclusion was decided by a
    configuration file.
    """

    model_config = ConfigDict(frozen=True)

    category: str
    choices: tuple[Choice, ...]
    unavailable: tuple[str, ...] = ()
    """Mapping versions under which this category does not exist at all.

    Reported rather than skipped. A revision that splits a category DELETES it, so its trend
    line does not go flat or go down -- it stops, and a reader comparing this quarter's report
    with last quarter's finds the row simply missing.
    """

    @property
    def directions(self) -> tuple[Direction, ...]:
        return tuple(sorted({c.direction for c in self.choices}, key=lambda d: d.value))

    @property
    def distinct_directions(self) -> int:
        return len(self.directions)

    @property
    def direction_is_a_choice(self) -> bool:
        return self.distinct_directions > 1

    @property
    def comparable_choices(self) -> tuple[Choice, ...]:
        return tuple(c for c in self.choices if c.comparable)

    @property
    def no_comparison_possible(self) -> bool:
        """No reading could form a comparison, so there is no evidence either way.

        Kept apart from `never_established`, where every reading DID run and none reached
        the threshold. Reporting the first as the second claims a test that never happened.
        """
        return not self.comparable_choices

    @property
    def never_established(self) -> bool:
        """Every reading came back UNKNOWN, which is a different failure from disagreeing."""
        return bool(self.comparable_choices) and self.directions == (Direction.UNKNOWN,)

    @property
    def unknown_share(self) -> float:
        if not self.choices:
            return 0.0
        unknown = sum(1 for c in self.choices if c.direction is Direction.UNKNOWN)
        return unknown / len(self.choices)

    def summary(self) -> str:
        head = (
            f"{self.category}: {len(self.choices)} readings of the same escalations produce "
            f"{self.distinct_directions} distinct direction(s) "
            f"{[d.value for d in self.directions]}."
        )
        if self.unavailable:
            head += (
                f" It does not exist at all under {list(self.unavailable)}, so those readings "
                "could not be run -- a revision that splits a category deletes it, and the "
                "trend line stops rather than moving."
            )
        if self.no_comparison_possible:
            return (
                head + " None of those readings could form a comparison at all -- the category "
                "occupies fewer than two usable buckets, so nothing was tested and UNKNOWN "
                "here records an absence of evidence rather than a test that came back empty."
            )
        partly = len(self.comparable_choices)
        if partly and partly < len(self.choices):
            head += (
                f" Only {partly} of them could form a comparison at all: under one grain the "
                "category occupies two buckets and under the other it occupies one, so the "
                "bucket width decides whether the question can even be ASKED, before any "
                "evidence is weighed."
            )
        if self.never_established:
            return (
                head + " Every reading came back UNKNOWN, so there is no direction here to "
                "depend on anything -- which is not the same as the rate being flat."
            )
        if not self.direction_is_a_choice:
            only = self.directions[0].value
            return (
                head
                + f" Every reading says {only}, so this one does not depend on the settings."
            )
        return (
            head
            + " Nothing in the escalations chooses between them, so the direction this "
            "report leads with was decided by configuration, not by what happened."
        )


def sensitivity(
    series_by_choice: dict[tuple[str, str, str, bool], Series],
    *,
    category: str,
    alpha: float,
    unavailable: tuple[str, ...] = (),
) -> Sensitivity:
    """Build the sensitivity table from pre-built series, one per combination."""
    choices: list[Choice] = []
    for (version, unit, grain, complete_only), series in sorted(series_by_choice.items()):
        claim = trend(series, alpha=alpha, complete_only=complete_only)
        choices.append(
            Choice(
                mapping_version=version,
                unit=unit,
                grain=grain,
                complete_only=complete_only,
                direction=claim.direction if claim else Direction.UNKNOWN,
                counts=(claim.count_before, claim.count_after) if claim else None,
                p_value=claim.p_value if claim else None,
            )
        )
    return Sensitivity(
        category=category, choices=tuple(choices), unavailable=unavailable
    )


def combinations(versions: list[str], units: list[str], grains: list[str]) -> list[tuple]:
    return list(itertools.product(versions, units, grains, [True, False]))


def why_a_trend_is_not_an_observation() -> str:
    return (
        "A count over time is not a measurement of the world. It is events x how many got "
        "reported x how the reporter categorised them x when the system heard about it x "
        "whether the category existed for the whole window. Only the first is what anybody "
        "wants to know, and a change in any of the other four produces exactly the same "
        "movement in the line. The data cannot distinguish them, so the honest output is the "
        "set of directions the choices produce rather than the one the settings happened to "
        "select."
    )
