"""Every command, through the real entry point, asserting on the reasoning it prints.

`flat` collapses whitespace before matching so these assert on SENTENCES rather than on
whatever the terminal width happened to do to them.
"""

from __future__ import annotations

import re

import pytest
from click.testing import CliRunner

from escalation_insight.cli import main
from tests.conftest import DATA


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


@pytest.fixture
def run():
    runner = CliRunner()

    def invoke(*args: str, expect: int = 0):
        result = runner.invoke(main, [*args, "--data-dir", str(DATA)], catch_exceptions=False)
        assert result.exit_code == expect, (
            f"{args} exited {result.exit_code}, wanted {expect}\n{result.output}"
        )
        return flat(result.output)

    return invoke


class TestReport:
    def test_it_leads_with_what_the_settings_decided(self, run):
        out = run("report")
        assert "52 tickets, 5 of them carrying a producer-fixable defect" in out
        assert "0 show a direction that survives every reading" in out
        assert "2 have their direction decided by the settings" in out

    def test_every_count_is_printed_beside_its_exposure(self, run):
        out = run("report")
        assert "31/31" in out and "28/28" in out and "12/31" in out
        assert "(partial)" in out

    def test_it_says_the_newest_bucket_is_excluded_from_the_claims(self, run):
        out = run("report")
        assert "newest bucket is EXCLUDED from every direction below" in out
        assert "nothing here describes 2026-03" in out

    def test_no_ratio_appears_without_its_evidence(self, run):
        out = run("report")
        assert "3x by count, 3.3x by rate" in out
        assert "NOT evidence of a change" in out

    def test_it_publishes_the_five_terms_a_count_is_made_of(self, run):
        out = run("report")
        assert "It is events x how many got reported x how the reporter categorised them" in out

    def test_including_the_newest_bucket_changes_the_comparison(self, run):
        excluded = run("report")
        included = run("report", "--include-newest")
        assert "2026-01->2026-02" in excluded
        assert "2026-01->2026-03" in included


class TestTrend:
    def test_it_runs_the_same_question_under_every_reading(self, run):
        out = run("trend")
        assert "24 readings of the same escalations produce 2 distinct direction(s)" in out
        assert "decided by configuration, not by what happened" in out

    def test_it_reports_a_category_a_revision_would_delete(self, run):
        out = run("trend")
        assert "does not exist at all under ['v3_split']" in out
        assert "a revision that splits a category deletes it" in out

    def test_it_separates_untested_from_tested_and_unconvincing(self, run):
        out = run("trend")
        assert "decides whether the question can even be ASKED" in out
        assert "Every reading came back UNKNOWN" in out
        assert "not the same as the rate being flat" in out


class TestEvidence:
    def test_it_shows_the_same_ratio_reaching_opposite_verdicts(self, run):
        out = run("evidence")
        assert "Both of these are a 3x increase" in out
        assert "compatible with having found nothing at all" in out

    def test_it_shows_the_calendar_deciding_a_verdict(self, run):
        out = run("evidence")
        assert "The verdict FLIPS" in out
        assert "The shorter month was doing the work" in out

    def test_it_says_when_a_comparison_could_never_have_found_anything(self, run):
        out = run("evidence")
        assert "NO split would have reached alpha 0.05" in out
        assert "finding none says nothing about the world" in out

    def test_it_names_why_a_ratio_hides_its_own_evidence(self, run):
        assert "A ratio is scale-free" in run("evidence")


class TestMapping:
    def test_it_shows_a_revision_rewriting_a_closed_month(self, run):
        out = run("mapping")
        assert "delivery_timing 2026-02: 6 -> 12" in out
        assert "A revised mapping is a retroactive edit" in out

    def test_it_shows_a_split_deleting_and_creating_categories(self, run):
        out = run("mapping")
        assert "categories that stop existing: ['delivery_timing']" in out
        assert "['carrier_delay', 'promise_missed']" in out

    def test_it_puts_the_mapping_inside_the_analysis(self, run):
        assert "It is inside it" in run("mapping")

    def test_it_credits_the_project_that_already_built_the_label_map(self):
        from escalation_insight import mapping

        assert "StatusChecker" in mapping.__doc__
        assert "PER MARKETPLACE" in mapping.__doc__


