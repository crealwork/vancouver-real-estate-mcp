"""Extract market activity — sales, listings, inventory — from the packages.

The HPI table answers "what is a typical home worth". This answers "what is
the market doing": how many homes sold, how many came up, how much is sitting
unsold, and the sales-to-active ratio the boards themselves use to call a
buyer's or seller's market.

The two boards lay this out very differently:

  * FVREB prints a vertical block per area — one row per metric, columns for
    each property type. Straightforward and safe to parse.

  * GVR prints a wide matrix with areas as columns and the header text set
    vertically, so pdftotext shreds the area names ("Burnab" / "y" on separate
    lines). Mapping a column back to an area by position would be guesswork,
    so we take only the board total, which is the last column and is
    verifiable: it must equal the sum of the columns before it.

Writes data/out/activity.jsonl.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from common import OUT, RAW, DecodeError, num, slugify, write_jsonl

# FVREB block: metric label, then 3 property types x (current, year ago,
# %change, month ago, %change).
FV_METRICS = {
    "Sales": "sales",
    "New Listings": "new_listings",
    "Active Listings": "active_listings",
    "Median Price": "median_price",
    "Average Price": "mean_price",
}
FV_TYPES = ["detached", "townhouse", "apartment"]
FV_HEADER = re.compile(r"^(?P<area>[A-Za-z][A-Za-z .,'&()/-]*?)\s{2,}\w{3}-\d{2}\s+\w{3}-\d{2}\s+%\s*change")
FV_ROW = re.compile(r"^(?P<label>Sales|New Listings|Active Listings|Median Price|Average Price)\s+(?P<rest>.+)$")

GVR_TYPES = {"Detached": "detached", "Attached": "townhouse", "Apartment": "apartment"}


def pdf_text(path: Path) -> str:
    out = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, check=False
    )
    if out.returncode != 0:
        raise DecodeError(f"pdftotext failed on {path.name}")
    return out.stdout


def parse_fvreb(text: str, period: str, url: str):
    """Vertical per-area blocks."""
    lines = text.splitlines()
    area: str | None = None
    pending: dict[str, dict] = {}

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        m = FV_HEADER.match(stripped)
        if m:
            candidate = re.sub(r"\s{2,}", " ", m.group("area")).strip()
            # Skip the legend/footnote lines that share this shape.
            if 2 < len(candidate) < 40:
                area = candidate
                pending = {}
            continue

        if area is None:
            continue

        r = FV_ROW.match(stripped)
        if not r:
            continue
        values = [num(v) for v in re.findall(r"-?[\d,]+\.?\d*%?|\$\s*[\d,]+", r.group("rest"))]
        # 3 types x 5 columns; anything else means the layout differs.
        if len(values) < 11:
            continue
        metric = FV_METRICS[r.group("label")]
        for i, ptype in enumerate(FV_TYPES):
            v = values[i * 5] if i * 5 < len(values) else None
            if v is None:
                continue
            key = ptype
            pending.setdefault(key, {})[metric] = v

        if metric == "mean_price":  # last row of the block
            for ptype, metrics in pending.items():
                yield {
                    "source": "fvreb_pdf",
                    "source_url": url,
                    "area_raw": area,
                    "area_slug": slugify(area),
                    "property_type": ptype,
                    "period": period,
                    **metrics,
                }
            area, pending = None, {}


def parse_gvr_totals(text: str, period: str, url: str):
    """Board totals only — the last column of the wide matrix, checked by sum."""
    out: dict[str, dict] = {}
    section: str | None = None

    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if "number" in low and "listings" in low:
            section = "new_listings"
        elif "number" in low and "sales" in low:
            section = "sales"
        elif re.search(r"\bmedian\b", low) and "price" in low:
            section = "median_price"

        m = re.match(r"^(?:.*?\b)?(Detached|Attached|Apartment)\s+(?P<rest>[\d,.$ nan/]+)$", s)
        if not m or section is None:
            continue
        ptype = GVR_TYPES[m.group(1)]
        values = [num(v) for v in re.findall(r"\$?\s*[\d,]+(?:\.\d+)?", m.group("rest"))]
        values = [v for v in values if v is not None]
        if len(values) < 4:
            continue
        total, parts = values[-1], values[:-1]
        # The total column must reconcile; if it does not, the row was
        # misread and is dropped rather than guessed at.
        if section in ("sales", "new_listings"):
            if abs(sum(parts) - total) > 0.5:
                continue
        else:
            continue  # medians do not sum; skip
        # The matrix repeats for the current month, the prior month, the same
        # month last year, then year-to-date. The current month comes first,
        # so never overwrite a value we already captured.
        out.setdefault(ptype, {}).setdefault(section, total)

    for ptype, metrics in out.items():
        if metrics:
            yield {
                "source": "gvr_pdf",
                "source_url": url,
                "area_raw": "Greater Vancouver",
                "area_slug": "greater-vancouver",
                "property_type": ptype,
                "period": period,
                **metrics,
            }


def main() -> int:
    records: list[dict] = []

    fv_dir = RAW / "fvreb_pdf"
    for path in sorted(fv_dir.glob("Package*.pdf")):
        ym = re.search(r"(\d{6})", path.name)
        if not ym:
            continue
        period = f"{ym.group(1)[:4]}-{ym.group(1)[4:]}"
        try:
            rows = list(parse_fvreb(pdf_text(path), period, f"fvreb:{path.name}"))
        except DecodeError as exc:
            print(f"  ! {path.name}: {exc}", file=sys.stderr)
            continue
        records.extend(rows)
    print(f"  fvreb activity rows: {len([r for r in records if r['source']=='fvreb_pdf']):,}")

    gvr_dir = RAW / "gvr_pdf"
    for path in sorted(gvr_dir.glob("GVR-*.pdf")):
        m = re.search(r"(\d{4}-\d{2})", path.name)
        if not m:
            continue
        try:
            records.extend(list(parse_gvr_totals(pdf_text(path), m.group(1), f"gvr:{path.name}")))
        except DecodeError as exc:
            print(f"  ! {path.name}: {exc}", file=sys.stderr)
    print(f"  gvr total rows     : {len([r for r in records if r['source']=='gvr_pdf']):,}")

    if not records:
        raise DecodeError("parsed zero activity records")

    n = write_jsonl(OUT / "activity.jsonl", records)
    periods = sorted({r["period"] for r in records})
    areas = sorted({r["area_raw"] for r in records})
    print(f"\nwrote {n:,} rows -> data/out/activity.jsonl")
    print(f"  periods: {periods[0]} .. {periods[-1]} ({len(periods)})")
    print(f"  areas  : {len(areas)}")
    print(f"  sample : {areas[:10]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
