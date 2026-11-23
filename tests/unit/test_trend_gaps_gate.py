"""The direction, the gap inference, and what the gate will and will not fail on."""

from __future__ import annotations

import datetime as dt

import pytest

from escalation_insight import gaps as gaps_mod
from escalation_insight import trend as trend_mod
from escalation_insight.aggregate import faults, run
from escalation_insight.gate import check, what_is_not_gated
from escalation_insight.mapping import Mapping
from escalation_insight.models import (
    Bucket,
    Direction,
    Exposure,
    GapCause,
    Grain,
    Series,
    TicketFault,
    Unit,
)
from tests.conftest import ticket

AS_OF = dt.date(2026, 3, 12)


def _series(*counts_and_labels, as_of=AS_OF) -> Series:
    made = []
    for label, count, start, end in counts_and_labels:
        made.append(
            Bucket(
                exposure=Exposure(label=label, start=start, end=end, as_of=as_of), count=count
            )
        )
    return Series(category="c", unit=Unit.TICKET, grain=Grain.MONTH,
                  mapping_version="v", buckets=tuple(made))


JAN = ("2026-01", 10, dt.date(2026, 1, 1), dt.date(2026, 2, 1))
FEB = ("2026-02", 12, dt.date(2026, 2, 1), dt.date(2026, 3, 1))
MAR = ("2026-03", 2, dt.date(2026, 3, 1), dt.date(2026, 4, 1))


class TestWhichTwoBucketsATrendCompares:
    def test_excluding_the_newest_bucket_changes_the_endpoints(self):
        series = _series(JAN, FEB, MAR)
        strict = trend_mod.endpoints(series, complete_only=True)
        loose = trend_mod.endpoints(series, complete_only=False)
        assert (strict[0].label, strict[1].label) == ("2026-01", "2026-02")
        assert (loose[0].label, loose[1].label) == ("2026-01", "2026-03")

    def test_one_bucket_is_not_a_trend(self):
        assert trend_mod.endpoints(_series(JAN), complete_only=True) is None
        assert trend_mod.trend(_series(JAN), alpha=0.05) is None

    def test_a_bucket_with_no_elapsed_time_is_not_an_endpoint(self):
        future = ("2026-09", 0, dt.date(2026, 9, 1), dt.date(2026, 10, 1))
        pair = trend_mod.endpoints(_series(JAN, FEB, future), complete_only=False)
        assert pair[1].label == "2026-02", "the future bucket cannot anchor anything"

    def test_the_claim_names_the_buckets_it_used(self):
        claim = trend_mod.trend(_series(JAN, FEB), alpha=0.05)
        assert claim.label == "c 2026-01->2026-02"


class TestUnknownIsNotFlat:
    def test_an_unconvincing_movement_is_unknown(self):
        claim = trend_mod.trend(_series(JAN, FEB), alpha=0.05)
        assert claim.direction is Direction.UNKNOWN
        assert "NOT evidence of a change" in claim.headline()

    def test_a_convincing_movement_gets_a_direction(self):
        big_jan = ("2026-01", 40, dt.date(2026, 1, 1), dt.date(2026, 2, 1))
        big_feb = ("2026-02", 120, dt.date(2026, 2, 1), dt.date(2026, 3, 1))
        claim = trend_mod.trend(_series(big_jan, big_feb), alpha=0.05)
        assert claim.direction is Direction.UP
        assert "the direction is UP" in claim.headline()

    def test_a_convincing_fall_is_down(self):
        big_jan = ("2026-01", 120, dt.date(2026, 1, 1), dt.date(2026, 2, 1))
        small_feb = ("2026-02", 40, dt.date(2026, 2, 1), dt.date(2026, 3, 1))
        assert trend_mod.trend(_series(big_jan, small_feb), alpha=0.05).direction is (
            Direction.DOWN
        )

    def test_there_is_no_flat_and_that_is_provable(self):
        """An exactly-constant rate is the MODAL outcome, whose two-sided p-value is 1.0.

        So `p <= alpha` cannot hold for any alpha below 1, and a verdict of "the rate did not
        change" is unreachable from this kind of evidence. Checked by algebra over a range of
        exposures rather than asserted once.
        """
        from escalation_insight.evidence import claim as make
        from escalation_insight.evidence import two_sided_p

        assert not hasattr(Direction, "FLAT")
        for total, days_before, days_after in (
            (300, 30, 30), (22, 31, 28), (100, 31, 30), (59, 31, 28),
        ):
            share = days_after / (days_before + days_after)
            modal = round(total * share)
            assert two_sided_p(modal, total, share) == pytest.approx(1.0), (
                "the modal outcome is never surprising, whatever the exposures"
            )
        exact = make("c", count_before=300, count_after=300, days_before=30, days_after=30,
                     alpha=0.99)
        assert exact.rate_ratio == 1.0
        assert exact.p_value == 1.0
        assert exact.direction is Direction.UNKNOWN, "not FLAT -- there is no such answer"

    def test_the_enum_has_exactly_three_values(self):
        assert [d.value for d in Direction] == ["UP", "DOWN", "UNKNOWN"]
        assert "failing to be surprised is" in Direction.__doc__