class TestUnit:
    def test_it_shows_deduplication_taking_rows_from_one_month(self, run):
        out = run("unit")
        assert "by TICKET 2026-01=6 2026-02=9" in out
        assert "by CASE 2026-01=6 2026-02=4" in out
        assert "removed 2026-01=0 2026-02=5 2026-03=0" in out
        assert "subtracts most from the period that went worst" in out

    def test_it_names_the_case_that_would_not_close(self, run):
        out = run("unit")
        assert "C-600: 6 tickets, 5 of them reopens" in out
        assert "indistinguishable from a case that was answered once and closed" in out

    def test_it_reports_the_broken_lineage(self, run):
        assert "['T-912'] point at a ticket absent from the export" in run("unit")

    def test_it_says_the_unit_everybody_wants_is_unavailable(self, run):
        assert "DISTINCT UNDERLYING PROBLEM" in run("unit")

    def test_the_module_credits_the_projects_that_own_dedup(self):
        from escalation_insight import units

        assert "CaseSearch" in units.__doc__ and "MultiSourceAgg" in units.__doc__


class TestCensoring:
    def test_it_quantifies_the_hidden_volume(self, run):
        out = run("censoring")
        assert (
            "delivery_timing: 2026-03 is the newest bucket and it is not finished: 12 of 31"
            in out
        )
        assert "understates the month-to-date by 33%" in out

    def test_it_states_the_dilemma_without_resolving_it(self, run):
        out = run("censoring")
        assert "silent about the only month anybody is asking about" in out
        assert "There is no third option" in out

    def test_a_later_cutoff_leaves_nothing_censored(self, run):
        assert "Every bucket is complete" in run("censoring", "--as-of", "2026-05-01")

    def test_the_module_credits_rule_monitor(self):
        from escalation_insight import buckets

        assert "RuleMonitor" in buckets.__doc__
        assert "breakdown point" in buckets.__doc__


class TestGaps:
    def test_the_top_topic_is_the_one_the_sop_documents(self, run):
        out = run("gaps")
        assert "returns │ 41 │ 16 │ 2.56 │ section 4.2 │ 3" in out
        assert "the one cause a new section would fix is ruled out" in out

    def test_dividing_changes_which_topic_looks_worst(self, run):
        out = run("gaps")
        assert "by questions asked : ['returns', 'delivery_timing', 'packaging']" in out
        assert "PER escalation: ['returns', 'packaging', 'delivery_timing']" in out
        assert "decided by whether somebody divided" in out

    def test_undocumented_rules_nothing_out(self, run):
        out = run("gaps")
        assert (
            "packaging: 3 questions over 4 escalations (0.75 per escalation), NOT documented"
            in out
        )
        assert "Undocumented, which rules nothing out" in out

    def test_it_warns_that_adding_a_section_can_make_it_worse(self, run):
        assert "adding a section makes this WORSE" in run("gaps")


class TestDoctor:
    def test_it_separates_chosen_from_measured(self, run):
        out = run("doctor")
        assert "Chosen, not measured" in out
        assert "Measured from the export" in out
        assert "Never measured, by anything here" in out
        assert "Judgements, not findings" in out

    def test_every_setting_says_what_it_decides(self, run):
        out = run("doctor")
        for setting in ("mapping_version", "unit", "grain", "complete_only", "alpha"):
            assert setting in out
        assert "Merging two labels can reverse a trend" in out

    def test_it_admits_what_it_never_measures(self, run):
        out = run("doctor")
        assert "how many escalations HAPPENED -- only how many were recorded" in out
        assert "whether escalations arrive uniformly inside a bucket" in out
        assert "why anybody asked a question" in out

    def test_alpha_is_named_a_convention(self, run):
        assert "alpha 0.05 is a convention borrowed from elsewhere" in run("doctor")


