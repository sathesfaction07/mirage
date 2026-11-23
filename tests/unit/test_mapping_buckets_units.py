"""The mapping, the bucketing, and what one counted thing is."""

from __future__ import annotations

import datetime as dt

import pytest

from escalation_insight import buckets, mapping, units
from escalation_insight.mapping import Mapping, MappingSet
from escalation_insight.models import Bucket, Exposure, Grain, Series, Unit
from tests.conftest import DATA, ticket

AS_OF = dt.date(2026, 3, 12)


def _mapping(name="t", **pairs) -> Mapping:
    return Mapping(version=name, description="", categories=dict(pairs))


class TestNormalisationIsDeliberatelyWeak:
    def test_it_folds_case_and_whitespace_only(self):
        assert mapping.normalise("  Shipping   Delay ") == "shipping delay"
        assert mapping.normalise("LATE DELIVERY") == "late delivery"

    def test_it_does_not_guess_synonyms(self):
        """Guessing would hide the merges this project exists to expose."""
        assert mapping.normalise("late delivery") != mapping.normalise("shipping delay")


class TestAnUnknownLabelIsNotACategory:
    def test_it_maps_to_none_rather_than_to_a_bucket(self):
        m = _mapping(**{"shipping delay": "delivery_timing"})
        assert m.canonical("Shipping Delay") == "delivery_timing"
        assert m.canonical("widget went bang") is None

    def test_such_a_row_lands_in_no_bucket_at_all(self):
        m = _mapping(**{"shipping delay": "delivery_timing"})
        placed = buckets.assign(ticket(raw_category="widget went bang"), m, Grain.MONTH, AS_OF)
        assert placed.category is None and placed.bucket is None
        assert "no canonical category" in placed.reason

    def test_a_row_with_no_event_time_lands_in_no_bucket_either(self):
        m = _mapping(**{"shipping delay": "delivery_timing"})
        placed = buckets.assign(ticket(opened=None), m, Grain.MONTH, AS_OF)
        assert placed.category == "delivery_timing" and placed.bucket is None
        assert "no event time" in placed.reason


class TestMergingCanReverseTheTrend:
    """The corpus is built for this and the numbers are checkable by hand."""

    def test_the_same_tickets_go_down_unmerged_and_up_merged(self):
        rows = (
            [ticket(f"T-1{i}", f"C-1{i}", "shipping delay", "2026-01-14") for i in range(10)]
            + [ticket(f"T-2{i}", f"C-2{i}", "shipping delay", "2026-02-11") for i in range(6)]
            + [ticket(f"T-3{i}", f"C-3{i}", "late delivery", "2026-02-18") for i in range(6)]
        )
        unmerged = _mapping("v1", **{"shipping delay": "delivery_timing"})
        merged = _mapping(
            "v2", **{"shipping delay": "delivery_timing", "late delivery": "delivery_timing"}
        )
        down = buckets.build_series(
            rows, category="delivery_timing", mapping=unmerged, unit=Unit.TICKET,
            grain=Grain.MONTH, as_of=AS_OF,
        )
        up = buckets.build_series(
            rows, category="delivery_timing", mapping=merged, unit=Unit.TICKET,
            grain=Grain.MONTH, as_of=AS_OF,
        )
        assert [b.count for b in down.buckets] == [10, 6], "unmerged: falls"
        assert [b.count for b in up.buckets] == [10, 12], "merged: rises"

    def test_the_merges_are_reported(self):
        merged = _mapping(
            "v2", **{"shipping delay": "delivery_timing", "late delivery": "delivery_timing",
                     "return refused": "returns"}
        )
        assert merged.merges == {
            "delivery_timing": ("late delivery", "shipping delay")
        }, "only categories fed by more than one label"


