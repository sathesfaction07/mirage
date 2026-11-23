"""Settings, and the fact that four of them decide the answer.

Every field below is CHOSEN. None is measured, none is discoverable from the escalations,
and each one can change the direction this tool reports. They are gathered here so that
`doctor` can print them under one heading and nobody mistakes them for findings.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .models import Grain, Unit

DEFAULT_ALPHA = 0.05
"""The threshold for calling a change real.

0.05 is a convention with no basis in escalation management, and it is printed by `doctor`
as a convention rather than a property of the data. Raising it produces more findings and
more wrong ones; lowering it produces fewer of both. Nothing here can tell you which cost
your team would rather pay, so the number is exposed rather than buried.
"""


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    data_dir: Path = Field(default=Path("data"))
    mapping_version: str = "v2"
    unit: Unit = Unit.TICKET
    grain: Grain = Grain.MONTH
    alpha: float = Field(default=DEFAULT_ALPHA, gt=0.0, lt=1.0)
    complete_only: bool = True
    """Whether to drop the unfinished newest bucket. True is the cautious choice and it is
    also the one that makes the report silent about the current month."""

    as_of: dt.date | None = None
    """Overrides the corpus's own cut-off date. Present so the censoring finding can be
    demonstrated at other cut-offs, since the effect depends entirely on when you look."""

    @property
    def tickets_path(self) -> Path:
        return self.data_dir / "tickets.csv"

    @property
    def mappings_path(self) -> Path:
        return self.data_dir / "mappings.json"

    @property
    def sop_path(self) -> Path:
        return self.data_dir / "sop.json"


CHOSEN_NOT_MEASURED: dict[str, str] = {
    "mapping_version": (
        "decides which raw labels are one category. Merging two labels can reverse a trend, "
        "and revising the mapping re-counts months that were already published."
    ),
    "unit": (
        "decides what one counted thing is. TICKET and CASE move in opposite directions on "
        "the same escalations."
    ),
    "grain": (
        "decides bucket width. Months are of unequal length; weeks straddle month ends. "
        "There is no grain with both properties."
    ),
    "complete_only": (
        "decides whether the unfinished newest bucket is in the answer. Excluding it makes "
        "the report silent about the current month; including it shows a decline built from "
        "the calendar and the recording lag."
    ),
    "alpha": (
        "decides how much evidence counts as enough. A convention, not a measurement, and "
        "not derived from anything about escalations."
    ),
}
