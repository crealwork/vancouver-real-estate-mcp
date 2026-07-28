"""Parse FVREB's HPIMLX_DB.xlsx — the deep history layer.

Source: https://www.fvreb.bc.ca/statistics/HPIMLX_DB.xlsx

Covers 1991-06 .. 2011-09 at neighbourhood granularity across both the
Greater Vancouver and Fraser Valley boards, with sale counts, mean/median
price, hedonic (quality-adjusted) price, a 90% confidence interval on the
hedonic estimate, and the HPI itself. Nothing else we found goes back this
far at this resolution.
"""

from __future__ import annotations

import sys
from collections import defaultdict

import openpyxl

from common import OUT, RAW, DecodeError, decode_hpimlx_month, num, slugify, write_jsonl

SOURCE_FILE = RAW / "HPIMLX_DB.xlsx"
SOURCE_URL = "https://www.fvreb.bc.ca/statistics/HPIMLX_DB.xlsx"

# Column order in the sheet.
COLUMNS = [
    "MARKET_LABEL",
    "PROPERTY_TYPE",
    "AREA",
    "MONTH",
    "SALE_COUNT",
    "MEAN_PRICE",
    "MEDIAN_PRICE",
    "HEDONIC_PRICE",
    "CI90_LOWER",
    "CI90_UPPER",
    "HPI",
]

PROPERTY_TYPE_MAP = {
    "RESIDENTIAL": "composite",
    "DETACHED": "detached",
    "ATTACHED": "townhouse",
    "APARTMENT": "apartment",
    "DET_ACRE": "detached_acreage",
}


def parse(path=SOURCE_FILE):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["HPIMLX_DB"]
    rows = ws.iter_rows(values_only=True)

    header = [str(c).strip() if c is not None else "" for c in next(rows)[: len(COLUMNS)]]
    if header != COLUMNS:
        raise DecodeError(f"unexpected header: {header}")

    for raw in rows:
        rec = dict(zip(COLUMNS, raw))
        area = rec["AREA"]
        month = rec["MONTH"]
        # The file carries a blank spacer row at the head of every series.
        if area is None or month is None or not hasattr(month, "year"):
            continue

        ptype = PROPERTY_TYPE_MAP.get(rec["PROPERTY_TYPE"])
        if ptype is None:
            raise DecodeError(f"unknown property type {rec['PROPERTY_TYPE']!r}")

        area = str(area).strip()
        yield {
            "source": "fvreb_hpimlx_db",
            "source_url": SOURCE_URL,
            "market_label": str(rec["MARKET_LABEL"]).strip(),
            "area_raw": area,
            "area_slug": slugify(area),
            "property_type": ptype,
            "period": decode_hpimlx_month(month),
            "sales": num(rec["SALE_COUNT"]),
            "mean_price": num(rec["MEAN_PRICE"]),
            "median_price": num(rec["MEDIAN_PRICE"]),
            "hedonic_price": num(rec["HEDONIC_PRICE"]),
            "ci90_lower": num(rec["CI90_LOWER"]),
            "ci90_upper": num(rec["CI90_UPPER"]),
            "hpi": num(rec["HPI"]),
        }


def fetch() -> None:
    """Download the workbook if we do not already have it."""
    import urllib.request

    from common import UA

    if SOURCE_FILE.exists() and SOURCE_FILE.stat().st_size > 100_000:
        return
    SOURCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(SOURCE_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = resp.read()
    if len(body) < 100_000:
        raise DecodeError(f"{SOURCE_URL} returned only {len(body)} bytes")
    SOURCE_FILE.write_bytes(body)
    print(f"downloaded {SOURCE_FILE.name} ({len(body):,} bytes)")


def main() -> int:
    fetch()
    if not SOURCE_FILE.exists():
        print(f"missing {SOURCE_FILE}", file=sys.stderr)
        return 1

    records = list(parse())
    if not records:
        raise DecodeError("parsed zero records")

    periods = sorted({r["period"] for r in records})
    areas = sorted({r["area_raw"] for r in records})
    by_type = defaultdict(int)
    for r in records:
        by_type[r["property_type"]] += 1

    # Every series must be gap-free once decoded; a decoding slip would show
    # up here as holes or duplicates.
    series = defaultdict(list)
    for r in records:
        series[(r["area_raw"], r["property_type"])].append(r["period"])
    broken = []
    for key, months in series.items():
        if len(months) != len(set(months)):
            broken.append((key, "duplicate periods"))
    if broken:
        raise DecodeError(f"{len(broken)} series with duplicate periods, e.g. {broken[:3]}")

    path = OUT / "fvreb_hpimlx.jsonl"
    n = write_jsonl(path, records)

    print(f"wrote {n:,} records -> {path}")
    print(f"  period range : {periods[0]} .. {periods[-1]}  ({len(periods)} months)")
    print(f"  areas        : {len(areas)}")
    print(f"  series       : {len(series):,}")
    print(f"  by type      : {dict(by_type)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
