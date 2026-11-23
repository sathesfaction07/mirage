"""Inferring an "SOP gap" from questions asked, and why the inference does not go through.

The brief's last uplift is recommendation generation: find the systemic gaps and suggest
fixes. This module builds the input that request needs and then declines to make the leap,
because the leap is not available.

A question count is the same number whichever of four things produced it:

    the SOP does not cover it          adding a section fixes this
    it is covered and unfindable       adding a section makes it WORSE
    it is covered, found, distrusted    adding a section changes nothing
    asking is simply cheaper           adding a section changes nothing

Nothing in an escalation export distinguishes them, because the export records the question
and never the search that preceded it. And the most-asked topic here IS documented, so the
one cause that a new section would fix is the one already ruled out for the biggest number
in the report.

There is a second, quieter problem: a question count is not comparable across topics until it
is divided by how many escalations that topic had. Doing that division changes the ranking,
which means "the biggest pain point" is a different topic depending on a decision nobody
writes down.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .models import GAP_CAUSE_NOTES, GapCause


class Sop(BaseModel):
    """What the procedure covers, and how many questions each topic drew."""

    model_config = ConfigDict(frozen=True)

    document: str
    revision: int
    covers: dict[str, str | None]
    questions: dict[str, int]

    @classmethod
    def load(cls, path: Path) -> Sop:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            document=raw["document"],
            revision=raw["revision"],
            covers=raw["covers"],
            questions=raw["questions"],
        )

    def section_for(self, category: str) -> str | None:
        return self.covers.get(category)

    def documents(self, category: str) -> bool:
        return self.covers.get(category) is not None


class TopicGap(BaseModel):
    """One topic's question load, and the causes still standing."""

    model_config = ConfigDict(frozen=True)

    category: str
    questions: int
    escalations: int
    section: str | None

    @property
    def documented(self) -> bool:
        return self.section is not None

    @property
    def per_escalation(self) -> float | None:
        """Questions per escalation. None when the topic has no escalations to divide by."""
        if self.escalations == 0:
            return None
        return self.questions / self.escalations

    @property
    def candidates(self) -> tuple[GapCause, ...]:
        """The causes this data has not ruled out.

        Being documented rules out exactly one, and leaves three. Being undocumented rules
        out none -- an absent section does not establish that its absence is why anybody
        asked, and assuming it does is the error this whole module exists to prevent.
        """
        if self.documented:
            return tuple(c for c in GapCause if c is not GapCause.NOT_DOCUMENTED)
        return tuple(GapCause)

    @property
    def adding_a_section_would_help(self) -> bool | None:
        """True only if NOT_DOCUMENTED is the single remaining candidate. It never is.

        None means undetermined, which is the honest answer for every topic here: even an
        undocumented topic has all four causes live, so a new section is a bet rather than
        a fix.
        """
        if self.documented:
            return False
        return None

    def note(self) -> str:
        where = f"documented at section {self.section}" if self.documented else "NOT documented"
        rate = "n/a" if self.per_escalation is None else f"{self.per_escalation:.2f}"
        lines = [
            f"{self.category}: {self.questions} questions over {self.escalations} escalations "
            f"({rate} per escalation), {where}.",
        ]
        if self.documented:
            lines.append(
                "  It is in the SOP and people asked anyway, so the one cause a new section "
                "would fix is ruled out. Three remain and this data separates none of them."
            )
        else:
            lines.append(
                "  Undocumented, which rules nothing out: it does not follow that the "
                "absence is why anybody asked. Four causes remain."
            )
        for cause in self.candidates:
            lines.append(f"    still possible -- {cause.value}: {GAP_CAUSE_NOTES[cause]}")
        return "\n".join(lines)


class Ranking(BaseModel):
    """The same topics ranked two ways, because both are defensible and they disagree."""

    model_config = ConfigDict(frozen=True)

    by_volume: tuple[str, ...]
    by_rate: tuple[str, ...]

    @property
    def agree(self) -> bool:
        return self.by_volume == self.by_rate

    @property
    def moved(self) -> tuple[str, ...]:
        return tuple(
            topic
            for topic in self.by_volume
            if self.by_volume.index(topic) != self.by_rate.index(topic)
        )

    def summary(self) -> str:
        head = (
            f"  ranked by questions asked      : {list(self.by_volume)}\n"
            f"  ranked by questions PER escalation: {list(self.by_rate)}"
        )
        if self.agree:
            return head + "\n  Same order both ways."
        return (
            head + f"\n  {list(self.moved)} move. A topic with few questions and few "
            "escalations is invisible by volume and prominent by rate, so \"the biggest pain "
            "point\" is decided by whether somebody divided, and reports rarely say."
        )


def assess(sop: Sop, escalations: dict[str, int]) -> tuple[TopicGap, ...]:
    """One assessment per topic the SOP has a question count for."""
    return tuple(
        TopicGap(
            category=category,
            questions=count,
            escalations=escalations.get(category, 0),
            section=sop.section_for(category),
        )
        for category, count in sorted(sop.questions.items())
    )


def ranking(gaps: tuple[TopicGap, ...]) -> Ranking:
    by_volume = tuple(
        g.category for g in sorted(gaps, key=lambda g: (-g.questions, g.category))
    )
    by_rate = tuple(
        g.category
        for g in sorted(gaps, key=lambda g: (-(g.per_escalation or 0.0), g.category))
    )
    return Ranking(by_volume=by_volume, by_rate=by_rate)


def why_a_gap_is_not_observable() -> str:
    return (
        "An export records that somebody asked. It does not record whether they looked first, "
        "what they searched for, whether they found the section and disbelieved it, or whether "
        "asking was simply faster than reading. Those four produce identical question counts, "
        "and only the first is fixed by writing more procedure -- while the second is made "
        "worse by it, because a longer document is a harder document to find anything in. So "
        "the recommendation the brief asks for cannot be derived from this data, and the "
        "topics with the most questions here are the ones the SOP already covers."
    )
