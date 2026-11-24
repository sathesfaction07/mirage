# Mirage

"This escalation category tripled in three months" sounds like a finding. It might be one. Or
more people might have started reporting, a category might have been renamed, or late tickets
might still be arriving for last month. Mirage analyses escalation tickets for
trends, and for every trend it reports, checks whether it could be an artifact of how the data
was collected.

```bash
./setup.sh
.venv/bin/mirage report
.venv/bin/mirage check     # exits 1 on this corpus, deliberately
```

---

## The claim this refutes

The requirements note this project started from gives its accuracy concern as *"correct pattern identification and categorization across
messy data"*, and its verdict is: **add an LLM normalization pass — send inconsistently
categorized entries for canonical categorization, then run the pandas analysis on clean
data.** The aspiration, in the project's own words, is to find *"this pattern is increasing 3x
over 3 months and affects 4 teams."*

There is no clean data for a trend to be run on. A count over time is not an observation of
the world — it is the product of five things:

```
   escalations that HAPPENED
 x how many got reported
 x how the reporter categorised them
 x when the system heard about it
 x whether the category existed for the whole window
```

Only the first is what anybody wants to know, and **a change in any of the other four moves
the line in exactly the same way.** The normalization pass does not remove that problem. It
*is* the third term, and it is the one that gets revised by a human on a Tuesday and applied
backwards over months that were already published.

## What a survey of the sibling projects found — it narrowed the pitch

Before writing anything, the sibling projects were searched for the mechanisms this project would
need. Two of them already existed, and both are what the project brief recommends:

| Already built | Where | So the angle here is |
|:--|:--|:--|
| Raw label → canonical category, **per marketplace**, with conflict detection and coverage gaps | **Vintage** `labels.py` | not building a `LabelMap` — asking what a mapping does to a **count over time** |
| Bucketed `Series`, rolling baselines, missing periods, robust stats (argument: **breakdown point**) | **Plimsoll** `series.py` / `stats.py` | it starts from an `Observation` that already knows its period. Everything here is the step **before** that |
| Categorization confidence and calibration | Plumbline | not classification quality |
| The deduplication ceiling | Kinship | dedup's effect on a trend's **direction** |
| Identity decides a static count | Denominator | the **unit** decides a direction |
| matplotlib charts | Plumbline, Meridian | **charts dropped** — a repeat that changes no conclusion |

Verified genuinely absent from every sibling project: `slope`/regression **0 files**, `binomial` /
`p_value` / `math.comb` **0**, confidence intervals **0**, censoring **0**, partial-period
**0**, Simpson's paradox **0**, ratio-with-evidence **0**.

So the new ground is **what a count means once time is involved**, and the machinery for it —
exact small-sample evidence — did not exist here.

No model, no network. The accuracy problem is arithmetic and the calendar.

---

## Findings

### 1. "3x" is scale-free. Its evidence is not.

Two increases, both exactly 3x, over periods of equal length:

| | p-value | verdict |
|:--|--:|:--|
| 1 → 3 | **0.62** | `UNKNOWN` |
| 40 → 120 | **1.8e-10** | `UP` |

Same ratio, same sentence in a status update, evidence differing by nine orders of magnitude.
**A ratio divides out the count, which is the only thing carrying the evidence** — so the
phrase in the project brief's own aspiration survives being computed from numbers that mean nothing.

The test is exact, via `math.comb`: under a constant rate, each escalation lands in the later
period with probability equal to that period's share of the exposure, so the later count is
Binomial(n, p) and "is this split surprising" has a closed-form answer. It has to be exact,
because the entire difficulty is that n is small.

### 2. The calendar manufactures a trend, and it is biased toward good news

January has 31 days and February 28. Under a constant rate February earns **47.5%** of the
pair, not 50% — so a perfectly ordinary February shortfall reads as improvement.

Testing against an even split rather than the true exposure changes verdicts. The smallest
case where it does:

