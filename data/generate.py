"""Writes the escalation corpus, and OWNS the directory it writes into.

Hand-authored rather than random, so a reader can check every number this project reports
against the input by eye. The shape mirrors a real escalation review -- free-text categories
with regional spellings and typos, tickets that reopen against one case, a recording lag
distinct from the event time -- and none of the content is real.

Each ticket exists to produce a specific finding, and the comments say which. The generator
PRUNES anything it did not write: a leftover export from an older field convention parses
cleanly and silently changes every count in the report.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

HERE = Path(__file__).parent

AS_OF = "2026-03-12"
"""The analysis runs mid-month, which is the ordinary case and the reason the newest bucket is
incomplete. Nothing in the export says so; it is a property of when someone pressed the button."""

# --------------------------------------------------------------------------------------
# F1: two raw labels that MEAN the same thing, arranged so that merging them REVERSES the
# trend. Unmerged, `shipping delay` runs 10 -> 6 (down). Merged with `late delivery`, the
# canonical category runs 10 -> 12 (up). Same tickets, opposite sign.
# --------------------------------------------------------------------------------------
SYNONYM_ROWS: list[tuple[str, str, str, str]] = []
for i in range(10):
    SYNONYM_ROWS.append((f"T-1{i:02d}", "shipping delay", "2026-01-14", "logistics"))
for i in range(6):
    SYNONYM_ROWS.append((f"T-2{i:02d}", "shipping delay", "2026-02-11", "logistics"))
for i in range(6):
    # The UK spelling. v1 of the mapping has never heard of it; v2 folds it in.
    SYNONYM_ROWS.append((f"T-3{i:02d}", "late delivery", "2026-02-18", "logistics"))

# --------------------------------------------------------------------------------------
# F5: the unit of analysis. January has 6 tickets across 6 cases. February has 9 tickets
# across 4 cases, because ONE case was reopened five times. By ticket the month is up
# (6 -> 9); by case it is down (6 -> 4).
# --------------------------------------------------------------------------------------
REOPEN_ROWS: list[tuple[str, str, str, str, str, str | None]] = []
for i in range(6):
    REOPEN_ROWS.append(
        (f"T-4{i:02d}", f"C-4{i:02d}", "return refused", "2026-01-20", "returns", None)
    )
for i in range(3):
    REOPEN_ROWS.append(
        (f"T-5{i:02d}", f"C-5{i:02d}", "return refused", "2026-02-09", "returns", None)
    )
# The case that would not die. Six tickets, one problem, and it is the WORST problem here.
REOPEN_ROWS.append(("T-600", "C-600", "return refused", "2026-02-03", "returns", None))
for i in range(1, 6):
    REOPEN_ROWS.append(
        (f"T-60{i}", "C-600", "return refused", f"2026-02-{3 + i:02d}", "returns", "T-600")
    )

# --------------------------------------------------------------------------------------
# F3 in the corpus: a "3x increase" made of counts so small the phrase means nothing.
# 1 -> 3. The tool must decline to call this a trend.
# --------------------------------------------------------------------------------------
SMALL_ROWS = [
    ("T-700", "packaging damaged", "2026-01-08", "fulfilment"),
    ("T-701", "packaging damaged", "2026-02-06", "fulfilment"),
    ("T-702", "packaging damaged", "2026-02-13", "fulfilment"),
    ("T-703", "packaging damaged", "2026-02-24", "fulfilment"),
]

# --------------------------------------------------------------------------------------
# F4: the newest bucket. March is cut off at the 12th, so its exposure is 12/31 of a month.
# Two of these were opened before the cutoff and RECORDED after it, so an export taken on
# the 12th does not contain them at all -- represented here by a recorded_at past AS_OF.
# --------------------------------------------------------------------------------------
MARCH_ROWS = [
    ("T-800", "shipping delay", "2026-03-02", "2026-03-03", "logistics"),
    ("T-801", "shipping delay", "2026-03-05", "2026-03-06", "logistics"),
    ("T-802", "return refused", "2026-03-09", "2026-03-10", "returns"),
    # Opened inside the window, recorded outside it. Real, and invisible on the 12th.
    ("T-803", "shipping delay", "2026-03-11", "2026-03-19", "logistics"),
    ("T-804", "return refused", "2026-03-11", "2026-03-20", "returns"),
]

# --------------------------------------------------------------------------------------
# Producer-side defects, one of each kind `check` gates on. Every one is fixable by
# whoever produced the export, which is exactly why they are the gating set.
# --------------------------------------------------------------------------------------
DEFECT_ROWS = [
    # A label no version of the mapping knows. Fixable: fix the label or extend the mapping.
    ("T-900", "C-900", "widget went bang", "2026-02-10", "2026-02-11", "unknown", None),
    # No event time at all. Cannot be bucketed, so it is absent from every series silently.
    ("T-901", "C-901", "shipping delay", "", "2026-02-12", "logistics", None),
    # An ordinary row in a category that exists ONLY to carry the remaining defects, so that
    # no defect pollutes a category some finding depends on.
    ("T-910", "C-910", "escalation misc", "2026-02-15", "2026-02-16", "misc", None),
    # The same id a second time. Every count that touches it is off by one, in a direction
    # nobody can recover, because there is no way to tell which row is the real one.
    ("T-910", "C-911", "escalation misc", "2026-02-17", "2026-02-18", "misc", None),
    # Recorded BEFORE it happened. Not a lag, an impossibility.
    ("T-911", "C-912", "escalation misc", "2026-02-15", "2026-02-14", "misc", None),
    # A reopen whose parent is not in this export, so case lineage cannot be built.
    ("T-912", "C-913", "escalation misc", "2026-02-16", "2026-02-17", "misc", "T-ABSENT"),
]

# --------------------------------------------------------------------------------------
# F6: what the SOP actually covers. `return refused` IS documented -- section 4.2 -- and it
# is still the most-asked topic here. That is the finding: a topic can be documented and
# still asked about, so a question count cannot tell a missing section from an unfindable
# one, and "add it to the SOP" would make the real cause worse.
# --------------------------------------------------------------------------------------
SOP_COVERAGE = {
    "delivery_timing": "3.1",
    "returns": "4.2",
    "packaging": None,
}


def rows() -> list[dict[str, str]]:
    """Every ticket, in one flat shape. Deliberately stringly-typed: this is an export."""
    out: list[dict[str, str]] = []

    def add(
        ticket_id: str,
        case_id: str,
        raw_category: str,
        opened_at: str,
        recorded_at: str,
        team: str,
        reopen_of: str | None,
    ) -> None:
        out.append(
            {
                "ticket_id": ticket_id,
                "case_id": case_id,
                "raw_category": raw_category,
                "opened_at": opened_at,
                "recorded_at": recorded_at,
                "team": team,
                "reopen_of": reopen_of or "",
            }
        )

    for ticket_id, raw, opened, team in SYNONYM_ROWS:
        add(ticket_id, ticket_id.replace("T-", "C-"), raw, opened, opened, team, None)
    for ticket_id, case_id, raw, opened, team, parent in REOPEN_ROWS:
        add(ticket_id, case_id, raw, opened, opened, team, parent)
    for ticket_id, raw, opened, team in SMALL_ROWS:
        add(ticket_id, ticket_id.replace("T-", "C-"), raw, opened, opened, team, None)
    for ticket_id, opened, recorded, team in [
        (r[0], r[2], r[3], r[4]) for r in MARCH_ROWS
    ]:
        raw = next(r[1] for r in MARCH_ROWS if r[0] == ticket_id)
        add(ticket_id, ticket_id.replace("T-", "C-"), raw, opened, recorded, team, None)
    for ticket_id, case_id, raw, opened, recorded, team, parent in DEFECT_ROWS:
        add(ticket_id, case_id, raw, opened, recorded, team, parent)
    return out


MAPPINGS = {
    "v1": {
        "description": "The mapping as it stood in January. It has never seen the UK spelling.",
        "categories": {
            "shipping delay": "delivery_timing",
            "return refused": "returns",
            "packaging damaged": "packaging",
            "escalation misc": "misc",
        },
    },
    "v2": {
        "description": (
            "Revised in February to fold in the UK spelling. Applying it re-counts every month "
            "that was already published."
        ),
        "categories": {
            "shipping delay": "delivery_timing",
            "late delivery": "delivery_timing",
            "return refused": "returns",
            "packaging damaged": "packaging",
            "escalation misc": "misc",
        },
    },
    "v3_split": {
        "description": (
            "A third reading that SPLITS delivery timing back apart, on the argument that a "
            "carrier delay and a late promise are different problems. Nothing in the tickets "
            "settles which reading is right."
        ),
        "categories": {
            "shipping delay": "carrier_delay",
            "late delivery": "promise_missed",
            "return refused": "returns",
            "packaging damaged": "packaging",
            "escalation misc": "misc",
        },
    },
}

QUESTION_COUNTS = {
    "returns": 41,
    "delivery_timing": 12,
    "packaging": 3,
}
"""How many questions each canonical topic drew. `returns` leads by a distance AND is the one
topic the SOP documents, which is the whole of F6."""

MANIFEST_FILES = ("tickets.csv", "mappings.json", "sop.json")


def write() -> None:
    HERE.joinpath("tickets.csv").write_text(_csv(rows()), encoding="utf-8")
    HERE.joinpath("mappings.json").write_text(
        json.dumps({"as_of": AS_OF, "versions": MAPPINGS}, indent=2) + "\n", encoding="utf-8"
    )
    HERE.joinpath("sop.json").write_text(
        json.dumps(
            {"document": "escalation-sop", "revision": 7, "covers": SOP_COVERAGE,
             "questions": QUESTION_COUNTS},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    for path in HERE.iterdir():
        if path.suffix in {".csv", ".json"} and path.name not in MANIFEST_FILES:
            path.unlink()


def _csv(records: list[dict[str, str]]) -> str:
    import io

    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "ticket_id",
            "case_id",
            "raw_category",
            "opened_at",
            "recorded_at",
            "team",
            "reopen_of",
        ],
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(records)
    return buf.getvalue()


if __name__ == "__main__":
    write()
    print(f"wrote {len(rows())} tickets and {len(MAPPINGS)} mapping versions to {HERE}")
