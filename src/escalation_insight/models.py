"""The types, and the reasons they have the shape they do.

The whole argument of this project lives in three of them:

    Unit        a count of TICKETS and a count of CASES move in OPPOSITE directions on the
                same escalations, so "how many" is not answerable until somebody says
                how many WHAT
    Exposure    a bucket is a stretch of time, and stretches are not equal -- January is
                31 days and February 28, so a constant rate yields a 10% lower February
                and the calendar has manufactured a decline
    Direction   has an UNKNOWN member, because "up", "down" and "flat" are three answers
                and the honest fourth is that the numbers are too small to say
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Unit(StrEnum):
    """What one counted thing IS.

    Not a presentation choice. On this corpus February holds 9 return tickets across 4
    cases, because one case was reopened five times, so the month is UP by ticket and DOWN
    by case. Both counts are correct and they disagree about whether things got worse.

    A third unit -- one DISTINCT UNDERLYING PROBLEM -- is the one an escalation review
    actually wants, and it is not derivable from any export like this: two separate cases
    can be the same problem and nothing records that they are. It is absent from this enum
    because implementing it would mean inventing it.
    """

    TICKET = "TICKET"
    CASE = "CASE"


class Grain(StrEnum):
    """The width of a bucket. Also a choice, and also able to flip a sign.

    MONTH buckets are of unequal width, which is why `Exposure` exists. WEEK buckets are of
    equal width and straddle month boundaries instead, so the two grains disagree about
    which bucket an escalation belongs to.
    """

    MONTH = "MONTH"
    WEEK = "WEEK"


class Direction(StrEnum):
    """Three values, and the absence of a fourth is the point.

    There is no FLAT. It was written, and then removed once the arithmetic showed it could
    never be returned: `rate_ratio == 1.0` holds exactly when the observed count equals the
    MODAL outcome under the constant-rate null, and the modal outcome's two-sided p-value is
    always 1.0, so `p <= alpha` cannot hold for any alpha below 1. FLAT was unreachable by
    algebra rather than by accident.

    Which is the honest result and not a limitation of the implementation: a test that asks
    "is this movement surprising" can fail to be surprised, and failing to be surprised is
    not evidence that nothing happened. UNKNOWN is that answer, and there is no route from
    this kind of evidence to "the rate is the same".
    """

    UP = "UP"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"


class TicketFault(StrEnum):
    """Things a ticket can be wrong about that the PRODUCER of the export can fix.

    Every member is fixable upstream, which is what makes this the gating set. Facts about
    the world -- an incomplete final bucket, a category whose definition is contested --
    are not in here, because nobody can fix time or agree a taxonomy by fixing a row.
    """

    NO_EVENT_TIME = "NO_EVENT_TIME"
    """Cannot be placed in any bucket, so it silently leaves every series."""

    RECORDED_BEFORE_EVENT = "RECORDED_BEFORE_EVENT"
    """A recording cannot precede the thing recorded. Not a lag; an impossibility."""

    DUPLICATE_ID = "DUPLICATE_ID"
    """Two rows claim one identity, and nothing says which is the real one."""

    ORPHAN_REOPEN = "ORPHAN_REOPEN"
    """Reopens a ticket absent from the export, so case lineage cannot be built."""

    UNMAPPED_CATEGORY = "UNMAPPED_CATEGORY"
    """No canonical category under the active mapping, so it appears in no series at all."""


class Ticket(BaseModel):
    """One row of an escalation export, with the strings kept as strings.

    `opened_at` is when the escalation HAPPENED and `recorded_at` is when the analysis
    system learned about it. Keeping both is the only reason this project can say anything
    about the newest bucket: bucketing by one gives a series that sags at the end, and
    bucketing by the other gives a series that puts events in the wrong month.
    """

    model_config = ConfigDict(frozen=True)

    ticket_id: str
    case_id: str
    raw_category: str
    team: str
    opened_at: dt.date | None = None
    recorded_at: dt.date | None = None
    reopen_of: str | None = None

    @property
    def is_reopen(self) -> bool:
        return self.reopen_of is not None

    @property
    def lag_days(self) -> int | None:
        """Days between the escalation and its appearance in the export.

        None when either date is absent, because a lag computed from one date is not a lag.
        """
        if self.opened_at is None or self.recorded_at is None:
            return None
        return (self.recorded_at - self.opened_at).days


class Exposure(BaseModel):
    """How much TIME a bucket covers, and how much of it has actually elapsed.

    Two separate reasons a bucket can hold fewer escalations than its neighbour without
    anything having improved:

      calendar   February is 28 days to January's 31, so a constant rate gives February
                 90.3% of January's count. Free, and in the direction of good news.
      cut-off    the newest bucket is only as wide as the part of it that has happened
                 when somebody runs the report.

    `elapsed_fraction` folds both together, and it is a DENOMINATOR -- which means it can
    only be used to compare rates, and a rate assumes escalations arrive uniformly inside
    the bucket. Nothing here can check that assumption, and it is stated rather than hidden.
    """

    model_config = ConfigDict(frozen=True)

    label: str
    start: dt.date
    end: dt.date
    """Exclusive. The first day NOT in this bucket."""

    as_of: dt.date

    @property
    def nominal_days(self) -> int:
        return (self.end - self.start).days

    @property
    def elapsed_days(self) -> int:
        """Days of this bucket that had happened when the report was run."""
        if self.as_of >= self.end:
            return self.nominal_days
        if self.as_of < self.start:
            return 0
        return (self.as_of - self.start).days + 1

    @property
    def is_complete(self) -> bool:
        return self.as_of >= self.end

    @property
    def elapsed_fraction(self) -> float:
        return self.elapsed_days / self.nominal_days

    def note(self) -> str:
        if self.is_complete:
            return f"{self.label}: complete, {self.nominal_days} days"
        return (
            f"{self.label}: INCOMPLETE -- {self.elapsed_days} of {self.nominal_days} days had "
            f"happened when this ran ({self.elapsed_fraction:.0%}), so its count is low by "
            "construction and not because anything improved"
        )


class Bucket(BaseModel):
    """A count, the exposure it was earned over, and how much never made it in.

    `count` is what the export contains. `late_arrivals` is how many rows belong to this
    bucket by event date but were recorded after the cut-off -- real escalations, invisible
    to anybody who ran the report on time.
    """

    model_config = ConfigDict(frozen=True)

    exposure: Exposure
    count: int = Field(ge=0)
    late_arrivals: int = Field(default=0, ge=0)

    @property
    def label(self) -> str:
        return self.exposure.label

    @property
    def rate_per_nominal_day(self) -> float | None:
        """Count per elapsed day. None for a bucket with no elapsed time at all."""
        if self.exposure.elapsed_days == 0:
            return None
        return self.count / self.exposure.elapsed_days

    @property
    def trustworthy(self) -> bool:
        """Whether this bucket's count can be compared with a complete one as-is."""
        return self.exposure.is_complete and self.late_arrivals == 0


