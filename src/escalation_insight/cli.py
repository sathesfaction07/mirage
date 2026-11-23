"""Commands. Each one publishes the reasoning behind its numbers, not just the numbers."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import click

from . import render
from .aggregate import Analysis, run
from .config import Settings
from .gate import check as run_check
from .models import Grain, Unit


def _settings(
    data_dir: str, mapping_version: str, unit: str, grain: str, alpha: float,
    include_newest: bool, as_of: str | None,
) -> Settings:
    return Settings(
        data_dir=Path(data_dir),
        mapping_version=mapping_version,
        unit=Unit(unit),
        grain=Grain(grain),
        alpha=alpha,
        complete_only=not include_newest,
        as_of=dt.date.fromisoformat(as_of) if as_of else None,
    )


def _common(function):
    function = click.option("--data-dir", default="data", show_default=True)(function)
    function = click.option("--mapping-version", default="v2", show_default=True)(function)
    function = click.option(
        "--unit", type=click.Choice([u.value for u in Unit]), default=Unit.TICKET.value,
        show_default=True,
    )(function)
    function = click.option(
        "--grain", type=click.Choice([g.value for g in Grain]), default=Grain.MONTH.value,
        show_default=True,
    )(function)
    function = click.option("--alpha", type=float, default=0.05, show_default=True)(function)
    function = click.option(
        "--include-newest/--exclude-newest", default=False, show_default=True,
        help="Include the unfinished newest bucket. Excluding it makes the report silent "
             "about the current period.",
    )(function)
    function = click.option(
        "--as-of", default=None, help="Override the cut-off date (YYYY-MM-DD)."
    )(function)
    return function


def _load(**kwargs) -> Analysis:
    return run(_settings(**kwargs))


@click.group()
@click.version_option()
def main() -> None:
    """Analyses escalation tickets, and reports which of its own trends are choices."""


@main.command()
@_common
def report(**kwargs) -> None:
    """Counts, exposures and the direction under the active settings."""
    render.show_report(_load(**kwargs))


@main.command()
@_common
def trend(**kwargs) -> None:
    """The same question under every combination of the four choices."""
    render.show_trend(_load(**kwargs))


@main.command()
@_common
def evidence(**kwargs) -> None:
    """Why a ratio is not a finding, and what these counts could have detected."""
    render.show_evidence(_load(**kwargs))


@main.command()
@_common
def mapping(**kwargs) -> None:
    """Mapping versions, their merges, and what a revision does to closed months."""
    render.show_mapping(_load(**kwargs))


@main.command()
@_common
def unit(**kwargs) -> None:
    """Tickets versus cases, and where deduplication takes its rows from."""
    render.show_units(_load(**kwargs))


@main.command()
@_common
def censoring(**kwargs) -> None:
    """The newest bucket's exposure, its hidden volume, and the resulting dilemma."""
    render.show_censoring(_load(**kwargs))


@main.command()
@_common
def gaps(**kwargs) -> None:
    """Questions asked per topic, and the four causes this data cannot separate."""
    render.show_gaps(_load(**kwargs))


@main.command()
@_common
def doctor(**kwargs) -> None:
    """What was chosen, what was measured, and what is never measured at all."""
    render.show_doctor(_load(**kwargs))


@main.command()
@click.argument("category")
@_common
def explain(category: str, **kwargs) -> None:
    """Everything known about one category, with its provenance."""
    render.show_explain(_load(**kwargs), category)


@main.command()
@_common
def check(**kwargs) -> None:
    """Fail only on defects the producer of the export can fix. Report the rest."""
    verdict = run_check(_load(**kwargs))
    render.show_check(verdict)
    sys.exit(verdict.exit_code)


if __name__ == "__main__":
    main()
