"""Terminal output. Every number is printed next to the words that qualify it.

The rule this module follows: a count never appears without its exposure, a ratio never
appears without its p-value, and a direction never appears without the number of readings
that agreed. Splitting them across columns would let a reader take the first and leave the
rest, which is the failure the whole project is about.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from . import evidence
from . import trend as trend_mod
from . import units as units_mod
from .aggregate import Analysis
from .config import CHOSEN_NOT_MEASURED
from .gate import Verdict, what_is_not_gated
from .mapping import why_a_mapping_is_not_cleaning
from .models import GAP_CAUSE_NOTES, Direction
from .units import why_neither_unit_is_right

console = Console()


def _series_table(analysis: Analysis) -> Table:
    table = Table(title="Counts under the ACTIVE settings", title_justify="left")
    table.add_column("category")
    table.add_column("bucket")
    table.add_column("count", justify="right")
    table.add_column("days", justify="right")
    table.add_column("per day", justify="right")
    table.add_column("recorded late", justify="right")
    for series in analysis.active:
        for bucket in series.buckets:
            rate = bucket.rate_per_nominal_day
            table.add_row(
                series.category,
                bucket.label + ("" if bucket.exposure.is_complete else " (partial)"),
                str(bucket.count),
                f"{bucket.exposure.elapsed_days}/{bucket.exposure.nominal_days}",
                "n/a" if rate is None else f"{rate:.3f}",
                str(bucket.late_arrivals) if bucket.late_arrivals else "",
            )
    return table


def show_report(analysis: Analysis) -> None:
    console.print(f"[bold]{analysis.headline()}[/bold]\n")
    console.print(_series_table(analysis))
    console.print()
    if analysis.settings.complete_only and analysis.censored:
        console.print(
            f"[yellow]The newest bucket is EXCLUDED from every direction below, so nothing "
            f"here describes {analysis.censored[0].label}. Including it would compare a "
            "part-month against a whole one.[/yellow]"
        )
    console.print("[bold]The direction, under the active settings[/bold]")
    for series in analysis.active:
        claim = trend_mod.trend(
            series, alpha=analysis.settings.alpha,
            complete_only=analysis.settings.complete_only,
        )
        console.print(f"  {claim.headline()}" if claim else
                      f"  {series.category}: fewer than two comparable buckets, so no claim.")
    console.print()
    console.print(f"[dim]{trend_mod.why_a_trend_is_not_an_observation()}[/dim]")


def show_trend(analysis: Analysis) -> None:
    console.print("[bold]The same question under every reading of the data[/bold]\n")
    for found in analysis.sensitivities:
        console.print(f"[bold]{found.category}[/bold]")
        table = Table(show_header=True)
        table.add_column("mapping")
        table.add_column("unit")
        table.add_column("grain")
        table.add_column("newest bucket")
        table.add_column("counts")
        table.add_column("p", justify="right")
        table.add_column("direction")
        for choice in found.choices:
            colour = {
                Direction.UP: "red", Direction.DOWN: "green",
                Direction.UNKNOWN: "dim",
            }[choice.direction]
            table.add_row(
                choice.mapping_version, choice.unit, choice.grain,
                "excluded" if choice.complete_only else "INCLUDED",
                "n/a" if choice.counts is None else f"{choice.counts[0]} -> {choice.counts[1]}",
                "n/a" if choice.p_value is None else f"{choice.p_value:.3f}",
                f"[{colour}]{choice.direction.value}[/{colour}]",
            )
        console.print(table)
        console.print(f"  {found.summary()}\n")


def show_evidence(analysis: Analysis) -> None:
    console.print("[bold]A ratio is scale-free. Its evidence is not.[/bold]\n")
    console.print(evidence.scale_demo().summary())
    console.print()
    console.print("[bold]The calendar alone can decide the verdict[/bold]")
    flip = evidence.smallest_flip(alpha=analysis.settings.alpha)
    console.print("  " + (flip.summary().replace("\n", "\n  ") if flip else
                          "  no verdict flip found below the search limit"))
    console.print()
    console.print("[bold]Could each comparison have found anything at all?[/bold]")
    for series in analysis.active:
        floor = evidence.power_floor(
            total=series.total, days_before=31, days_after=28, alpha=analysis.settings.alpha
        )
        console.print(f"  {series.category}: {floor.summary()}")
    console.print()
    console.print(f"[dim]{evidence.why_a_ratio_is_not_a_finding()}[/dim]")


def show_mapping(analysis: Analysis) -> None:
    console.print("[bold]Mapping versions, and what changing them does[/bold]\n")
    table = Table()
    table.add_column("version")
    table.add_column("categories", justify="right")
    table.add_column("merged categories")
    table.add_column("description")
    for name in analysis.mappings.names:
        mapping = analysis.mappings.get(name)
        merges = ", ".join(
            f"{canon}<-{len(labels)} labels" for canon, labels in mapping.merges.items()
        )
        table.add_row(name, str(len(mapping.canonical_names)), merges or "none",
                      mapping.description)
    console.print(table)
    console.print()
    for effect in analysis.version_effects:
        console.print(effect.summary())
        console.print()
    console.print(f"[dim]{why_a_mapping_is_not_cleaning()}[/dim]")


def show_units(analysis: Analysis) -> None:
    console.print("[bold]What one counted thing IS[/bold]\n")
    for effect in analysis.unit_effects:
        console.print(effect.summary())
        console.print()
    deepest = units_mod.depths(analysis.tickets)
    if deepest and deepest[0].tickets > 1:
        console.print("[bold]The deepest case in the export[/bold]")
        console.print(f"  {deepest[0].note()}\n")
    orphans = units_mod.lineage_disagreement(analysis.tickets)
    if orphans:
        console.print(
            f"  {len(orphans)} reopen(s) {list(orphans)} point at a ticket absent from the "
            "export, so `case_id` and the reopen chain disagree about what one case is.\n"
        )
    console.print(f"[dim]{why_neither_unit_is_right()}[/dim]")


def show_censoring(analysis: Analysis) -> None:
    console.print("[bold]The newest bucket[/bold]\n")
    if not analysis.censored:
        console.print("  Every bucket is complete, at this cut-off.")
        return
    for censored in analysis.censored:
        console.print(censored.summary())
        console.print()
    console.print("[bold]Exposure of every bucket, whether complete or not[/bold]")
    for series in analysis.active[:1]:
        for bucket in series.buckets:
            console.print(f"  {bucket.exposure.note()}")


def show_gaps(analysis: Analysis) -> None:
    console.print("[bold]Questions asked, and what they do NOT establish[/bold]\n")
    table = Table()
    table.add_column("topic")
    table.add_column("questions", justify="right")
    table.add_column("escalations", justify="right")
    table.add_column("per escalation", justify="right")
    table.add_column("in the SOP")
    table.add_column("causes still live", justify="right")
    for gap in analysis.topic_gaps:
        rate = gap.per_escalation
        table.add_row(
            gap.category, str(gap.questions), str(gap.escalations),
            "n/a" if rate is None else f"{rate:.2f}",
            f"section {gap.section}" if gap.documented else "[red]no[/red]",
            str(len(gap.candidates)),
        )
    console.print(table)
    console.print()
    console.print(analysis.ranking.summary())
    console.print()
    for gap in analysis.topic_gaps:
        console.print(gap.note())
        console.print()
    console.print("[bold]The four candidate causes[/bold]")
    for cause, note in GAP_CAUSE_NOTES.items():
        console.print(f"  {cause.value:26s} {note}")


def show_doctor(analysis: Analysis) -> None:
    console.print("[bold]Chosen, not measured[/bold]")
    console.print(
        "  Each of these was picked by whoever ran this. None is discoverable from the "
        "escalations, and each can change the direction reported.\n"
    )
    table = Table()
    table.add_column("setting")
    table.add_column("value")
    table.add_column("what it decides")
    active = {
        "mapping_version": analysis.settings.mapping_version,
        "unit": analysis.settings.unit.value,
        "grain": analysis.settings.grain.value,
        "complete_only": str(analysis.settings.complete_only),
        "alpha": f"{analysis.settings.alpha:g}",
    }
    for name, note in CHOSEN_NOT_MEASURED.items():
        table.add_row(name, active[name], note)
    console.print(table)
    console.print()

    console.print("[bold]Measured from the export[/bold]")
    measured = Table()
    measured.add_column("quantity")
    measured.add_column("value")
    measured.add_row("tickets read", str(len(analysis.tickets)))
    measured.add_row("categories under the active mapping", str(len(analysis.categories)))
    measured.add_row("producer-fixable defects",
                     str(sum(len(v) for v in analysis.ticket_faults.values())))
    measured.add_row("cut-off date (as_of)", analysis.as_of.isoformat())
    console.print(measured)
    console.print()

    console.print("[bold]Never measured, by anything here[/bold]")
    for line in (
        "how many escalations HAPPENED -- only how many were recorded",
        "whether the reporting rate changed, which looks identical to the volume changing",
        "whether escalations arrive uniformly inside a bucket, which every rate assumes",
        "why anybody asked a question, which is what an SOP gap would require",
        "how many DISTINCT PROBLEMS there were, the unit everybody actually means",
    ):
        console.print(f"  - {line}")
    console.print()
    console.print("[bold]Judgements, not findings[/bold]")
    for line in (
        f"alpha {analysis.settings.alpha:g} is a convention borrowed from elsewhere",
        "counting a case at its EARLIEST ticket rather than its latest",
        "treating a ratio with no evidence as UNKNOWN rather than as a small effect",
    ):
        console.print(f"  - {line}")


def show_check(verdict: Verdict) -> None:
    if verdict.failures:
        console.print("[bold red]Fixable at the source[/bold red]")
        for failure in verdict.failures:
            console.print(f"  [red]x[/red] {failure}")
    else:
        console.print("[bold green]Nothing fixable at source[/bold green]")
    console.print()
    console.print("[bold yellow]Reported and NOT failed on[/bold yellow]")
    for report in verdict.reports:
        console.print(f"  [yellow]-[/yellow] {report}")
    console.print()
    console.print(f"[dim]{what_is_not_gated()}[/dim]")
    console.print()
    if verdict.failures:
        console.print(
            f"[bold red]FAIL on {len(verdict.failures)} producer-fixable defect(s)[/bold red]"
        )
    else:
        console.print("[bold green]PASS[/bold green]")


def show_explain(analysis: Analysis, category: str) -> None:
    series = next((s for s in analysis.active if s.category == category), None)
    if series is None:
        console.print(f"[red]no category {category!r}[/red] under mapping "
                      f"{analysis.settings.mapping_version}. "
                      f"Known: {list(analysis.categories)}")
        return
    console.print(f"[bold]{category}[/bold] ({series.provenance()})\n")
    for bucket in series.buckets:
        console.print(f"  {bucket.exposure.note()}")
        console.print(f"    count {bucket.count}, recorded late {bucket.late_arrivals}")
    console.print()
    claim = trend_mod.trend(series, alpha=analysis.settings.alpha,
                            complete_only=analysis.settings.complete_only)
    console.print(
        f"  {claim.headline()}" if claim
        else f"  {category}: fewer than two comparable buckets, so no claim."
    )
    console.print()
    found = next((s for s in analysis.sensitivities if s.category == category), None)
    if found:
        console.print(f"  {found.summary()}")
    effect = next((u for u in analysis.unit_effects if u.category == category), None)
    if effect:
        console.print()
        console.print(effect.summary())
    gap = next((g for g in analysis.topic_gaps if g.category == category), None)
    if gap:
        console.print()
        console.print(gap.note())
