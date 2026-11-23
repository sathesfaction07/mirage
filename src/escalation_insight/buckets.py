"""Placing an escalation in a period, which is where most of the loss happens.

Plimsoll already owns time series in this portfolio: `Series` with periods, missing
periods, rolling baselines, and a `stats` module whose argument is breakdown point -- robust
versus non-robust estimators for anomaly detection. This module does not compete with it and
does not repeat it.

The difference is where the two start. Plimsoll starts from an `Observation` that already
knows which period it belongs to. Everything here is about the step BEFORE that: how a
ticket becomes an observation in a period at all, and what the choice of period does to the
number. By the time you have a well-formed series, the interesting damage is done.

Three ways a bucket's count is not a count of what happened in that stretch of time:

  unequal width   January is 31 days and February 28. A constant rate gives February 90% of
                  January, for free, in the direction of good news.
  the cut-off     the newest bucket is only as wide as the part of it that has happened.
  the lag         an escalation can happen inside the bucket and be recorded after the
                  report was run, so it is real, in the past, and absent.
"""

from __future__ import annotations

import calendar
import datetime as dt
from collections import defaultdict

from pydantic import BaseModel, ConfigDict

from .mapping import Mapping
from .models import Bucket, Exposure, Grain, Series, Ticket, Unit
from .units import collapse


def month_bounds(day: dt.date) -> tuple[str, dt.date, dt.date]:
    start = day.replace(day=1)
    last = calendar.monthrange(day.year, day.month)[1]
    end = start + dt.timedelta(days=last)
    return start.strftime("%Y-%m"), start, end


def week_bounds(day: dt.date) -> tuple[str, dt.date, dt.date]:
    """ISO weeks: equal width, and they straddle month boundaries.

    Which is the trade. Monthly buckets have a stable label everyone understands and unequal
    exposure; weekly buckets have equal exposure and put the end of January in the same
    bucket as the start of February. There is no grain that has both.
    """
    year, week, weekday = day.isocalendar()
    start = day - dt.timedelta(days=weekday - 1)
    return f"{year}-W{week:02d}", start, start + dt.timedelta(days=7)


def bounds(day: dt.date, grain: Grain) -> tuple[str, dt.date, dt.date]:
    return month_bounds(day) if grain is Grain.MONTH else week_bounds(day)


class Assignment(BaseModel):
    """One ticket's fate: which bucket, or why none."""

    model_config = ConfigDict(frozen=True)

    ticket_id: str
    category: str | None
    bucket: str | None
    late: bool
    reason: str | None = None


def assign(
    ticket: Ticket, mapping: Mapping, grain: Grain, as_of: dt.date
) -> Assignment:
    category = mapping.canonical(ticket.raw_category)
    if category is None:
        return Assignment(
            ticket_id=ticket.ticket_id, category=None, bucket=None, late=False,
            reason=f"no canonical category for {ticket.raw_category!r} under {mapping.version}",
        )
    if ticket.opened_at is None:
        return Assignment(
            ticket_id=ticket.ticket_id, category=category, bucket=None, late=False,
            reason="no event time, so there is no period it could belong to",
        )
    label, _, _ = bounds(ticket.opened_at, grain)
    late = ticket.recorded_at is not None and ticket.recorded_at > as_of
    return Assignment(
        ticket_id=ticket.ticket_id, category=category, bucket=label, late=late,
        reason="recorded after the cut-off, so it is real and invisible" if late else None,
    )


def build_series(
    tickets: list[Ticket],
    *,
    category: str,
    mapping: Mapping,
    unit: Unit,
    grain: Grain,
    as_of: dt.date,
) -> Series:
    """Every bucket between the first and last escalation, with gaps filled.

    Gaps are filled with zero rather than omitted, because a missing bucket and a zero
    bucket render identically in a chart and mean different things -- and an omitted bucket
    silently shortens the window a trend is measured over.
    """
    counted = collapse(tickets, unit)
    on_time: dict[str, int] = defaultdict(int)
    late: dict[str, int] = defaultdict(int)
    for ticket in counted:
        placed = assign(ticket, mapping, grain, as_of)
        if placed.category != category or placed.bucket is None:
            continue
        (late if placed.late else on_time)[placed.bucket] += 1

    labels = sorted(set(on_time) | set(late))
    if not labels:
        return Series(
            category=category, unit=unit, grain=grain,
            mapping_version=mapping.version, buckets=(),
        )

    spans: dict[str, tuple[dt.date, dt.date]] = {}
    for ticket in counted:
        if ticket.opened_at is None:
            continue
        label, start, end = bounds(ticket.opened_at, grain)
        spans[label] = (start, end)

    walk = spans[labels[0]][0]
    ordered: list[Bucket] = []
    while walk < spans[labels[-1]][1]:
        label, start, end = bounds(walk, grain)
        ordered.append(
            Bucket(
                exposure=Exposure(label=label, start=start, end=end, as_of=as_of),
                count=on_time[label],
                late_arrivals=late[label],
            )
        )
        walk = end
    return Series(
        category=category, unit=unit, grain=grain,
        mapping_version=mapping.version, buckets=tuple(ordered),
    )


class Censoring(BaseModel):
    """What the newest bucket is worth, and the dilemma it creates."""

    model_config = ConfigDict(frozen=True)

    category: str
    label: str
    elapsed_days: int
    nominal_days: int
    visible: int
    late_arrivals: int

    @property
    def true_so_far(self) -> int:
        return self.visible + self.late_arrivals

    @property
    def understated_by(self) -> float | None:
        if self.true_so_far == 0:
            return None
        return self.late_arrivals / self.true_so_far

    def summary(self) -> str:
        lines = [
            f"{self.category}: {self.label} is the newest bucket and it is not finished: "
            f"{self.elapsed_days} of {self.nominal_days} days.",
            f"  visible when this ran: {self.visible}",
            f"  already happened but recorded after the cut-off: {self.late_arrivals}",
        ]
        if self.understated_by is not None and self.late_arrivals:
            lines.append(
                f"  so the export understates the month-to-date by "
                f"{self.understated_by:.0%}, and every one of those was real at the time."
            )
        lines.append(
            "  Drop this bucket and the report is silent about the only month anybody is "
            "asking about. Keep it and the report shows a decline that is made of the "
            "calendar and the lag. There is no third option, and choosing is not a "
            "statistical act."
        )
        return "\n".join(lines)


def censoring(series: Series) -> Censoring | None:
    """The newest bucket's exposure and hidden volume. None when every bucket is complete."""
    if not series.buckets:
        return None
    newest = series.buckets[-1]
    if newest.trustworthy:
        return None
    return Censoring(
        category=series.category,
        label=newest.label,
        elapsed_days=newest.exposure.elapsed_days,
        nominal_days=newest.exposure.nominal_days,
        visible=newest.count,
        late_arrivals=newest.late_arrivals,
    )
