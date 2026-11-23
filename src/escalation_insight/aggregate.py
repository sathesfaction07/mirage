"""Reads the export, builds every reading of it, and refuses to pick one.

`run` is deliberately expensive: it builds the same series under every combination of the
four choices, because the disagreement between them is the output. A tool that built one
series would be faster and would have nothing to say.
"""

from __future__ import annotations

import csv
import datetime as dt
import itertools
from collections import Counter, defaultdict
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from . import buckets, evidence, gaps, trend, units
from .config import Settings
from .mapping import Mapping, MappingSet, VersionEffect, version_effect
from .models import Direction, Grain, Series, Ticket, TicketFault, Unit


def load_tickets(path: Path) -> list[Ticket]:
    """Parse the export. A blank date is None, not today, and not the epoch."""
    out: list[Ticket] = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            out.append(
                Ticket(
                    ticket_id=row["ticket_id"],
                    case_id=row["case_id"],
                    raw_category=row["raw_category"],
                    team=row["team"],
                    opened_at=_date(row["opened_at"]),
                    recorded_at=_date(row["recorded_at"]),
                    reopen_of=row["reopen_of"] or None,
                )
            )
    return out


def _date(raw: str) -> dt.date | None:
    return dt.date.fromisoformat(raw) if raw.strip() else None


def faults(tickets: list[Ticket], mapping: Mapping) -> dict[TicketFault, tuple[str, ...]]:
    """Producer-fixable defects, one bucket per kind.

    UNMAPPED_CATEGORY is here rather than in a taxonomy report because it is fixable two
    ways at the source -- correct the label, or add it to the mapping -- and until somebody
    does, the row is in the export and in none of the counts.
    """
    seen: Counter[str] = Counter(t.ticket_id for t in tickets)
    known = {t.ticket_id for t in tickets}
    found: dict[TicketFault, list[str]] = defaultdict(list)
    for ticket in tickets:
        if ticket.opened_at is None:
            found[TicketFault.NO_EVENT_TIME].append(ticket.ticket_id)
        elif ticket.recorded_at is not None and ticket.recorded_at < ticket.opened_at:
            found[TicketFault.RECORDED_BEFORE_EVENT].append(ticket.ticket_id)
        if ticket.reopen_of and ticket.reopen_of not in known:
            found[TicketFault.ORPHAN_REOPEN].append(ticket.ticket_id)
        if mapping.canonical(ticket.raw_category) is None:
            found[TicketFault.UNMAPPED_CATEGORY].append(ticket.ticket_id)
    for ticket_id, count in seen.items():
        if count > 1:
            found[TicketFault.DUPLICATE_ID].append(ticket_id)
    return {fault: tuple(sorted(set(ids))) for fault, ids in sorted(found.items())}