class TestARevisionRewritesClosedMonths:
    def test_a_closed_bucket_changes_value(self, analysis):
        effect = next(v for v in analysis.version_effects if v.before == "v1")
        assert effect.after == "v2"
        assert effect.rewrites_history is True
        assert effect.rewritten["delivery_timing"]["2026-02"] == (6, 12)
        assert effect.unmapped_before == 7 and effect.unmapped_after == 1
        assert "retroactive edit" in effect.summary()

    def test_a_split_makes_a_category_disappear_and_another_appear(self, analysis):
        effect = next(v for v in analysis.version_effects if v.before == "v2")
        assert effect.after == "v3_split"
        assert "delivery_timing" in effect.disappeared
        assert set(effect.appeared) == {"carrier_delay", "promise_missed"}
        assert "stop existing" in effect.summary()

    def test_identical_versions_report_no_change(self):
        rows = [ticket()]
        same = _mapping("a", **{"shipping delay": "delivery_timing"})
        other = _mapping("b", **{"shipping delay": "delivery_timing"})
        effect = mapping.version_effect(rows, same, other)
        assert effect.rewrites_history is False
        assert "identical counts everywhere" in effect.summary()

    def test_the_note_puts_the_mapping_inside_the_analysis(self):
        assert "It is inside it" in mapping.why_a_mapping_is_not_cleaning()


class TestMappingSetLoading:
    def test_it_loads_the_corpus_and_normalises_keys(self):
        loaded = MappingSet.load(DATA / "mappings.json")
        assert loaded.names == ("v1", "v2", "v3_split")
        assert loaded.get("v2").canonical("  SHIPPING  delay ") == "delivery_timing"

    def test_an_unknown_version_names_the_ones_that_exist(self):
        loaded = MappingSet.load(DATA / "mappings.json")
        with pytest.raises(KeyError, match="known versions: v1, v2, v3_split"):
            loaded.get("v9")

    def test_labels_for_a_category(self):
        loaded = MappingSet.load(DATA / "mappings.json")
        assert loaded.get("v2").labels_for("delivery_timing") == (
            "late delivery", "shipping delay",
        )


class TestExposureIsNotUniform:
    def test_february_is_shorter_than_january(self):
        jan = Exposure(label="2026-01", start=dt.date(2026, 1, 1), end=dt.date(2026, 2, 1),
                       as_of=AS_OF)
        feb = Exposure(label="2026-02", start=dt.date(2026, 2, 1), end=dt.date(2026, 3, 1),
                       as_of=AS_OF)
        assert jan.nominal_days == 31 and feb.nominal_days == 28
        assert feb.nominal_days / jan.nominal_days == pytest.approx(0.903, abs=0.001)

    def test_a_complete_bucket_says_so(self):
        jan = Exposure(label="2026-01", start=dt.date(2026, 1, 1), end=dt.date(2026, 2, 1),
                       as_of=AS_OF)
        assert jan.is_complete and jan.elapsed_fraction == 1.0
        assert "complete, 31 days" in jan.note()

    def test_the_newest_bucket_is_partial_and_says_why(self):
        mar = Exposure(label="2026-03", start=dt.date(2026, 3, 1), end=dt.date(2026, 4, 1),
                       as_of=AS_OF)
        assert mar.is_complete is False
        assert mar.elapsed_days == 12 and mar.nominal_days == 31
        assert "low by construction" in mar.note()
        assert "not because anything improved" in mar.note()

    def test_a_bucket_entirely_in_the_future_has_no_elapsed_time(self):
        future = Exposure(label="2026-06", start=dt.date(2026, 6, 1), end=dt.date(2026, 7, 1),
                          as_of=AS_OF)
        assert future.elapsed_days == 0
        assert Bucket(exposure=future, count=0).rate_per_nominal_day is None

    def test_a_partial_bucket_is_not_trustworthy_even_with_nothing_late(self):
        mar = Exposure(label="2026-03", start=dt.date(2026, 3, 1), end=dt.date(2026, 4, 1),
                       as_of=AS_OF)
        assert Bucket(exposure=mar, count=5).trustworthy is False

    def test_a_complete_bucket_with_late_arrivals_is_not_trustworthy_either(self):
        jan = Exposure(label="2026-01", start=dt.date(2026, 1, 1), end=dt.date(2026, 2, 1),
                       as_of=AS_OF)
        assert Bucket(exposure=jan, count=5, late_arrivals=1).trustworthy is False
        assert Bucket(exposure=jan, count=5).trustworthy is True


