"""One question decides whether something FAILS: can the producer of the export fix it?

A defect in a row is fixable by whoever exported it -- correct the label, populate the date,
stop emitting the id twice. A fact about the world is not: nobody can fix February being
short, or agree a taxonomy by editing a row, or make a question count reveal why somebody
asked.

So the gate is narrow on purpose, and everything it will not fail on is still printed. A gate
that failed on ambiguity would fail on every real export forever, and be turned off.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .aggregate import Analysis
from .models import TicketFault

FAULT_FIXES: dict[TicketFault, str] = {
    TicketFault.NO_EVENT_TIME: "populate the event timestamp; without it the row is in no period",
    TicketFault.RECORDED_BEFORE_EVENT: (
        "fix the clock or the field order; a recording cannot precede its event"
    ),
    TicketFault.DUPLICATE_ID: "emit each id once, or say which row supersedes which",
    TicketFault.ORPHAN_REOPEN: "include the parent ticket, or clear the reopen reference",
    TicketFault.UNMAPPED_CATEGORY: (
        "correct the label, or add it to the mapping and say which version"
    ),
}


class Verdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    failures: tuple[str, ...]
    reports: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1


def check(analysis: Analysis) -> Verdict:
    failures: list[str] = []
    for fault, ids in sorted(analysis.ticket_faults.items()):
        failures.append(
            f"{fault.value}: {len(ids)} row(s) {list(ids)} -- {FAULT_FIXES[fault]}"
        )

    reports: list[str] = []
    for censored in analysis.censored:
        reports.append(
            f"{censored.category}: newest bucket {censored.label} is {censored.elapsed_days} of "
            f"{censored.nominal_days} days elapsed with {censored.late_arrivals} escalation(s) "
            "recorded after the cut-off. Nobody can fix time."
        )
    for category in analysis.settings_decide:
        found = next(s for s in analysis.sensitivities if s.category == category)
        reports.append(
            f"{category}: {len(found.choices)} readings give "
            f"{[d.value for d in found.directions]}. Which one this report leads with is a "
            "configuration decision, and configuring it is a judgement, not a defect."
        )
    for category in analysis.never_established:
        reports.append(
            f"{category}: no reading produced a direction. Too few escalations to distinguish "
            "any movement from a constant rate, which is a fact about the volume."
        )
    for category in analysis.not_comparable:
        reports.append(
            f"{category}: occupies fewer than two usable buckets, so no comparison could be "
            "formed. Its silence is an absence of evidence, not evidence of stability."
        )
    for category in analysis.deleted_by_a_revision:
        found = next(s for s in analysis.sensitivities if s.category == category)
        reports.append(
            f"{category}: does not exist under {list(found.unavailable)}, so a revision would "
            "delete this row from the report rather than change it. A taxonomy decision."
        )
    for effect in analysis.version_effects:
        if effect.rewrites_history:
            reports.append(
                f"{effect.before} -> {effect.after}: {effect.rewritten_buckets} closed "
                "bucket(s) change value. Revising a mapping is a retroactive edit, and "
                "revising it may still be the right thing to do."
            )
    for effect in analysis.unit_effects:
        if not effect.evenly_spread and (hit := effect.worst_hit):
            reports.append(
                f"{effect.category}: collapsing tickets into cases removes {hit[1]} from "
                f"{hit[0]} and fewer elsewhere, so deduplication changes the shape and not "
                "just the scale. Choosing a unit is not a defect."
            )
    if not analysis.ranking.agree:
        reports.append(
            f"question ranking: by volume {list(analysis.ranking.by_volume)}, by rate "
            f"{list(analysis.ranking.by_rate)}. Both are defensible and they disagree about "
            "which topic is the biggest problem."
        )
    for gap in analysis.topic_gaps:
        if gap.documented and gap.questions:
            reports.append(
                f"{gap.category}: {gap.questions} questions on a topic documented at section "
                f"{gap.section}, so it is not a missing section. Which of the three remaining "
                "causes it is cannot be read from this export."
            )
    return Verdict(failures=tuple(failures), reports=tuple(reports))


def what_is_not_gated() -> str:
    return (
        "Not gated: an unfinished newest bucket, a direction that depends on the settings, a "
        "category too small to say anything about, a category a revision would delete, a "
        "mapping revision that rewrites closed months, an uneven deduplication, two "
        "defensible rankings that disagree, and a question count whose cause is unknowable. "
        "Every one of those is real and none is a defect in the export, so failing a build "
        "over them would only teach people to stop running the check."
    )