class Analysis(BaseModel):
    """Everything, under every reading, with nothing collapsed."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    settings: Settings
    as_of: dt.date
    tickets: list[Ticket]
    mappings: MappingSet
    sop: gaps.Sop
    active: tuple[Series, ...]
    """One series per category under the ACTIVE settings."""

    sensitivities: tuple[trend.Sensitivity, ...]
    version_effects: tuple[VersionEffect, ...]
    unit_effects: tuple[units.UnitEffect, ...]
    censored: tuple[buckets.Censoring, ...]
    topic_gaps: tuple[gaps.TopicGap, ...]
    ranking: gaps.Ranking
    ticket_faults: dict[TicketFault, tuple[str, ...]]

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(s.category for s in self.active)

    @property
    def settings_decide(self) -> tuple[str, ...]:
        return tuple(s.category for s in self.sensitivities if s.direction_is_a_choice)

    @property
    def never_established(self) -> tuple[str, ...]:
        """Categories where EVERY reading came back UNKNOWN. Not the same as flat."""
        return tuple(s.category for s in self.sensitivities if s.never_established)

    @property
    def not_comparable(self) -> tuple[str, ...]:
        """Categories with too few buckets for any reading to form a comparison."""
        return tuple(s.category for s in self.sensitivities if s.no_comparison_possible)

    @property
    def deleted_by_a_revision(self) -> tuple[str, ...]:
        return tuple(s.category for s in self.sensitivities if s.unavailable)

    @property
    def survives_every_reading(self) -> tuple[str, ...]:
        return tuple(
            s.category
            for s in self.sensitivities
            if not s.direction_is_a_choice and s.directions != (Direction.UNKNOWN,)
        )

    def headline(self) -> str:
        total = len(self.tickets)
        faulty = sum(len(v) for v in self.ticket_faults.values())
        decided = len(self.settings_decide)
        survived = len(self.survives_every_reading)
        parts = [
            f"{total} tickets, {faulty} of them carrying a producer-fixable defect.",
            f"Of {len(self.categories)} categories, {survived} show a direction that survives "
            f"every reading of the data; {decided} have their direction decided by the settings "
            f"rather than by the escalations, {len(self.never_established)} were tested under "
            "every reading and never reached the threshold, and "
            f"{len(self.not_comparable)} could not be tested at all.",
        ]
        if self.censored:
            first = self.censored[0]
            parts.append(
                f"The newest bucket ({first.label}) is {first.elapsed_days} of "
                f"{first.nominal_days} days elapsed, so its count is low by construction."
            )
        rewrites = [v for v in self.version_effects if v.rewrites_history]
        if rewrites:
            parts.append(
                f"{len(rewrites)} mapping revision(s) change counts in months that were "
                "already closed and already reported."
            )
        return " ".join(parts)


def run(settings: Settings) -> Analysis:
    tickets = load_tickets(settings.tickets_path)
    mappings = MappingSet.load(settings.mappings_path)
    sop = gaps.Sop.load(settings.sop_path)
    as_of = settings.as_of or dt.date.fromisoformat(mappings.as_of)
    active_mapping = mappings.get(settings.mapping_version)

    categories = sorted(
        {
            canon
            for ticket in tickets
            if (canon := active_mapping.canonical(ticket.raw_category)) is not None
        }
    )

    active = tuple(
        buckets.build_series(
            tickets,
            category=category,
            mapping=active_mapping,
            unit=settings.unit,
            grain=settings.grain,
            as_of=as_of,
        )
        for category in categories
    )

    sensitivities: list[trend.Sensitivity] = []
    for category in categories:
        per_choice: dict[tuple[str, str, str, bool], Series] = {}
        for version, unit, grain, complete_only in trend.combinations(
            list(mappings.names), [u.value for u in Unit], [g.value for g in Grain]
        ):
            mapping = mappings.get(version)
            if category not in mapping.canonical_names:
                continue
            per_choice[(version, unit, grain, complete_only)] = buckets.build_series(
                tickets,
                category=category,
                mapping=mapping,
                unit=Unit(unit),
                grain=Grain(grain),
                as_of=as_of,
            )
        missing = tuple(
            name
            for name in mappings.names
            if category not in mappings.get(name).canonical_names
        )
        if per_choice:
            sensitivities.append(
                trend.sensitivity(
                    per_choice,
                    category=category,
                    alpha=settings.alpha,
                    unavailable=missing,
                )
            )

    names = list(mappings.names)
    version_effects = tuple(
        version_effect(tickets, mappings.get(a), mappings.get(b))
        for a, b in itertools.pairwise(names)
    )

    unit_effects = tuple(
        units.unit_effect(
            buckets.build_series(
                tickets, category=category, mapping=active_mapping,
                unit=Unit.TICKET, grain=settings.grain, as_of=as_of,
            ),
            buckets.build_series(
                tickets, category=category, mapping=active_mapping,
                unit=Unit.CASE, grain=settings.grain, as_of=as_of,
            ),
        )
        for category in categories
    )

    censored = tuple(c for series in active if (c := buckets.censoring(series)) is not None)

    escalations = {series.category: series.total for series in active}
    topic_gaps = gaps.assess(sop, escalations)

    return Analysis(
        settings=settings,
        as_of=as_of,
        tickets=tickets,
        mappings=mappings,
        sop=sop,
        active=active,
        sensitivities=tuple(sensitivities),
        version_effects=version_effects,
        unit_effects=unit_effects,
        censored=censored,
        topic_gaps=topic_gaps,
        ranking=gaps.ranking(topic_gaps),
        ticket_faults=faults(tickets, active_mapping),
    )


def payload(analysis: Analysis) -> dict:
    """The numbers, flat, for tests and CI to assert on."""
    return {
        "tickets": len(analysis.tickets),
        "categories": list(analysis.categories),
        "faults": {k.value: list(v) for k, v in analysis.ticket_faults.items()},
        "settings_decide_direction": list(analysis.settings_decide),
        "survives_every_reading": list(analysis.survives_every_reading),
        "never_established": list(analysis.never_established),
        "not_comparable": list(analysis.not_comparable),
        "deleted_by_a_revision": list(analysis.deleted_by_a_revision),
        "directions_by_category": {
            s.category: [d.value for d in s.directions] for s in analysis.sensitivities
        },
        "readings_per_category": {
            s.category: len(s.choices) for s in analysis.sensitivities
        },
        "unknown_share": {
            s.category: round(s.unknown_share, 3) for s in analysis.sensitivities
        },
        "history_rewrites": [
            {"from": v.before, "to": v.after, "buckets": v.rewritten_buckets}
            for v in analysis.version_effects
            if v.rewrites_history
        ],
        "uneven_dedup": [u.category for u in analysis.unit_effects if not u.evenly_spread],
        "censored": [
            {"category": c.category, "label": c.label, "elapsed": c.elapsed_days,
             "nominal": c.nominal_days, "visible": c.visible, "late": c.late_arrivals}
            for c in analysis.censored
        ],
        "documented_and_still_asked": [
            g.category for g in analysis.topic_gaps if g.documented and g.questions > 0
        ],
        "ranking_by_volume": list(analysis.ranking.by_volume),
        "ranking_by_rate": list(analysis.ranking.by_rate),
        "ranking_agrees": analysis.ranking.agree,
        "underpowered": [
            g.category
            for g in analysis.topic_gaps
            if not evidence.power_floor(
                total=g.escalations, days_before=31, days_after=28,
                alpha=analysis.settings.alpha,
            ).can_detect_anything
        ],
    }
