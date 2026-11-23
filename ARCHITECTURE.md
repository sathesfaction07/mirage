# Architecture

## The shape of the problem

The brief asks for pattern identification over messy escalation data and prescribes an LLM
normalization pre-pass to clean it first. The module layout is the argument that there is no
"first": normalization is a term in the analysis, not a step before it.

```
  tickets.csv ──> 52 rows, free text, two timestamps each
                        │
                        ▼
                  mapping.py        raw label -> canonical category, UNDER A VERSION
                        │           merging can reverse a trend; revising rewrites the past
                        ▼
                  units.py          what one counted thing IS: ticket or case
                        │           collapsing is not even across time
                        ▼
                  buckets.py        event -> period, with EXPOSURE and CENSORING
                        │           months are unequal; the newest one is unfinished
                        ▼
                 evidence.py        exact binomial: is this split surprising at all?
                        │
                        ▼
                  trend.py ──> a direction, plus the same question under all 24 readings
                        │
                        ▼
        aggregate.py ──> render.py / gate.py / gaps.py
```

Each stage is a decision that changes the number, and none of them is recoverable downstream.

## Where this sits next to what already exists

Two projects here already own most of what the brief recommends, and both are credited in the
module docstrings rather than quietly re-implemented.

**Vintage** `labels.py` maps a raw label to a canonical status *per marketplace*, finds
conflicts between marketplaces, and reports coverage gaps. That is the normalization pass,
already built, with the regional dimension the brief names as its worst input. `mapping.py`
does not compete with it; it asks the question nobody asks it — *what does a mapping do to a
count over time?*

**Plimsoll** `series.py` / `stats.py` owns bucketed series, rolling baselines, missing
periods, and robust estimators, with breakdown point as its argument. It starts from an
`Observation` that already knows its period. `buckets.py` is entirely about the step before
that: **how a ticket becomes an observation in a period at all.** By the time a well-formed
series exists, the interesting damage is done.

## Why `Direction` has three members and not four

`FLAT` was written, and then deleted, because it is unreachable by algebra:

- `rate_ratio == 1.0` holds exactly when the observed count equals the **modal** outcome under
  the constant-rate null.
- The modal outcome's two-sided p-value, by the method of small p-values, is **1.0**.
- So `p_value <= alpha` cannot hold for any `alpha < 1`, and `Settings` forbids `alpha >= 1`.

The deletion is the finding, not a workaround. **A null-hypothesis test can fail to be
surprised; it can never establish that nothing happened.** `UNKNOWN` is that answer, and there
is no route from this kind of evidence to "the rate is the same". A test pins the algebra.

## Two states that look identical and are not

| | means | how it arises |
|:--|:--|:--|
| `UNKNOWN` | a comparison ran and was unconvincing | enough buckets, not enough volume |
| `no_comparison_possible` | no comparison could be formed | fewer than two usable buckets |

Conflating them was a defect. Separating them produced a finding: `misc` occupies one month and
two ISO weeks, so **12 of its 24 readings can be compared and 12 cannot** — the bucket width
decides whether the question can be asked, before any evidence is weighed.

## Exposure is a denominator, and it is doing real work

`Exposure` folds two independent reasons a bucket can be short:

- **calendar** — February is 28 days to January's 31, so a constant rate yields 90.3% of
  January's count, free, in the direction of good news.
- **cut-off** — the newest bucket is only as wide as the part of it that has happened.

`evidence.claim` therefore tests against `days_after / (days_before + days_after)` rather than
0.5. The correction is asymmetric: ignoring it makes declines look real and increases look
weak, so an unadjusted monthly report is tilted toward reporting improvement.

Everything downstream of a rate inherits one assumption nothing here can check — that
escalations arrive uniformly inside a bucket. `doctor` prints it under *never measured*.

## What the settings decide

| setting | changes | evidence on this corpus |
|:--|:--|:--|
| `mapping_version` | which labels are one category | `v1` falls 10→6, `v2` rises 10→12 |
| `unit` | what one thing is | tickets 6→9 up, cases 6→4 down |
| `grain` | bucket width | decides whether `misc` is comparable at all |
| `complete_only` | is the unfinished bucket in | changes which two buckets anchor the claim |
| `alpha` | how much evidence is enough | a convention, from nowhere in particular |

`doctor` prints all five under **chosen, not measured**, beside what was measured and what is
never measured, because the three are indistinguishable in a finished report.

## The gate's dividing line

**Can the producer of the export fix it?** Five faults can, and each names its fix. Twelve
findings cannot, and are printed without failing.

Nobody can fix February being short. A gate that failed on ambiguity would fail on every real
export forever and be switched off, taking the five real defects with it.

## The corpus

`data/generate.py` writes 52 hand-authored rows, each existing to produce a named finding, so a
reader can check every number by eye. Ten synonym rows in January and six-plus-six in February
make the merge reverse a sign; one case carries five reopens; two March rows are recorded after
the cut-off; and the five producer-fixable defects live in their own `misc` category so that no
defect pollutes a category a finding depends on — which was a correction, since the first
version put them in `returns` and broke the unit demonstration.

The generator **owns** `data/` and prunes anything it did not write.

## What is deliberately absent

- **No model and no network.** The findings are arithmetic and the calendar.
- **No charts.** Plumbline and Meridian already have matplotlib output, and a chart
  changes none of the conclusions — it mostly makes an unqualified number easier to quote.
- **No pandas.** The grouping here is a `Counter`; pandas would add a dependency and hide the
  bucketing decisions this project exists to expose.
- **No third unit.** "One distinct underlying problem" is what everybody means and no export
  can produce it. Implementing it would mean inventing it.
- **No recommendation generator.** The brief asks for one. Section 8 of the README is why the
  inference it would rest on does not go through.