class TestTheDirectionCanBeAChoice:
    def test_two_categories_have_their_direction_decided_by_settings(self, analysis, result):
        assert result["settings_decide_direction"] == ["delivery_timing", "returns"]
        for category in result["settings_decide_direction"]:
            found = next(s for s in analysis.sensitivities if s.category == category)
            assert found.direction_is_a_choice is True
            assert set(found.directions) == {Direction.DOWN, Direction.UNKNOWN}
            assert "decided by configuration, not by what happened" in found.summary()

    def test_nothing_survives_every_reading_on_this_corpus(self, result):
        assert result["survives_every_reading"] == []

    def test_a_category_deleted_by_a_revision_is_reported_not_skipped(self, analysis, result):
        assert result["deleted_by_a_revision"] == ["delivery_timing"]
        found = next(s for s in analysis.sensitivities if s.category == "delivery_timing")
        assert found.unavailable == ("v3_split",)
        assert "a revision that splits a category deletes it" in found.summary()
        assert len(found.choices) == 16, "8 readings could not be run"

    def test_never_established_is_kept_apart_from_disagreeing(self, result):
        assert sorted(result["never_established"]) == ["misc", "packaging"]
        assert not set(result["never_established"]) & set(
            result["settings_decide_direction"]
        )

    def test_a_unanimous_direction_says_it_does_not_depend_on_settings(self):
        big = Series(
            category="c", unit=Unit.TICKET, grain=Grain.MONTH, mapping_version="v",
            buckets=(
                Bucket(exposure=Exposure(label="2026-01", start=dt.date(2026, 1, 1),
                                         end=dt.date(2026, 2, 1), as_of=AS_OF), count=40),
                Bucket(exposure=Exposure(label="2026-02", start=dt.date(2026, 2, 1),
                                         end=dt.date(2026, 3, 1), as_of=AS_OF), count=120),
            ),
        )
        found = trend_mod.sensitivity(
            {("v1", "TICKET", "MONTH", True): big}, category="c", alpha=0.05
        )
        assert found.direction_is_a_choice is False
        assert "does not depend on the settings" in found.summary()

    def test_no_comparison_possible_is_its_own_state(self):
        single = Series(
            category="c", unit=Unit.TICKET, grain=Grain.MONTH, mapping_version="v",
            buckets=(
                Bucket(exposure=Exposure(label="2026-01", start=dt.date(2026, 1, 1),
                                         end=dt.date(2026, 2, 1), as_of=AS_OF), count=3),
            ),
        )
        found = trend_mod.sensitivity(
            {("v1", "TICKET", "MONTH", True): single}, category="c", alpha=0.05
        )
        assert found.no_comparison_possible is True
        assert found.never_established is False, "nothing was tested, so nothing came back"
        assert "records an absence of evidence rather than a test" in found.summary()

    def test_an_empty_sensitivity_has_no_unknown_share(self):
        empty = trend_mod.Sensitivity(category="c", choices=())
        assert empty.unknown_share == 0.0

    def test_the_combinations_are_the_product_of_the_choices(self):
        combos = trend_mod.combinations(["v1", "v2"], ["TICKET"], ["MONTH", "WEEK"])
        assert len(combos) == 2 * 1 * 2 * 2

    def test_the_note_names_all_five_terms(self):
        note = trend_mod.why_a_trend_is_not_an_observation()
        for term in ("how many got reported", "categorised", "when the system heard",
                     "whether the category existed"):
            assert term in note

    def test_a_choice_labels_itself(self):
        choice = trend_mod.Choice(
            mapping_version="v1", unit="TICKET", grain="MONTH", complete_only=False,
            direction=Direction.UP, counts=(1, 2), p_value=0.01,
        )
        assert "newest=INCLUDED" in choice.label()
        assert choice.comparable is True


