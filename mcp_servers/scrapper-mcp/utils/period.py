"""Parse user-facing ``Microdatos (…)`` period strings into ``(year, quarter)`` pairs.

Accepted shapes (case-insensitive, trimmed):

- ``Microdatos (2025)``              → year 2025, Q1..Q4
- ``Microdatos y documentos 2016-2025`` → years 2016..2025, Q1..Q4
- ``Microdatos (2020-2021)``         → 2020..2021, Q1..Q4
- ``2025``                           → year 2025, Q1..Q4
- ``2020-2021``                      → years 2020..2021, Q1..Q4
- ``2025 Q3`` / ``2025 T3`` / ``2025-Q3`` → single (2025, 3)
- ``2024 Q1,Q2`` / ``2024 Q1-Q3``    → (2024, 1), (2024, 2), (2024, 3)

``Bases REDATAM`` and any other non-numeric labels are rejected with a clear error so
the caller does not silently fetch the wrong dataset.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_YEAR_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_RANGE_RE = re.compile(r"(?<!\d)(\d{4})\s*[-–]\s*(\d{4})(?!\d)")
_Q_RE = re.compile(r"[QqTt]\s*([1-4])")


class PeriodError(ValueError):
    """Invalid or unsupported period input."""


@dataclass(frozen=True)
class PeriodItem:
    year: int
    quarter: int


def parse_period(value: str) -> list[PeriodItem]:
    """Return the (year, quarter) list implied by *value*.

    Raises ``PeriodError`` when the input has no recognizable year, a year range
    is malformed, or an unsupported label is present (e.g. ``Bases REDATAM``).
    """

    text = (value or "").strip()
    if not text:
        raise PeriodError("empty period")

    lower = text.lower()
    if "redatam" in lower:
        raise PeriodError(
            "REDATAM bases are not supported by indec_mercado_laboral "
            "(different site, different format). Use an EPH microdatos period, "
            "e.g. 'Microdatos (2024)' or '2020-2021'."
        )

    years: list[int] = []
    m_range = _RANGE_RE.search(text)
    if m_range:
        y0, y1 = int(m_range.group(1)), int(m_range.group(2))
        if y1 < y0:
            raise PeriodError(f"year range goes backwards: {y0}-{y1}")
        years = list(range(y0, y1 + 1))
    else:
        years = [int(m.group(1)) for m in _YEAR_RE.finditer(text)]

    if not years:
        raise PeriodError(f"no year found in period: {value!r}")

    quarters = [int(m.group(1)) for m in _Q_RE.finditer(text)]
    if not quarters:
        quarters = [1, 2, 3, 4]
    quarters = sorted(set(quarters))
    years = sorted(set(years))

    return [PeriodItem(year=y, quarter=q) for y in years for q in quarters]