class TestGrainsDisagree:
    def test_months_are_unequal_and_weeks_are_not(self):
        label, start, end = buckets.month_bounds(dt.date(2026, 2, 17))
        assert (label, (end - start).days) == ("2026-02", 28)
        label, start, end = buckets.week_bounds(dt.date(2026, 2, 17))
        assert (end - start).days == 7

    def test_a_week_straddles_the_month_boundary(self):
        _, start, end = buckets.week_bounds(dt.date(2026, 2, 26))
        assert start.month == 2 and end.month == 3, "one bucket, two months"

    def test_the_grain_can_decide_whether_a_question_is_even_askable(self, analysis):
        """misc sits in one month and two ISO weeks, so half its readings cannot compare."""
        found = next(s for s in analysis.sensitivities if s.category == "misc")
        assert len(found.comparable_choices) == 12
        assert len(found.choices) == 24
        assert "decides whether the question can even be ASKED" in found.summary()


class TestGapsAreFilledWithZeroNotOmitted:
    def test_an_empty_month_between_two_busy_ones_is_a_zero(self):
        rows = [ticket("T-1", "C-1", opened="2026-01-05"),
                ticket("T-2", "C-2", opened="2026-03-05", recorded="2026-03-06")]
        series = buckets.build_series(
            rows, category="delivery_timing",
            mapping=_mapping(**{"shipping delay": "delivery_timing"}),
            unit=Unit.TICKET, grain=Grain.MONTH, as_of=dt.date(2026, 4, 1),
        )
        assert [b.label for b in series.buckets] == ["2026-01", "2026-02", "2026-03"]
        assert [b.count for b in series.buckets] == [1, 0, 1]

    def test_a_category_with_no_rows_gives_an_empty_series(self):
        series = buckets.build_series(
            [ticket()], category="nothing_here",
            mapping=_mapping(**{"shipping delay": "delivery_timing"}),
            unit=Unit.TICKET, grain=Grain.MONTH, as_of=AS_OF,
        )
        assert series.buckets == () and series.total == 0
        assert buckets.censoring(series) is None

    def test_buckets_must_be_in_time_order(self):
        jan = Bucket(exposure=Exposure(label="2026-01", start=dt.date(2026, 1, 1),
                                       end=dt.date(2026, 2, 1), as_of=AS_OF), count=1)
        feb = Bucket(exposure=Exposure(label="2026-02", start=dt.date(2026, 2, 1),
                                       end=dt.date(2026, 3, 1), as_of=AS_OF), count=1)
        with pytest.raises(ValueError, match="time order"):
            Series(category="c", unit=Unit.TICKET, grain=Grain.MONTH,
                   mapping_version="v", buckets=(feb, jan))


class TestTheUnitChangesTheDirection:
    def test_tickets_rise_while_cases_fall(self, analysis):
        effect = next(u for u in analysis.unit_effects if u.category == "returns")
        assert dict(effect.by_ticket)["2026-01"] == 6
        assert dict(effect.by_ticket)["2026-02"] == 9, "up by ticket"
        assert dict(effect.by_case)["2026-01"] == 6
        assert dict(effect.by_case)["2026-02"] == 4, "down by case"

    def test_deduplication_is_not_spread_evenly(self, analysis):
        effect = next(u for u in analysis.unit_effects if u.category == "returns")
        assert dict(effect.removed) == {"2026-01": 0, "2026-02": 5, "2026-03": 0}
        assert effect.evenly_spread is False
        assert effect.worst_hit == ("2026-02", 5)
        assert "subtracts most from the period that went worst" in effect.summary()

    def test_an_even_collapse_is_reported_as_even(self):
        jan = Exposure(label="2026-01", start=dt.date(2026, 1, 1), end=dt.date(2026, 2, 1),
                       as_of=AS_OF)
        def series(count):
            return Series(category="c", unit=Unit.TICKET, grain=Grain.MONTH,
                          mapping_version="v",
                          buckets=(Bucket(exposure=jan, count=count),))
        effect = units.unit_effect(series(4), series(4))
        assert effect.evenly_spread is True
        assert effect.worst_hit is None
        assert "not even" not in effect.summary()

    def test_comparing_two_different_categories_is_refused(self):
        jan = Exposure(label="2026-01", start=dt.date(2026, 1, 1), end=dt.date(2026, 2, 1),
                       as_of=AS_OF)
        a = Series(category="a", unit=Unit.TICKET, grain=Grain.MONTH, mapping_version="v",
                   buckets=(Bucket(exposure=jan, count=1),))
        b = Series(category="b", unit=Unit.CASE, grain=Grain.MONTH, mapping_version="v",
                   buckets=(Bucket(exposure=jan, count=1),))
        with pytest.raises(ValueError, match="two different categories"):
            units.unit_effect(a, b)

    def test_the_deepest_case_collapses_to_one(self, analysis):
        deepest = units.depths(analysis.tickets)[0]
        assert deepest.case_id == "C-600"
        assert deepest.tickets == 6 and deepest.reopens == 5
        assert "indistinguishable from a case that was answered once" in deepest.note()

    def test_a_case_is_counted_where_the_problem_started(self):
        rows = [ticket("T-1", "C-1", opened="2026-01-20"),
                ticket("T-2", "C-1", opened="2026-02-05", reopen_of="T-1")]
        collapsed = units.collapse(rows, Unit.CASE)
        assert [t.ticket_id for t in collapsed] == ["T-1"], "earliest, not latest"

    def test_collapsing_by_ticket_changes_nothing(self):
        rows = [ticket("T-1"), ticket("T-2", "C-1")]
        assert units.collapse(rows, Unit.TICKET) == rows

    def test_a_row_with_no_event_time_cannot_represent_its_case(self):
        rows = [ticket("T-1", "C-1", opened=None), ticket("T-2", "C-1", opened="2026-01-05")]
        assert [t.ticket_id for t in units.collapse(rows, Unit.CASE)] == ["T-2"]

    def test_an_orphan_reopen_breaks_lineage(self, analysis):
        assert units.lineage_disagreement(analysis.tickets) == ("T-912",)

    def test_the_unit_everybody_wants_is_not_available(self):
        note = units.why_neither_unit_is_right()
        assert "DISTINCT UNDERLYING PROBLEM" in note
        assert "bracket the truth from opposite sides" in note