class TestAGapIsNotObservable:
    def test_being_documented_rules_out_exactly_one_cause(self, analysis):
        documented = next(g for g in analysis.topic_gaps if g.category == "returns")
        assert documented.documented is True and documented.section == "4.2"
        assert GapCause.NOT_DOCUMENTED not in documented.candidates
        assert len(documented.candidates) == 3
        assert documented.adding_a_section_would_help is False

    def test_being_undocumented_rules_out_nothing(self, analysis):
        undocumented = next(g for g in analysis.topic_gaps if g.category == "packaging")
        assert undocumented.documented is False
        assert len(undocumented.candidates) == 4
        assert undocumented.adding_a_section_would_help is None, "undetermined, not True"
        assert "rules nothing out" in undocumented.note()

    def test_the_most_asked_topic_is_the_one_the_sop_covers(self, analysis, result):
        assert result["ranking_by_volume"][0] == "returns"
        assert "returns" in result["documented_and_still_asked"]

    def test_dividing_by_volume_changes_the_ranking(self, analysis, result):
        assert result["ranking_agrees"] is False
        assert result["ranking_by_volume"] == ["returns", "delivery_timing", "packaging"]
        assert result["ranking_by_rate"] == ["returns", "packaging", "delivery_timing"]
        assert set(analysis.ranking.moved) == {"delivery_timing", "packaging"}
        assert "decided by whether somebody divided" in analysis.ranking.summary()

    def test_a_topic_with_no_escalations_has_no_rate(self):
        gap = gaps_mod.TopicGap(category="c", questions=5, escalations=0, section=None)
        assert gap.per_escalation is None
        assert "n/a per escalation" in gap.note()

    def test_agreeing_rankings_say_so(self):
        one = gaps_mod.TopicGap(category="a", questions=9, escalations=3, section=None)
        two = gaps_mod.TopicGap(category="b", questions=2, escalations=4, section=None)
        ranked = gaps_mod.ranking((one, two))
        assert ranked.agree is True and ranked.moved == ()
        assert "Same order both ways" in ranked.summary()

    def test_the_note_says_a_longer_document_is_harder_to_search(self):
        assert "harder document to find anything in" in gaps_mod.why_a_gap_is_not_observable()

    def test_every_cause_carries_a_note(self):
        from escalation_insight.models import GAP_CAUSE_NOTES

        assert set(GAP_CAUSE_NOTES) == set(GapCause)
        assert "makes this WORSE" in GAP_CAUSE_NOTES[GapCause.DOCUMENTED_NOT_FINDABLE]

    def test_the_sop_reports_what_it_covers(self, analysis):
        assert analysis.sop.documents("returns") is True
        assert analysis.sop.documents("packaging") is False
        assert analysis.sop.section_for("nothing") is None


class TestFaultDetection:
    def test_the_corpus_carries_exactly_one_of_each(self, result):
        assert result["faults"] == {
            "DUPLICATE_ID": ["T-910"],
            "NO_EVENT_TIME": ["T-901"],
            "ORPHAN_REOPEN": ["T-912"],
            "RECORDED_BEFORE_EVENT": ["T-911"],
            "UNMAPPED_CATEGORY": ["T-900"],
        }

    def test_a_missing_event_time_masks_the_ordering_check(self):
        """With no event time there is nothing for the recording to precede."""
        found = faults(
            [ticket("T-1", opened=None, recorded="2026-01-01")],
            Mapping(version="v", description="", categories={"shipping delay": "c"}),
        )
        assert found[TicketFault.NO_EVENT_TIME] == ("T-1",)
        assert TicketFault.RECORDED_BEFORE_EVENT not in found

    def test_a_clean_export_has_no_faults(self):
        found = faults(
            [ticket("T-1"), ticket("T-2", "C-2")],
            Mapping(version="v", description="", categories={"shipping delay": "c"}),
        )
        assert found == {}

    def test_a_missing_recorded_date_is_not_an_ordering_fault(self):
        found = faults(
            [ticket("T-1", recorded=None)],
            Mapping(version="v", description="", categories={"shipping delay": "c"}),
        )
        assert found == {}


class TestTheGateIsNarrowOnPurpose:
    def test_it_fails_only_on_producer_fixable_defects(self, analysis):
        verdict = check(analysis)
        assert verdict.ok is False and verdict.exit_code == 1
        assert len(verdict.failures) == 5
        for fault in TicketFault:
            assert any(fault.value in f for f in verdict.failures)
        assert all("--" in f for f in verdict.failures), "every failure names its fix"

    def test_it_reports_without_failing_on_everything_else(self, analysis):
        reports = " ".join(check(analysis).reports)
        for phrase in (
            "Nobody can fix time",
            "configuring it is a judgement, not a defect",
            "a fact about the volume",
            "A taxonomy decision",
            "may still be the right thing to do",
            "Choosing a unit is not a defect",
            "they disagree about which topic is the biggest problem",
            "cannot be read from this export",
        ):
            assert phrase in reports, phrase

    def test_a_clean_export_passes_while_still_reporting(self, tmp_path):
        (tmp_path / "tickets.csv").write_text(
            "ticket_id,case_id,raw_category,opened_at,recorded_at,team,reopen_of\n"
            "T-1,C-1,shipping delay,2026-01-05,2026-01-06,logistics,\n"
            "T-2,C-2,shipping delay,2026-02-05,2026-02-06,logistics,\n",
            encoding="utf-8",
        )
        (tmp_path / "mappings.json").write_text(
            '{"as_of": "2026-04-01", "versions": {"v2": {"description": "d",'
            ' "categories": {"shipping delay": "delivery_timing"}}}}',
            encoding="utf-8",
        )
        (tmp_path / "sop.json").write_text(
            '{"document": "d", "revision": 1, "covers": {"delivery_timing": "1.1"},'
            ' "questions": {"delivery_timing": 4}}',
            encoding="utf-8",
        )
        from escalation_insight.config import Settings

        verdict = check(run(Settings(data_dir=tmp_path)))
        assert verdict.ok is True and verdict.exit_code == 0
        assert verdict.failures == ()
        assert any("cannot be read from this export" in r for r in verdict.reports), (
            "a passing export still has unanswerable questions in it"
        )

    def test_what_is_not_gated_explains_why(self):
        note = what_is_not_gated()
        assert "teach people to stop running the check" in note
