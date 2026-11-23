"""Free-text label -> canonical category, under a VERSION, because the mapping changes.

StatusChecker already builds the thing the brief asks for. Its `LabelMap` maps a raw label to
a canonical status PER MARKETPLACE, detects conflicts between marketplaces, and reports which
statuses each marketplace fails to cover -- which is most of "send inconsistent categories for
canonical categorisation", already done, and better than a fresh attempt here would be.

What is new is the question nobody asks it: what does a mapping DO to a count over time?

Two answers, and both are ways to be wrong while every individual mapping decision is right:

  merging   two labels that mean one thing become one category, and the merged series can
            move in the OPPOSITE direction to either of its parts
  revision  a mapping is dated, so applying today's mapping to last quarter's tickets
            changes numbers that were already published, and nothing in the output says so

The mapping is not a cleaning step that happens before the analysis. It is a term IN the
analysis, and revising it is a retroactive edit of every report ever produced from it.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .models import Ticket

WHITESPACE = re.compile(r"\s+")


def normalise(raw: str) -> str:
    """Case and whitespace only.

    Deliberately weak. Anything cleverer -- stemming, synonym guessing, an edit-distance
    match -- is the mapping making decisions that the mapping's author should be making
    visibly, and it would hide exactly the merges this module exists to expose.
    """
    return WHITESPACE.sub(" ", raw.strip().lower())


class Mapping(BaseModel):
    """One version of the raw-label-to-category map."""

    model_config = ConfigDict(frozen=True)

    version: str
    description: str
    categories: dict[str, str]

    def canonical(self, raw: str) -> str | None:
        """The canonical category, or None if this version has never heard of the label.

        None is not a category. A row that maps to nothing appears in NO series, so it is
        absent from every count without being absent from the export -- which is why
        UNMAPPED_CATEGORY is a gated fault rather than a footnote.
        """
        return self.categories.get(normalise(raw))

    @property
    def canonical_names(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.categories.values())))

    def labels_for(self, category: str) -> tuple[str, ...]:
        return tuple(sorted(k for k, v in self.categories.items() if v == category))

    @property
    def merges(self) -> dict[str, tuple[str, ...]]:
        """Categories fed by more than one raw label, with the labels."""
        grouped = defaultdict(list)
        for raw, canon in self.categories.items():
            grouped[canon].append(raw)
        return {k: tuple(sorted(v)) for k, v in sorted(grouped.items()) if len(v) > 1}


class MappingSet(BaseModel):
    """Every version, and the date the set was published."""

    model_config = ConfigDict(frozen=True)

    as_of: str
    versions: dict[str, Mapping]

    @classmethod
    def load(cls, path: Path) -> MappingSet:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            as_of=raw["as_of"],
            versions={
                name: Mapping(
                    version=name,
                    description=body["description"],
                    categories={normalise(k): v for k, v in body["categories"].items()},
                )
                for name, body in raw["versions"].items()
            },
        )

    def get(self, version: str) -> Mapping:
        if version not in self.versions:
            known = ", ".join(sorted(self.versions))
            raise KeyError(f"no mapping version {version!r}; known versions: {known}")
        return self.versions[version]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.versions))


class VersionEffect(BaseModel):
    """What moving from one mapping version to another does to the counts.

    `rewritten` is the finding: buckets whose totals CHANGE for tickets that were already
    closed and already reported. A revision is not additive.
    """

    model_config = ConfigDict(frozen=True)

    before: str
    after: str
    unmapped_before: int
    unmapped_after: int
    rewritten: dict[str, dict[str, tuple[int, int]]]
    """category -> bucket label -> (count under `before`, count under `after`)"""

    appeared: tuple[str, ...]
    disappeared: tuple[str, ...]

    @property
    def rewrites_history(self) -> bool:
        return bool(self.rewritten)

    @property
    def rewritten_buckets(self) -> int:
        return sum(len(v) for v in self.rewritten.values())

    def summary(self) -> str:
        if not self.rewrites_history and not self.appeared and not self.disappeared:
            return f"{self.before} -> {self.after}: identical counts everywhere."
        lines = [
            f"{self.before} -> {self.after}: {self.unmapped_before} unmapped becomes "
            f"{self.unmapped_after}, and {self.rewritten_buckets} already-counted bucket(s) "
            "change value."
        ]
        for category, buckets in sorted(self.rewritten.items()):
            for label, (was, now) in sorted(buckets.items()):
                lines.append(f"  {category} {label}: {was} -> {now}")
        if self.appeared:
            lines.append(f"  categories that did not exist before: {list(self.appeared)}")
        if self.disappeared:
            lines.append(f"  categories that stop existing: {list(self.disappeared)}")
        lines.append(
            "  Every one of those months was closed. A revised mapping is a retroactive "
            "edit, so a trend published last month is not comparable with the same trend "
            "published today -- and neither report says which mapping produced it."
        )
        return "\n".join(lines)


def _counts(tickets: list[Ticket], mapping: Mapping) -> tuple[dict[str, Counter], int]:
    per_category: dict[str, Counter] = defaultdict(Counter)
    unmapped = 0
    for ticket in tickets:
        if ticket.opened_at is None:
            continue
        canon = mapping.canonical(ticket.raw_category)
        if canon is None:
            unmapped += 1
            continue
        per_category[canon][ticket.opened_at.strftime("%Y-%m")] += 1
    return per_category, unmapped


def version_effect(tickets: list[Ticket], before: Mapping, after: Mapping) -> VersionEffect:
    """Compare two mapping versions over the SAME tickets."""
    counts_before, unmapped_before = _counts(tickets, before)
    counts_after, unmapped_after = _counts(tickets, after)

    rewritten: dict[str, dict[str, tuple[int, int]]] = {}
    for category in sorted(set(counts_before) & set(counts_after)):
        moved = {
            label: (counts_before[category][label], counts_after[category][label])
            for label in sorted(set(counts_before[category]) | set(counts_after[category]))
            if counts_before[category][label] != counts_after[category][label]
        }
        if moved:
            rewritten[category] = moved

    return VersionEffect(
        before=before.version,
        after=after.version,
        unmapped_before=unmapped_before,
        unmapped_after=unmapped_after,
        rewritten=rewritten,
        appeared=tuple(sorted(set(counts_after) - set(counts_before))),
        disappeared=tuple(sorted(set(counts_before) - set(counts_after))),
    )


def why_a_mapping_is_not_cleaning() -> str:
    return (
        "The brief calls this a normalisation PRE-PASS, which puts it before the analysis and "
        "outside it. It is inside it. A count of a category is a count of whatever the mapping "
        "says the category is, so the mapping is one of the terms being multiplied together to "
        "produce the number -- and the only term that gets revised by a human on a Tuesday and "
        "applied backwards over closed months."
    )
