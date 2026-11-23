"""Fixtures.

The console width fixture is function-scoped and autouse, and every fixture that captures
output must ALSO be function-scoped. A higher-scoped fixture is instantiated BEFORE
function-scoped autouse ones, so it would capture 80-column output and assertions on whole
sentences would fail on wrapped text -- a test that depends on the terminal is a test that
passes on one machine.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from escalation_insight.config import Settings
from escalation_insight.models import Ticket

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(autouse=True)
def _wide_console(monkeypatch):
    monkeypatch.setenv("COLUMNS", "300")
    monkeypatch.setenv("TERM", "dumb")
    from escalation_insight import render

    monkeypatch.setattr(render, "console", _console())


def _console():
    from rich.console import Console

    return Console(width=300, force_terminal=False, no_color=True, legacy_windows=False)


@pytest.fixture
def settings() -> Settings:
    return Settings(data_dir=DATA)


@pytest.fixture
def analysis(settings):
    from escalation_insight.aggregate import run

    return run(settings)


@pytest.fixture
def result(analysis):
    from escalation_insight.aggregate import payload

    return payload(analysis)


def ticket(
    ticket_id: str = "T-1",
    case_id: str = "C-1",
    raw_category: str = "shipping delay",
    opened: str | None = "2026-01-10",
    recorded: str | None = "2026-01-11",
    team: str = "logistics",
    reopen_of: str | None = None,
) -> Ticket:
    return Ticket(
        ticket_id=ticket_id,
        case_id=case_id,
        raw_category=raw_category,
        team=team,
        opened_at=dt.date.fromisoformat(opened) if opened else None,
        recorded_at=dt.date.fromisoformat(recorded) if recorded else None,
        reopen_of=reopen_of,
    )