```
1 -> 7 over 31 then 28 days
  testing against an even 50/50 split : p = 0.0703 -> UNKNOWN
  testing against the real exposures  : p = 0.0312 -> UP
```

And the bias is **asymmetric**: ignoring month length makes a decline look more real and an
increase look less real. A monthly escalation report that never adjusts is systematically
tilted toward reporting that things are getting better.

The corpus's own "3x" moves too: packaging is **3.0x by count and 3.32x by rate**.

### 3. Merging two labels can reverse the trend

Two raw labels that mean one thing — `shipping delay` and the UK-spelled `late delivery`:

| mapping | Jan | Feb | direction |
|:--|--:|--:|:--|
| `v1` (never saw the UK spelling) | 10 | **6** | falls |
| `v2` (folds them together) | 10 | **12** | rises |

**Identical tickets. Opposite sign.** Nothing in the escalations chooses between the two
readings — it is a decision about whether two phrasings are one problem.

And the sting: at n=22 the "increase" is p=0.53. **The merge flips the sign of something that
was never a finding in the first place.**

### 4. A revised mapping is a retroactive edit

`v1 -> v2` takes unmapped rows from 7 to 1 and changes a **closed** month:

```
delivery_timing 2026-02: 6 -> 12
```

February was over. It had been reported. A trend published last month is not comparable with
the same trend published today, **and neither report says which mapping produced it.**

`v2 -> v3_split` is worse in a different way: it splits `delivery_timing` into
`carrier_delay` and `promise_missed`, so the category **stops existing**. Its trend line does
not go flat or go down — the row vanishes from the report. Eight of `delivery_timing`'s 24
readings cannot be run at all, and the tool says so rather than quietly averaging the 16 that
can.

### 5. The unit changes the direction, and deduplication is not neutral

February holds 9 return tickets across 4 cases, because one case was reopened five times:

| unit | Jan | Feb | direction |
|:--|--:|--:|:--|
| `TICKET` | 6 | **9** | up |
| `CASE` | 6 | **4** | down |

Both counts are correct and they disagree about whether things got worse. But the sharper
result is *where* the collapse takes its rows from:

```
removed  2026-01=0   2026-02=5   2026-03=0
```

**Deduplication subtracts exclusively from the month containing the case that would not
close.** Reopens cluster on hard problems, so collapsing to cases strips the most from the
worst period — and the deduplicated series therefore understates the very thing an escalation
review exists to find. `C-600` is 6 tickets and 5 reopens; under `CASE` it is a 1,
indistinguishable from a case answered once and closed.

Neither unit is right. The one everybody means — **one distinct underlying problem** — is not
derivable from any export like this, because two separate cases can be the same problem and
nothing records that they are. It is absent from the enum because implementing it would mean
inventing it.

### 6. The newest bucket is incomplete, and it is the only one anyone reads

The report ran on 12 March. Two things hit that bucket at once:

- **partial period** — 12 of 31 days have happened
- **recording lag** — escalations opened on the 11th were recorded on the 19th and 20th, so
  they are real, in the past, and absent from an export taken on time

March shows 2 visible escalations for `delivery_timing` with 1 more already in existence:
**the export understates that month-to-date by 33%** — and `returns`, at 1 visible and 1 late,
by **50%**.

> Drop the bucket and the report is silent about the only month anybody is asking about. Keep
> it and the report shows a decline made of the calendar and the lag. There is no third
> option, and choosing is not a statistical act.

`report` therefore says out loud that the newest bucket is excluded from every direction it
prints, rather than letting a reader assume the numbers describe now.

### 7. Some comparisons could never have found anything

Before looking at the data, ask whether the study was capable of a finding:

```
packaging: with 4 escalations across the two periods, NO split would have reached
           alpha 0.05 -- not even all of them landing in one period. This comparison
           could not have produced a finding, so finding none says nothing about the world.

returns:   with 16, a change would have been called only if the later period held one of
           [0,1,2,3,12,13,14,15,16]. Anything else was going to be reported as UNKNOWN
           before the data was looked at.
```

