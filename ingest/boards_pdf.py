"""Download and parse the monthly stats packages from both boards.

Each package carries an "MLS(R) Home Price Index" table: one row per
(property type, area) with the benchmark price, the index, and % change over
1/3/6 months and 1/3/5/10 years. That table is the only place neighbourhood
level data exists after FVREB's HPIMLX_DB stops in 2011-09.

The two boards lay the table out differently, but both reduce to:
    <label...> <benchmark> <index> <7 percentages>
so one row regex handles both; only the property-type headers differ.

Usage:
    python boards_pdf.py fvreb    # 2008-01 .. current, Fraser Valley areas
    python boards_pdf.py gvr      # whatever discover_gvr.py found
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import OUT, RAW, UA, DecodeError, num, slugify, write_jsonl

FVREB_PDF_URL = "https://www.fvreb.bc.ca/statistics/Package{ym}.pdf"
FVREB_PDF_URL_SPACED = "https://www.fvreb.bc.ca/statistics/Package%20{ym}.pdf"

# Property-type headers as they appear at the start of a row, most specific
# first. A value of None means "this word continues the previous header"
# (FVREB prints "RESIDENTIAL" and "COMBINED" on consecutive lines).
TYPE_HEADERS: list[tuple[re.Pattern, str | None]] = [
    (re.compile(r"^residential\s*/\s*composite\b", re.I), "composite"),
    (re.compile(r"^single\s+family\s+detached\b", re.I), "detached"),
    (re.compile(r"^residential\b", re.I), "composite"),
    (re.compile(r"^combined\b", re.I), None),
    (re.compile(r"^detached\b", re.I), "detached"),
    (re.compile(r"^townhouse\b", re.I), "townhouse"),
    (re.compile(r"^apartment\b", re.I), "apartment"),
    (re.compile(r"^acreage\b", re.I), "detached_acreage"),
]

CHANGE_FIELDS = [
    "change_1m",
    "change_3m",
    "change_6m",
    "change_1y",
    "change_3y",
    "change_5y",
    "change_10y",
]

# The number of change columns grew over time: packages before ~2015 stop at
# FIVE YEAR because the index itself only began in 2005, so there was no ten
# year figure to print yet. Accept 4-7 and map them in printed order.
ROW = re.compile(
    r"^(?P<label>[A-Za-z][A-Za-z0-9 .,'&()/–—-]*?)\s+"
    r"\$?\s*(?P<bench>\d{1,3}(?:,\d{3})+|\d{5,})\s+"
    r"(?P<index>\d+\.\d+)\s+"
    r"(?P<rest>-?\d+\.?\d*%?(?:\s+-?\d+\.?\d*%?){3,6})\s*$"
)

# Lines that look like data rows but are not area rows.
SKIP_LABELS = re.compile(r"^(benchmark|price|index|area|property\s+type|source|mls)\b", re.I)


def fetch(url: str, dest: Path) -> Path | None:
    if dest.exists() and dest.stat().st_size > 10_000:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = resp.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return None
    if len(body) < 10_000 or not body[:5].startswith(b"%PDF"):
        return None
    dest.write_bytes(body)
    return dest


def pdf_text(path: Path) -> str:
    out = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        raise DecodeError(f"pdftotext failed on {path.name}: {out.stderr[:200]}")
    return out.stdout


def strip_type_header(label: str, current: str | None) -> tuple[str, str | None]:
    """Split a row label into (area, property_type)."""
    for pattern, ptype in TYPE_HEADERS:
        m = pattern.match(label)
        if m:
            rest = label[m.end():].strip()
            return rest, (current if ptype is None else ptype)
    return label.strip(), current


def parse_hpi_table(text: str, period: str, source: str, url: str):
    current_type: str | None = None
    for line in text.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        m = ROW.match(line.strip())
        if not m:
            # A header line may set the property type without carrying data.
            stripped = line.strip()
            for pattern, ptype in TYPE_HEADERS:
                if pattern.match(stripped) and ptype is not None and len(stripped) < 40:
                    current_type = ptype
                    break
            continue

        label = m.group("label").strip()
        if SKIP_LABELS.match(label):
            continue

        area, current_type = strip_type_header(label, current_type)
        # pdftotext preserves column padding, so the same area can arrive with
        # different runs of internal whitespace.
        area = re.sub(r"\s{2,}", " ", area).strip()
        if not area or current_type is None:
            continue
        # Guard against footnote/legend lines sneaking through.
        if len(area) > 45 or not re.search(r"[A-Za-z]", area):
            continue

        changes = [num(v) for v in m.group("rest").split()]
        if not 4 <= len(changes) <= len(CHANGE_FIELDS):
            continue

        rec = {
            "source": source,
            "source_url": url,
            "area_raw": area,
            "area_slug": slugify(area),
            "property_type": current_type,
            "period": period,
            "benchmark_price": num(m.group("bench")),
            "hpi": num(m.group("index")),
        }
        rec.update(dict(zip(CHANGE_FIELDS, changes)))
        yield rec


def fvreb_targets() -> dict[str, str]:
    """FVREB publishes Package{YYYYMM}.pdf, with a space in older filenames."""
    targets = {}
    for year in range(2008, 2027):
        for month in range(1, 13):
            ym = f"{year:04d}{month:02d}"
            targets[f"{year:04d}-{month:02d}"] = ym
    return targets


def run_fvreb() -> list[dict]:
    pdf_dir = RAW / "fvreb_pdf"
    records: list[dict] = []
    targets = fvreb_targets()

    def get(item):
        period, ym = item
        dest = pdf_dir / f"Package{ym}.pdf"
        path = fetch(FVREB_PDF_URL.format(ym=ym), dest)
        url = FVREB_PDF_URL.format(ym=ym)
        if path is None:
            url = FVREB_PDF_URL_SPACED.format(ym=ym)
            path = fetch(url, dest)
        return period, path, url

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(get, sorted(targets.items())))

    got = 0
    for period, path, url in results:
        if path is None:
            continue
        got += 1
        try:
            rows = list(parse_hpi_table(pdf_text(path), period, "fvreb_pdf", url))
        except DecodeError as exc:
            print(f"  ! {period}: {exc}", file=sys.stderr)
            continue
        if not rows:
            print(f"  ~ {period}: no HPI rows parsed", file=sys.stderr)
        records.extend(rows)
    print(f"  fvreb: {got} PDFs downloaded, {len(records):,} rows parsed")
    return records


def run_gvr() -> list[dict]:
    index_path = OUT / "gvr_pdf_index.json"
    if not index_path.exists():
        raise SystemExit("run discover_gvr.py first")
    index = json.loads(index_path.read_text())
    pdf_dir = RAW / "gvr_pdf"
    records: list[dict] = []

    def get(item):
        period, url = item
        dest = pdf_dir / f"GVR-{period}.pdf"
        return period, fetch(url, dest), url

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(get, sorted(index.items())))

    got = 0
    for period, path, url in results:
        if path is None:
            continue
        got += 1
        try:
            rows = list(parse_hpi_table(pdf_text(path), period, "gvr_pdf", url))
        except DecodeError as exc:
            print(f"  ! {period}: {exc}", file=sys.stderr)
            continue
        if not rows:
            print(f"  ~ {period}: no HPI rows parsed", file=sys.stderr)
        records.extend(rows)
    print(f"  gvr: {got} PDFs downloaded, {len(records):,} rows parsed")
    return records


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    records: list[dict] = []
    if which in ("fvreb", "both"):
        records += run_fvreb()
    if which in ("gvr", "both"):
        records += run_gvr()

    if not records:
        raise DecodeError("parsed zero PDF records")

    by_source: dict[str, list[dict]] = {}
    for r in records:
        by_source.setdefault(r["source"], []).append(r)

    for source, rows in by_source.items():
        path = OUT / f"{source}.jsonl"
        write_jsonl(path, rows)
        periods = sorted({r["period"] for r in rows})
        areas = sorted({r["area_raw"] for r in rows})
        print(f"\n{source}: {len(rows):,} rows -> {path}")
        print(f"  periods : {periods[0]} .. {periods[-1]}  ({len(periods)})")
        print(f"  areas   : {len(areas)}")
        print(f"  sample  : {areas[:8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
