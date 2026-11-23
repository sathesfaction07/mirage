"""The arithmetic. If any of this is wrong, every claim the project makes is wrong."""

from __future__ import annotations

import math

import pytest

from escalation_insight import evidence
from escalation_insight.models import Direction


class TestTheBinomialItself:
    """Checked against values computable by hand, not against another implementation."""

    def test_pmf_matches_the_closed_form(self):
        assert evidence.pmf(0, 4, 0.5) == pytest.approx(1 / 16)
        assert evidence.pmf(2, 4, 0.5) == pytest.approx(6 / 16)
        assert evidence.pmf(10, 10, 0.5) == pytest.approx(1 / 1024)

    def test_pmf_is_zero_outside_the_range(self):
        assert evidence.pmf(-1, 4, 0.5) == 0.0
        assert evidence.pmf(5, 4, 0.5) == 0.0

    def test_pmf_sums_to_one(self):
        for n in (1, 5, 20):
            for p in (0.1, 0.4746, 0.5, 0.9):
                assert sum(evidence.pmf(k, n, p) for k in range(n + 1)) == pytest.approx(1.0)

    def test_the_most_likely_outcome_has_p_value_one(self):
        assert evidence.two_sided_p(5, 10, 0.5) == pytest.approx(1.0)

    def test_both_extremes_of_a_fair_coin(self):
        """Ten heads out of ten: 2/1024, counting both tails as equally unlikely."""
        assert evidence.two_sided_p(10, 10, 0.5) == pytest.approx(2 / 1024)
        assert evidence.two_sided_p(0, 10, 0.5) == pytest.approx(2 / 1024)

    def test_nothing_observed_refutes_nothing(self):
        assert evidence.two_sided_p(0, 0, 0.5) == 1.0

    def test_it_never_exceeds_one(self):
        for n in range(1, 25):
            for k in range(n + 1):
                assert 0.0 <= evidence.two_sided_p(k, n, 0.4746) <= 1.0

    def test_it_is_exact_and_needs_no_large_n(self):
        """The whole reason for `math.comb`: n is small, so approximations are unavailable."""
        assert evidence.two_sided_p(4, 4, 0.5) == pytest.approx(2 * (1 / 16))
        assert math.comb(4, 4) == 1


class TestARatioIsScaleFreeAndItsEvidenceIsNot:
    """The finding the brief's own headline phrase falls to."""

    def test_the_same_multiplier_gives_opposite_verdicts(self):
        demo = evidence.scale_demo()
        assert demo.small.count_ratio == demo.large.count_ratio == 3.0
        assert demo.small.direction is Direction.UNKNOWN
        assert demo.large.direction is Direction.UP
        assert demo.verdicts_differ is True

    def test_the_small_one_is_not_even_unusual(self):
        demo = evidence.scale_demo()
        assert demo.small.p_value > 0.5, "1 -> 3 happens more than half the time"
        assert demo.large.p_value < 1e-8

    def test_the_summary_says_the_ratio_cannot_tell_them_apart(self):
        text = evidence.scale_demo().summary()
        assert "compatible with having found nothing at all" in text
        assert "divides out the very thing" in text

    def test_a_zero_denominator_has_no_ratio_but_can_still_have_evidence(self):
        strong = evidence.claim(
            "new", count_before=0, count_after=5, days_before=31, days_after=28, alpha=0.05
        )
        assert strong.count_ratio is None and strong.rate_ratio is None
        assert strong.direction is Direction.UP
        assert "no RATIO to report" in strong.headline()
        assert "the RATE did change" in strong.headline()

        weak = evidence.claim(
            "new", count_before=0, count_after=2, days_before=31, days_after=28, alpha=0.05
        )
        assert weak.direction is Direction.UNKNOWN
        assert "not even the rate is established" in weak.headline()

    def test_the_note_names_the_mechanism(self):
        assert "scale-free" in evidence.why_a_ratio_is_not_a_finding()
        assert "UNKNOWN" in evidence.why_a_ratio_is_not_a_finding()


class TestTheCalendarIsNotNeutral:
    def test_february_earns_less_than_half_of_a_pair(self):
        case = evidence.calendar_bias(n=10, count_after=5)
        assert case.adjusted.days_before == 31
        assert case.adjusted.days_after == 28
        assert case.naive.days_before == case.naive.days_after

    def test_the_count_ratio_and_the_rate_ratio_differ(self):
        claim = evidence.claim(
            "packaging", count_before=1, count_after=3, days_before=31, days_after=28,
            alpha=0.05,
        )
        assert claim.count_ratio == pytest.approx(3.0)
        assert claim.rate_ratio == pytest.approx(3.321, abs=0.001)
        assert claim.rate_ratio > claim.count_ratio, "the shorter month raises the rate"

    def test_ignoring_month_length_can_flip_the_verdict(self):
        flip = evidence.smallest_flip()
        assert flip is not None
        assert flip.verdict_flips is True
        assert flip.naive.direction is Direction.UNKNOWN
        assert flip.adjusted.direction is Direction.UP
        assert "The verdict FLIPS" in flip.summary()

    def test_the_flip_search_ignores_zero_denominators(self):
        """A flip resting on a missing ratio is true and uninteresting."""
        flip = evidence.smallest_flip()
        assert flip.n - flip.count_after > 0
        assert flip.count_after > 0

    def test_when_the_verdict_holds_it_still_says_the_p_value_moved(self):
        case = evidence.calendar_bias(n=10, count_after=5)
        assert case.verdict_flips is False
        assert "Same verdict here" in case.summary()

    def test_no_flip_below_a_tiny_limit_is_a_real_answer(self):
        assert evidence.smallest_flip(limit=3) is None


class TestWhetherTheStudyCouldHaveFoundAnything:
    def test_four_escalations_can_never_reach_significance(self):
        floor = evidence.power_floor(total=4, days_before=31, days_after=28)
        assert floor.can_detect_anything is False
        assert floor.detectable == ()
        assert "NO split would have reached" in floor.summary()
        assert "says nothing about the world" in floor.summary()

    def test_twenty_two_can_only_detect_extremes(self):
        floor = evidence.power_floor(total=22, days_before=31, days_after=28)
        assert floor.can_detect_anything is True
        assert 11 not in floor.detectable, "the middle was never going to be a finding"
        assert 0 in floor.detectable and 22 in floor.detectable
        assert "was going to be reported as UNKNOWN before the data was looked at" in (
            floor.summary()
        )

    def test_a_looser_alpha_detects_more(self):
        strict = evidence.power_floor(total=8, days_before=31, days_after=28, alpha=0.01)
        loose = evidence.power_floor(total=8, days_before=31, days_after=28, alpha=0.20)
        assert len(loose.detectable) > len(strict.detectable)

    def test_zero_escalations_detect_nothing(self):
        assert evidence.power_floor(total=0, days_before=31, days_after=28).detectable == ()


class TestRefusals:
    def test_a_period_with_no_elapsed_time_is_not_comparable(self):
        with pytest.raises(ValueError, match="no elapsed time"):
            evidence.claim("x", count_before=1, count_after=1, days_before=0, days_after=5,
                           alpha=0.05)
        with pytest.raises(ValueError, match="no elapsed time"):
            evidence.claim("x", count_before=1, count_after=1, days_before=5, days_after=0,
                           alpha=0.05)