And the bucket width decides whether the question is askable at all: `misc` occupies one
month and two ISO weeks, so **12 of its 24 readings can form a comparison and 12 cannot.**

### 8. An "SOP gap" is not observable

A question count is the same number whichever of four things produced it:

| cause | what adding a section does |
|:--|:--|
| `NOT_DOCUMENTED` | **fixes it** — the only one |
| `DOCUMENTED_NOT_FINDABLE` | **makes it worse** — a longer document is harder to search |
| `DOCUMENTED_NOT_TRUSTED` | nothing |
| `ASKING_IS_CHEAPER` | nothing |

An export records that somebody asked. It does not record whether they looked first, what they
searched for, or whether they found the section and disbelieved it.

On this corpus the top topic by both measures is `returns` — **41 questions on a topic the SOP
documents at section 4.2.** So the one cause a new section would fix is precisely the one
already ruled out for the biggest number in the report, and the recommendation the project brief asks
for would make the most likely remaining cause worse.

Being undocumented rules out *nothing*, either: it does not follow that the absence is why
anybody asked.

And **the ranking flips depending on whether anybody divided:**

```
by questions asked        : returns, delivery_timing, packaging
by questions PER escalation: returns, packaging, delivery_timing
```

`packaging` has 3 questions — invisible by volume, second-worst by rate. "The biggest pain
point" is decided by a choice that reports rarely state.

---

## Nine defects of my own, all found by reading output

**1. `Direction.FLAT` was unreachable by algebra, and removing it was the finding.** A test
asserted that an exactly-constant rate reports `FLAT`. It reported `UNKNOWN`. The reason is
not a bug: `rate_ratio == 1.0` holds exactly when the observed count equals the **modal**
outcome under the constant-rate null, and the modal outcome's two-sided p-value is always
**1.0** — so `p <= alpha` cannot hold for any alpha below 1. `FLAT` was not merely dead code;
**a null-hypothesis test can never conclude that nothing changed.** Failing to be surprised is
not evidence of stability. The enum now has three values and its docstring explains the
absence of the fourth.

**2. `UNKNOWN` conflated a test that ran with a test that could not run.** A category with one
bucket was recorded as `UNKNOWN`, the same value as a category tested under every reading and
never convincing. `no_comparison_possible` is now separate — and chasing it produced finding 7,
that the grain decides whether the question can be asked.

**3. The headline contradicted itself on a zero denominator.** `headline()` said "a category
that did not exist before cannot have increased" while `direction` returned `UP` for the same
claim. Both had a point: there is no **ratio**, and the **rate** genuinely did change. It now
says exactly that — *"Infinitely more" and "one more than none" are the same fact.*

**4. Two censoring entries rendered identically.** `Censoring` never carried its category, so
`delivery_timing` and `returns` both printed as `2026-03` with different numbers and no way to
tell which was which.

**5. Readings were skipped in silence.** When a category does not exist under a mapping
version, those readings were dropped without comment — hiding that a revision can **delete** a
category rather than change it. Now reported.

**6. The headline conflated two failures.** "Readings disagree" and "no reading found
anything" were counted together, so a category nobody could say anything about looked like a
category people disagreed about.

**7. A flip search that rested on a fallback.** `smallest_flip` returned `0 -> 5`, where the
verdict came from the zero-denominator branch rather than from evidence — technically a flip
and useless as an example. Restricted to real ratios, it returns `1 -> 7`.

**8. One fact, two phrasings.** `report` said "fewer than two comparable buckets" and
`explain` said "Not enough comparable buckets" about the identical situation.

**9. Three functions nothing called.** `claim_for`, `from_env` and `show_verdict_summary`,
written speculatively and removed rather than tested around.

---

## What `check` gates on

One question: **can the producer of the export fix it?**