class RatioClaim(BaseModel):
    """A claim of the form "N times more", with the evidence for it computed separately.

    The two are separated because a ratio is SCALE-FREE and its evidence is not: 1 -> 3 and
    40 -> 120 are both "3x", and one of them is noise. A report that prints the ratio
    without the evidence has published the same sentence for both.
    """

    model_config = ConfigDict(frozen=True)

    label: str
    count_before: int = Field(ge=0)
    count_after: int = Field(ge=0)
    days_before: int = Field(gt=0)
    days_after: int = Field(gt=0)
    p_value: float = Field(ge=0.0, le=1.0)
    alpha: float

    @property
    def count_ratio(self) -> float | None:
        """The headline number, and the wrong one: it ignores that the buckets differ in width."""
        if self.count_before == 0:
            return None
        return self.count_after / self.count_before

    @property
    def rate_ratio(self) -> float | None:
        if self.count_before == 0:
            return None
        before = self.count_before / self.days_before
        after = self.count_after / self.days_after
        return after / before

    @property
    def total(self) -> int:
        return self.count_before + self.count_after

    @property
    def direction(self) -> Direction:
        if self.p_value > self.alpha:
            return Direction.UNKNOWN
        ratio = self.rate_ratio
        if ratio is None:
            # A zero denominator with evidence behind it: the rate rose from nothing.
            return Direction.UP
        return Direction.UP if ratio > 1.0 else Direction.DOWN

    def headline(self) -> str:
        """The sentence a report is allowed to print about this claim."""
        if self.count_before == 0:
            supported = (
                f"and a constant rate produces this split only {self.p_value:.2%} of the time, "
                f"so the RATE did change"
                if self.direction is not Direction.UNKNOWN
                else f"and a constant rate produces this split {self.p_value:.0%} of the time, "
                "so not even the rate is established"
            )
            return (
                f"{self.label}: 0 -> {self.count_after}. There is no RATIO to report -- a ratio "
                f"needs a denominator and this one is zero -- {supported}. \"Infinitely more\" "
                "and \"one more than none\" are the same fact."
            )
        counted = f"{self.count_before} -> {self.count_after}"
        ratio = f"{self.count_ratio:.2g}x by count, {self.rate_ratio:.2g}x by rate"
        if self.direction is Direction.UNKNOWN:
            return (
                f"{self.label}: {counted} ({ratio}) -- but with {self.total} escalations in "
                f"total, a constant underlying rate produces a split at least this uneven "
                f"{self.p_value:.0%} of the time, so this is NOT evidence of a change."
            )
        return (
            f"{self.label}: {counted} ({ratio}), and a constant rate produces a split this "
            f"uneven only {self.p_value:.2%} of the time (alpha {self.alpha:g}), so the "
            f"direction is {self.direction.value}."
        )