class TestExplain:
    def test_it_shows_one_category_with_its_provenance(self, run):
        out = run("explain", "returns")
        assert "unit=TICKET grain=MONTH mapping=v2" in out
        assert "2026-03: INCOMPLETE" in out

    def test_it_carries_the_gap_and_the_unit_effect_too(self, run):
        out = run("explain", "returns")
        assert "subtracts most from the period that went worst" in out
        assert "documented at section 4.2" in out

    def test_an_unknown_category_lists_the_known_ones(self, run):
        out = run("explain", "nonsense")
        assert "no category 'nonsense'" in out
        assert "delivery_timing" in out and "returns" in out

    def test_a_category_with_one_bucket_says_so(self, run):
        """And in the SAME words `report` uses -- one fact should not have two phrasings."""
        assert "misc: fewer than two comparable buckets, so no claim" in run("explain", "misc")
        assert "misc: fewer than two comparable buckets, so no claim" in run("report")


class TestCheck:
    def test_it_fails_on_the_five_producer_fixable_defects(self, run):
        out = run("check", expect=1)
        assert "Fixable at the source" in out
        assert "FAIL on 5 producer-fixable defect(s)" in out
        for fault in ("DUPLICATE_ID", "NO_EVENT_TIME", "ORPHAN_REOPEN",
                      "RECORDED_BEFORE_EVENT", "UNMAPPED_CATEGORY"):
            assert fault in out

    def test_every_failure_names_the_fix(self, run):
        out = run("check", expect=1)
        assert "populate the event timestamp" in out
        assert "emit each id once, or say which row supersedes which" in out
        assert "correct the label, or add it to the mapping" in out

    def test_it_reports_the_rest_without_failing(self, run):
        out = run("check", expect=1)
        assert "Reported and NOT failed on" in out
        assert "Nobody can fix time" in out
        assert "configuring it is a judgement, not a defect" in out
        assert "Choosing a unit is not a defect" in out

    def test_it_says_why_it_declines_to_gate_on_ambiguity(self, run):
        assert "teach people to stop running the check" in run("check", expect=1)

    def test_a_clean_export_passes(self, tmp_path):
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
        result = CliRunner().invoke(
            main, ["check", "--data-dir", str(tmp_path)], catch_exceptions=False
        )
        assert result.exit_code == 0
        assert "Nothing fixable at source" in flat(result.output)
        assert "PASS" in flat(result.output)

    def test_one_bad_label_alone_is_enough_to_fail(self, tmp_path):
        (tmp_path / "tickets.csv").write_text(
            "ticket_id,case_id,raw_category,opened_at,recorded_at,team,reopen_of\n"
            "T-1,C-1,shipping delay,2026-01-05,2026-01-06,logistics,\n"
            "T-2,C-2,widget went bang,2026-02-05,2026-02-06,logistics,\n",
            encoding="utf-8",
        )
        (tmp_path / "mappings.json").write_text(
            '{"as_of": "2026-04-01", "versions": {"v2": {"description": "d",'
            ' "categories": {"shipping delay": "delivery_timing"}}}}',
            encoding="utf-8",
        )
        (tmp_path / "sop.json").write_text(
            '{"document": "d", "revision": 1, "covers": {}, "questions": {}}',
            encoding="utf-8",
        )
        result = CliRunner().invoke(
            main, ["check", "--data-dir", str(tmp_path)], catch_exceptions=False
        )
        assert result.exit_code == 1
        assert "UNMAPPED_CATEGORY" in flat(result.output)


class TestSettingsChangeTheAnswer:
    def test_the_unit_changes_the_reported_counts(self, run):
        by_ticket = run("report", "--unit", "TICKET")
        by_case = run("report", "--unit", "CASE")
        assert by_ticket != by_case

    def test_the_mapping_version_changes_a_closed_month(self, run):
        v1 = run("explain", "delivery_timing", "--mapping-version", "v1")
        v2 = run("explain", "delivery_timing", "--mapping-version", "v2")
        assert "count 6" in v1 and "count 12" in v2

    def test_a_split_version_has_no_delivery_timing_at_all(self, run):
        out = run("explain", "delivery_timing", "--mapping-version", "v3_split")
        assert "no category 'delivery_timing'" in out
        assert "carrier_delay" in out

    def test_the_grain_changes_the_buckets(self, run):
        assert "2026-W" in run("report", "--grain", "WEEK")

    def test_a_looser_alpha_can_produce_a_direction(self, run):
        strict = run("trend", "--alpha", "0.05")
        loose = run("trend", "--alpha", "0.5")
        assert strict != loose