```
FAILS (5, fixable at source)          REPORTS (12, not fixable there)
  UNMAPPED_CATEGORY                     an unfinished newest bucket
  NO_EVENT_TIME                         a direction that depends on the settings
  RECORDED_BEFORE_EVENT                 a category too small to test at all
  DUPLICATE_ID                          a category a revision would delete
  ORPHAN_REOPEN                         a revision that rewrites closed months
                                        an uneven deduplication
                                        two defensible rankings that disagree
                                        a question count whose cause is unknowable
```

Every failure names its fix. Verified both ways: a clean two-row export **passes** — and still
reports that its question counts cannot establish a cause — while one wrong label alone
**fails**.

Nobody can fix February being short, so failing a build over it would only teach people to
switch the check off.

---

## Commands

| | |
|:--|:--|
| `report` | counts beside their exposures, and the direction under the active settings |
| `trend` | the same question under all 24 readings, with the set of answers |
| `evidence` | the 3x demonstration, the calendar flip, and what these counts could detect |
| `mapping` | versions, their merges, and what a revision does to closed months |
| `unit` | tickets versus cases, and where deduplication takes its rows from |
| `censoring` | the newest bucket's exposure, hidden volume, and the resulting dilemma |
| `gaps` | questions per topic, and the four causes this data cannot separate |
| `doctor` | chosen / measured / never measured / judgements, in four sections |
| `explain <category>` | everything about one category, with provenance |
| `check` | fail on producer-fixable defects only |

## Honest about limits

- **The denominator does not exist.** How many escalations *happened* is unknowable; every
  number here counts what was recorded.
- **A reporting-rate change is indistinguishable from a volume change.** Nothing here can
  separate them, and that is stated in `doctor` rather than worked around.
- **Every rate assumes escalations arrive uniformly inside a bucket.** They do not, and
  nothing here can check it.
- **`alpha = 0.05` is a convention** borrowed from elsewhere with no basis in escalation
  management. Exposed as a flag, printed by `doctor` as a convention.
- **Counting a case at its earliest ticket is a judgement.** Counting it at the latest is
  equally defensible and flatters the past.
- **The recording lag is declared in the corpus, not detected.** A real analysis does not know
  what it has not yet been told — which is the whole problem.
- **The question counts are fixture data.** "41 questions" is a fact about a file I wrote.
- **The corpus is mine and small.** Every figure above is a fact about 52 hand-authored rows,
  not an estimate for anyone.
- **Nothing here fixes anything.** Freeze your mapping before you publish a trend, say which
  version produced each report, and accept that the current month is always wrong.

## Tests

**153 tests, 100% coverage**, under 2s.

```
tests/unit/test_evidence.py              24   the binomial, checked against hand-computed values
tests/unit/test_mapping_buckets_units.py 44   merging, exposure, grain, the unit, censoring
tests/unit/test_trend_gaps_gate.py       36   direction, the FLAT proof, gaps, the gate
tests/integration/test_cli.py            49   every command through the real entry point
```

The console-width fixture is **function-scoped and autouse**, and every fixture that captures
output must be function-scoped too — a higher-scoped one is instantiated first, captures
80-column output, and breaks assertions on whole sentences. That cost an afternoon in a
previous project.

## Layout

```
src/escalation_insight/
  models.py      Ticket, Exposure, Bucket, Series, RatioClaim, Direction (three values), GapCause
  evidence.py    exact binomial via math.comb; scale demo; calendar bias; power floor
  mapping.py     versioned label -> category; merges; what a revision does to closed months
  buckets.py     event -> bucket; exposure; censoring; grain
  units.py       ticket vs case; the dedup asymmetry; broken lineage
  trend.py       direction; sensitivity across all four choices
  gaps.py        question counts; the four causes; the ranking flip
  aggregate.py   run + payload
  render.py      output where no number appears without its qualifier
  gate.py        producer-fixable only
  cli.py         ten commands
  config.py      settings, and CHOSEN_NOT_MEASURED
data/generate.py hand-authored corpus; owns its directory and prunes what it did not write
```