class Series(BaseModel):
    """Buckets in time order, for one category, under one set of choices.

    Carries the choices with it. A series is not comparable to another series unless every
    one of them matches, and the four fields here are exactly the four that can flip a sign.
    """

    model_config = ConfigDict(frozen=True)

    category: str
    unit: Unit
    grain: Grain
    mapping_version: str
    buckets: tuple[Bucket, ...]

    @model_validator(mode="after")
    def _ordered(self) -> Series:
        labels = [b.label for b in self.buckets]
        if labels != sorted(labels):
            raise ValueError(f"buckets must be in time order, got {labels}")
        return self

    @property
    def total(self) -> int:
        return sum(b.count for b in self.buckets)

    @property
    def complete_buckets(self) -> tuple[Bucket, ...]:
        return tuple(b for b in self.buckets if b.trustworthy)

    def provenance(self) -> str:
        return (
            f"unit={self.unit.value} grain={self.grain.value} mapping={self.mapping_version}"
        )


class GapCause(StrEnum):
    """Why a topic might draw questions. The point is that they are not distinguishable.

    A question count is the same whichever of these produced it, so an "SOP gap" is a
    CONCLUSION about one of four candidates and never an observation.
    """

    NOT_DOCUMENTED = "NOT_DOCUMENTED"
    DOCUMENTED_NOT_FINDABLE = "DOCUMENTED_NOT_FINDABLE"
    DOCUMENTED_NOT_TRUSTED = "DOCUMENTED_NOT_TRUSTED"
    ASKING_IS_CHEAPER = "ASKING_IS_CHEAPER"


GAP_CAUSE_NOTES: dict[GapCause, str] = {
    GapCause.NOT_DOCUMENTED: (
        "the SOP genuinely does not cover it -- the only cause that adding a section fixes"
    ),
    GapCause.DOCUMENTED_NOT_FINDABLE: (
        "it is in there and nobody can find it -- adding a section makes this WORSE"
    ),
    GapCause.DOCUMENTED_NOT_TRUSTED: (
        "it is in there, people found it, and they asked a human anyway"
    ),
    GapCause.ASKING_IS_CHEAPER: (
        "asking costs less effort than reading, whatever the SOP says or does not say"
    ),
}
