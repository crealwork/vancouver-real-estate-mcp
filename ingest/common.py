"""Shared helpers for the ingest pipeline."""

from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "out"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)


class DecodeError(ValueError):
    """Raised when source data does not match the encoding we expect."""


def decode_hpimlx_month(value: dt.datetime | dt.date) -> str:
    """Decode the MONTH column of FVREB's HPIMLX_DB.xlsx into 'YYYY-MM'.

    The workbook stores each period as an Excel serial date whose *day*
    component carries the month: 1991-06 was written out in a form Excel read
    back as 1991-01-06. So the real period is (year=Y, month=D), and the
    month component of the parsed date is always January.

    Verified against the full file: 244 distinct values spanning 1991-06
    through 2011-09, with year-boundary gaps of 354/355 days (365/366 minus
    the 11 in-year steps), which only holds under this reading.
    """
    if value.month != 1:
        raise DecodeError(f"expected January in encoded value, got {value!r}")
    if not 1 <= value.day <= 12:
        raise DecodeError(f"day component {value.day} is not a valid month in {value!r}")
    return f"{value.year:04d}-{value.day:02d}"


def month_key(period: str) -> int:
    """'2005-01' -> 24060. Sortable integer month index."""
    y, m = period.split("-")
    return int(y) * 12 + int(m) - 1


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return re.sub(r"-{2,}", "-", s)


def num(value) -> float | None:
    """Coerce a spreadsheet/PDF cell to a number, or None if it is blank."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "").replace("$", "").replace("%", "")
    if s in ("", "-", "--", "N/A", "n/a", "*"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def write_jsonl(path: Path, records) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    return n


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)