class TestCensoring:
    def test_the_newest_bucket_is_understated_by_the_lag(self, analysis):
        found = next(c for c in analysis.censored if c.category == "delivery_timing")
        assert (found.elapsed_days, found.nominal_days) == (12, 31)
        assert found.visible == 2 and found.late_arrivals == 1
        assert found.true_so_far == 3
        assert found.understated_by == pytest.approx(1 / 3)
        assert "understates the month-to-date by 33%" in found.summary()

    def test_it_names_the_dilemma_and_refuses_to_resolve_it(self, analysis):
        text = analysis.censored[0].summary()
        assert "silent about the only month anybody is asking about" in text
        assert "a decline that is made of the calendar and the lag" in text
        assert "There is no third option" in text

    def test_it_carries_its_category_so_two_entries_are_distinguishable(self, analysis):
        assert len(analysis.censored) == 2
        assert {c.category for c in analysis.censored} == {"delivery_timing", "returns"}
        assert all(c.category in c.summary() for c in analysis.censored)

    def test_nothing_is_censored_once_the_month_is_over(self, settings):
        from escalation_insight.aggregate import run

        later = run(settings.model_copy(update={"as_of": dt.date(2026, 4, 15)}))
        assert later.censored == ()

    def test_a_bucket_with_no_late_arrivals_omits_the_understatement_line(self):
        mar = Exposure(label="2026-03", start=dt.date(2026, 3, 1), end=dt.date(2026, 4, 1),
                       as_of=AS_OF)
        series = Series(category="c", unit=Unit.TICKET, grain=Grain.MONTH,
                        mapping_version="v", buckets=(Bucket(exposure=mar, count=3),))
        found = buckets.censoring(series)
        assert found.late_arrivals == 0
        assert "understates the month-to-date" not in found.summary()
        assert "There is no third option" in found.summary()

    def test_an_empty_partial_bucket_has_no_understatement_to_report(self):
        mar = Exposure(label="2026-03", start=dt.date(2026, 3, 1), end=dt.date(2026, 4, 1),
                       as_of=AS_OF)
        series = Series(category="c", unit=Unit.TICKET, grain=Grain.MONTH,
                        mapping_version="v", buckets=(Bucket(exposure=mar, count=0),))
        assert buckets.censoring(series).understated_by is None


class TestTicketFacts:
    def test_the_lag_needs_both_dates(self):
        assert ticket(opened="2026-01-01", recorded="2026-01-04").lag_days == 3
        assert ticket(opened=None).lag_days is None
        assert ticket(recorded=None).lag_days is None

    def test_a_reopen_knows_it_is_one(self):
        assert ticket(reopen_of="T-0").is_reopen is True
        assert ticket().is_reopen is False
