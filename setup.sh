#!/usr/bin/env bash
# Installs, tests, and re-derives every finding from the arithmetic rather than from a doc.
set -euo pipefail
cd "$(dirname "$0")"

export COLUMNS=200

python3 -m venv .venv
.venv/bin/pip install -q -e ".[dev]"
.venv/bin/ruff check src tests data
.venv/bin/python data/generate.py
.venv/bin/python -m pytest -q --cov=escalation_insight --cov-report=term-missing

echo
echo "═══ 1. A ratio is scale-free. Its evidence is not. ═══"
.venv/bin/python - <<'PY'
from escalation_insight.evidence import scale_demo
demo = scale_demo()
print(demo.summary())
assert demo.small.count_ratio == demo.large.count_ratio == 3.0
assert demo.verdicts_differ
PY

echo
echo "═══ 2. The calendar alone can decide the verdict, and it favours good news ═══"
.venv/bin/python - <<'PY'
from escalation_insight.evidence import claim, smallest_flip
flip = smallest_flip()
print(flip.summary())
assert flip.verdict_flips and flip.count_after > 0 and flip.n - flip.count_after > 0
pack = claim("packaging", count_before=1, count_after=3, days_before=31, days_after=28,
             alpha=0.05)
print(f"\n  and the corpus's own 3x moves: {pack.count_ratio:.3g}x by count, "
      f"{pack.rate_ratio:.3g}x by rate")
assert pack.rate_ratio > pack.count_ratio
PY

echo
echo "═══ 3. Merging two labels reverses the trend. Same tickets. ═══"
.venv/bin/python - <<'PY'
import datetime as dt
from escalation_insight.aggregate import load_tickets
from escalation_insight.buckets import build_series
from escalation_insight.mapping import MappingSet
from escalation_insight.models import Grain, Unit
from pathlib import Path

tickets = load_tickets(Path("data/tickets.csv"))
mappings = MappingSet.load(Path("data/mappings.json"))
for version in ("v1", "v2"):
    series = build_series(
        tickets, category="delivery_timing", mapping=mappings.get(version),
        unit=Unit.TICKET, grain=Grain.MONTH, as_of=dt.date(2026, 3, 12),
    )
    counts = {b.label: b.count for b in series.buckets}
    print(f"  {version}: Jan={counts['2026-01']}  Feb={counts['2026-02']}")
    assert counts["2026-01"] == 10
    assert counts["2026-02"] == (6 if version == "v1" else 12)
print("  10 -> 6 falls; 10 -> 12 rises; the tickets never changed.")
PY

echo
echo "═══ 4. A revised mapping is a retroactive edit ═══"
.venv/bin/python - <<'PY'
from escalation_insight.aggregate import run
from escalation_insight.config import Settings
analysis = run(Settings(data_dir="data"))
for effect in analysis.version_effects:
    print(effect.summary())
    print()
first = analysis.version_effects[0]
assert first.rewritten["delivery_timing"]["2026-02"] == (6, 12)
assert (first.unmapped_before, first.unmapped_after) == (7, 1)
assert "delivery_timing" in analysis.version_effects[1].disappeared
PY

echo "═══ 5. The unit changes the direction, and dedup is not even ═══"
.venv/bin/python - <<'PY'
from escalation_insight.aggregate import run
from escalation_insight.config import Settings
from escalation_insight.units import depths
analysis = run(Settings(data_dir="data"))
effect = next(u for u in analysis.unit_effects if u.category == "returns")
print(effect.summary())
assert dict(effect.by_ticket)["2026-02"] == 9
assert dict(effect.by_case)["2026-02"] == 4
assert dict(effect.removed) == {"2026-01": 0, "2026-02": 5, "2026-03": 0}
assert effect.evenly_spread is False
print()
print("  " + depths(analysis.tickets)[0].note())
PY

echo
echo "═══ 6. The newest bucket is incomplete, and it is the only one anyone reads ═══"
.venv/bin/python - <<'PY'
from escalation_insight.aggregate import run
from escalation_insight.config import Settings
analysis = run(Settings(data_dir="data"))
for censored in analysis.censored:
    print(censored.summary())
    print()
first = next(c for c in analysis.censored if c.category == "delivery_timing")
assert (first.elapsed_days, first.nominal_days) == (12, 31)
assert first.visible == 2 and first.late_arrivals == 1
assert abs(first.understated_by - 1 / 3) < 1e-9
PY

echo "═══ 7. Some comparisons could never have found anything ═══"
.venv/bin/python - <<'PY'
from escalation_insight.aggregate import run
from escalation_insight.config import Settings
from escalation_insight.evidence import power_floor
analysis = run(Settings(data_dir="data"))
for series in analysis.active:
    floor = power_floor(total=series.total, days_before=31, days_after=28)
    print(f"  {series.category}: {floor.summary()}")
assert power_floor(total=4, days_before=31, days_after=28).can_detect_anything is False
found = next(s for s in analysis.sensitivities if s.category == "misc")
assert len(found.comparable_choices) == 12 and len(found.choices) == 24
print(f"\n  and misc: {len(found.comparable_choices)} of {len(found.choices)} readings could "
      "form a comparison at all -- the grain decides whether the question can be ASKED")
PY

echo
echo "═══ 8. An SOP gap is not observable, and the ranking flips ═══"
.venv/bin/python - <<'PY'
from escalation_insight.aggregate import run
from escalation_insight.config import Settings
analysis = run(Settings(data_dir="data"))
print(analysis.ranking.summary())
print()
top = next(g for g in analysis.topic_gaps if g.category == analysis.ranking.by_volume[0])
print(top.note())
assert analysis.ranking.agree is False
assert top.documented is True and top.questions == 41
assert top.adding_a_section_would_help is False
PY

echo
echo "═══ 9. There is no FLAT, and that is provable ═══"
.venv/bin/python - <<'PY'
from escalation_insight.evidence import claim, two_sided_p
from escalation_insight.models import Direction
assert [d.value for d in Direction] == ["UP", "DOWN", "UNKNOWN"]
for total, before_days, after_days in ((300, 30, 30), (22, 31, 28), (59, 31, 28)):
    share = after_days / (before_days + after_days)
    assert abs(two_sided_p(round(total * share), total, share) - 1.0) < 1e-9
exact = claim("c", count_before=300, count_after=300, days_before=30, days_after=30, alpha=0.99)
print(f"  an exactly constant rate: rate_ratio={exact.rate_ratio}, p={exact.p_value}, "
      f"direction={exact.direction.value}")
print("  The modal outcome always has p = 1.0, so `p <= alpha` is unreachable for alpha < 1.")
print("  A null-hypothesis test can fail to be surprised. It can never conclude nothing moved.")
assert exact.direction is Direction.UNKNOWN
PY

echo
echo "═══ 10. The gate fails only on what the producer can fix ═══"
.venv/bin/mirage check || true
echo
echo "setup complete."
