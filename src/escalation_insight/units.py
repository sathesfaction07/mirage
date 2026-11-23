"""Deciding what one counted thing IS, and what deduplication costs when you decide.

CaseSearch owns the deduplication ceiling in this portfolio and MultiSourceAgg owns the
result that a static count is a function of the identity key. Neither is repeated here. The
new part is temporal and it is sharper: collapsing tickets into cases does not remove rows
evenly across time, so it changes the DIRECTION of a trend, and it removes the most from
exactly the escalations an escalation review exists to find.

Neither unit is correct, and the report says so rather than picking:

  TICKET   a case reopened six times contributes six. Persistence inflates the count, so the
           number partly measures how hard something was to close.
  CASE     that same case contributes one -- the SAME as one resolved on first contact. The
           inflation is gone and so is every trace of the difficulty.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict

from .models import Series, Ticket, Unit


def collapse(tickets: list[Ticket], unit: Unit) -> list[Ticket]:
    """One row per counted thing; for CASE, the EARLIEST ticket of each case.

    Earliest rather than latest so a case is counted in the period the problem STARTED.
    Counting it at the last touch would move work out of the month a problem began and into
    the month somebody finally gave up, which flatters the past and is equally defensible.
    """
    if unit is Unit.TICKET:
        return list(tickets)
    first: dict[str, Ticket] = {}
    for ticket in tickets:
        if ticket.opened_at is None:
            continue
        seen = first.get(ticket.case_id)
        if seen is None or seen.opened_at is None or ticket.opened_at < seen.opened_at:
            first[ticket.case_id] = ticket
    return [first[key] for key in sorted(first)]


class CaseDepth(BaseModel):
    """How many tickets one case produced."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    tickets: int
    reopens: int

    def note(self) -> str:
        return (
            f"{self.case_id}: {self.tickets} tickets, {self.reopens} of them reopens. Under "
            f"TICKET it is {self.tickets} escalations; under CASE it is 1, indistinguishable "
            "from a case that was answered once and closed."
        )


def depths(tickets: list[Ticket]) -> tuple[CaseDepth, ...]:
    per_case: Counter[str] = Counter()
    reopens: Counter[str] = Counter()
    for ticket in tickets:
        per_case[ticket.case_id] += 1
        if ticket.is_reopen:
            reopens[ticket.case_id] += 1
    return tuple(
        CaseDepth(case_id=case, tickets=count, reopens=reopens[case])
        for case, count in sorted(per_case.items(), key=lambda kv: (-kv[1], kv[0]))
    )


class UnitEffect(BaseModel):
    """What collapsing tickets into cases does, bucket by bucket.

    `removed` is the finding. If it were spread evenly the two series would be scaled copies
    of each other and the direction would survive. It is not spread evenly, because reopens
    cluster on the cases that would not close, so the collapse subtracts most from the worst
    period.
    """

    model_config = ConfigDict(frozen=True)

    category: str
    by_ticket: tuple[tuple[str, int], ...]
    by_case: tuple[tuple[str, int], ...]
    removed: tuple[tuple[str, int], ...]

    @property
    def evenly_spread(self) -> bool:
        counts = {n for _, n in self.removed}
        return len(counts) <= 1

    @property
    def worst_hit(self) -> tuple[str, int] | None:
        ranked = sorted(self.removed, key=lambda kv: (-kv[1], kv[0]))
        return ranked[0] if ranked and ranked[0][1] > 0 else None

    def summary(self) -> str:
        lines = [
            f"{self.category}:",
            "  by TICKET  " + "  ".join(f"{k}={v}" for k, v in self.by_ticket),
            "  by CASE    " + "  ".join(f"{k}={v}" for k, v in self.by_case),
            "  removed    " + "  ".join(f"{k}={v}" for k, v in self.removed),
        ]
        hit = self.worst_hit
        if hit and not self.evenly_spread:
            lines.append(
                f"  The collapse is not even: {hit[0]} loses {hit[1]} while others lose "
                "fewer. Reopens cluster on cases that would not close, so deduplication "
                "subtracts most from the period that went worst -- and the deduplicated "
                "series therefore understates the very thing it was run to find."
            )
        return "\n".join(lines)


def unit_effect(by_ticket: Series, by_case: Series) -> UnitEffect:
    if by_ticket.category != by_case.category:
        raise ValueError("comparing two different categories")
    ticket_counts = {b.label: b.count for b in by_ticket.buckets}
    case_counts = {b.label: b.count for b in by_case.buckets}
    labels = sorted(set(ticket_counts) | set(case_counts))
    return UnitEffect(
        category=by_ticket.category,
        by_ticket=tuple((label, ticket_counts.get(label, 0)) for label in labels),
        by_case=tuple((label, case_counts.get(label, 0)) for label in labels),
        removed=tuple(
            (label, ticket_counts.get(label, 0) - case_counts.get(label, 0))
            for label in labels
        ),
    )


def lineage_disagreement(tickets: list[Ticket]) -> tuple[str, ...]:
    """Tickets whose `reopen_of` parent is absent, so case lineage cannot be built.

    Two groupings of the same rows -- `case_id` and the reopen chain -- and when the chain
    points outside the export they disagree about what one case is. Producer-fixable.
    """
    known = {t.ticket_id for t in tickets}
    return tuple(
        sorted(t.ticket_id for t in tickets if t.reopen_of and t.reopen_of not in known)
    )


def why_neither_unit_is_right() -> str:
    return (
        "There is a third unit that everybody actually means -- one DISTINCT UNDERLYING "
        "PROBLEM -- and no export like this can produce it, because two separate cases can be "
        "the same problem and nothing in the data records that they are. TICKET and CASE are "
        "the two available approximations and they bracket the truth from opposite sides: one "
        "counts persistence as volume, the other discards it entirely."
    )
