"""Merge every source into one continuous monthly series per (area, type).

The hard part is that the boards restate the MLS(R) HPI. FVREB publishes the
proof itself ("Revised Benchmark Price" vs "Original Benchmark Price"), and
the effects show up everywhere:

  * the legacy HPIMLX series sits up to ~35% away from the current CREA
    benchmark on their 2005-2011 overlap;
  * even within one source, FVREB's own packages jump — Fraser Valley Board
    reads index 223.9 in the June 2010 package and 144.3 in June 2012,
    because the index was rebased in between.

So we cannot trust source boundaries alone. Instead every source is cut into
segments wherever its own month-over-month move is too large to be a real
market move, all segments are sorted newest-first, and each older segment is
chain-linked onto the accumulated series — using the overlap ratio when the
segments overlap, and the adjacent-month ratio when they merely abut. The
newest data therefore defines the level, and older data contributes only its
shape. No level jumps survive into the output.

Outputs data/out/series.jsonl and data/out/areas.json.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict

from common import OUT, month_key, read_jsonl, write_jsonl

SOURCES = ["crea_hpi", "gvr_pdf", "gvr_wayback", "fvreb_pdf", "fvreb_hpimlx"]

# A real market never moves this fast in a month; anything larger is a
# restatement boundary. Vancouver's worst months (Oct 2008, Aug 2016) were
# around -5%, so 20% leaves a wide margin.
JUMP_THRESHOLD = 0.20
# A hole this long inside one source is treated as a segment break too.
MAX_GAP_MONTHS = 15

ALIASES = {
    "greater-vancouver-board": "greater-vancouver",
    "fraser-valley-board": "fraser-valley",
    "fraser-valley-board-fvreb": "fraser-valley",
    "chilliwack-and-district-board": "chilliwack",
    "lower-mainland-gv-and-fv": "lower-mainland",
    "lower-mainland-gv-fv-area": "lower-mainland",
    "lower-mainland-lm": "lower-mainland",
    "white-rock-south-surrey": "south-surrey-and-white-rock",
    "south-surrey-white-rock": "south-surrey-and-white-rock",
    # FVREB packages print the property type on the same line as the board
    # name in some years, so it lands in the area label.
    "fraser-valley-board-apartment": "fraser-valley",
    "fraser-valley-board-detached": "fraser-valley",
    "fraser-valley-board-townhouse": "fraser-valley",
    "fraser-valley-board-house-w-acreage": "fraser-valley",
    "fraser-valley-board-acreage": "fraser-valley",
    # Abbreviated neighbourhood spellings in the later packages.
    "south-surrey-crescent-bch-ocean-prk": "south-surrey-crescent-beach-ocean-park",
    "surrey-cloverdale-and-n-surrey": "surrey-cloverdale-and-north-surrey",
    "maple-ridge-and-pitt-meadows": "maple-ridge-pitt-meadows",
    "city-of-surrey-combined": "surrey",
    "delta-ladner": "ladner",
    # The activity tables spell areas differently from the HPI tables.
    "delta-north": "north-delta",
    "surrey-central": "surrey",
    "surrey-north": "north-surrey",
    "surrey-cloverdale": "cloverdale",
    "all-areas-combined": "fraser-valley",
    "residential-totals": "fraser-valley",
    "delta-tsawwassen": "tsawwassen",
}

GVR_AREAS = {
    "bowen-island", "burnaby-east", "burnaby-north", "burnaby-south", "coquitlam",
    "ladner", "maple-ridge", "new-westminster", "north-vancouver", "pitt-meadows",
    "port-coquitlam", "port-moody", "richmond", "squamish", "sunshine-coast",
    "tsawwassen", "vancouver-east", "vancouver-west", "west-vancouver", "whistler",
}
FVREB_AREAS = {
    "north-delta", "north-surrey", "surrey", "cloverdale", "south-surrey-and-white-rock",
    "langley", "abbotsford", "mission",
}
BOARD_AREAS = {"greater-vancouver", "fraser-valley"}
AGGREGATE_AREAS = {"lower-mainland", "british-columbia", "canada", "chilliwack"}


def canonical_slug(raw: str) -> str:
    raw = re.sub(r"-{2,}", "-", raw.strip("-"))
    return ALIASES.get(raw, raw)


def price_of(rec: dict) -> float | None:
    for field in ("benchmark_price", "hedonic_price"):
        v = rec.get(field)
        if v:
            return float(v)
    return None


def load_all() -> dict:
    """-> {(area, ptype): {source: {period: rec}}}"""
    data: dict = defaultdict(lambda: defaultdict(dict))
    for source in SOURCES:
        path = OUT / f"{source}.jsonl"
        if not path.exists():
            print(f"  ! missing {path.name}")
            continue
        n = 0
        for rec in read_jsonl(path):
            if source == "crea_hpi":
                if rec.get("frequency") != "monthly" or rec.get("seasonally_adjusted"):
                    continue
            if price_of(rec) is None:
                continue
            area = canonical_slug(rec["area_slug"])
            key = (area, rec["property_type"])
            # Within one source and month, keep the first reading.
            data[key][source].setdefault(rec["period"], rec)
            n += 1
        print(f"  loaded {n:,} usable rows from {path.name}")
    return data


def segment(series: dict[str, dict]) -> list[dict[str, dict]]:
    """Cut one source's series wherever it jumps or gaps."""
    periods = sorted(series, key=month_key)
    if not periods:
        return []
    segments = [{periods[0]: series[periods[0]]}]
    for prev, cur in zip(periods, periods[1:]):
        gap = month_key(cur) - month_key(prev)
        p0, p1 = price_of(series[prev]), price_of(series[cur])
        monthly_rate = abs((p1 / p0) ** (1 / gap) - 1) if p0 and gap else 0.0
        if gap > MAX_GAP_MONTHS or monthly_rate > JUMP_THRESHOLD:
            segments.append({})
        segments[-1][cur] = series[cur]
    return segments


def geometric_mean(values: list[float]) -> float:
    return math.exp(sum(math.log(v) for v in values) / len(values))


# Beyond this, "assume the level did not move across the boundary" stops
# being a harmless approximation and starts inventing history.
MAX_BLIND_BRIDGE_MONTHS = 3


def link_factor(
    accum: dict[str, float],
    seg_prices: dict[str, float],
    parent: dict[str, float] | None = None,
) -> tuple[float, str] | None:
    """Scale factor bringing `seg_prices` onto `accum`'s level, plus how we got it."""
    overlap = sorted(set(accum) & set(seg_prices), key=month_key)
    if overlap:
        ratios = [accum[p] / seg_prices[p] for p in overlap if seg_prices[p]]
        if ratios:
            return geometric_mean(ratios), f"overlap {overlap[0]}..{overlap[-1]}"
        return None

    a_first = min(accum, key=month_key)
    s_last = max(seg_prices, key=month_key)
    if month_key(s_last) >= month_key(a_first) or not seg_prices[s_last]:
        return None
    gap = month_key(a_first) - month_key(s_last)

    if gap <= MAX_BLIND_BRIDGE_MONTHS:
        return accum[a_first] / seg_prices[s_last], f"adjacent across {gap}m gap"

    # A long hole — GVR neighbourhood data is missing 2011-10..2018-11, and
    # prices moved a great deal in between. Carry the parent area's actual
    # growth across the hole instead of pretending the level held flat.
    if parent and s_last in parent and a_first in parent and parent[s_last]:
        growth = parent[a_first] / parent[s_last]
        return (
            (accum[a_first] / growth) / seg_prices[s_last],
            f"bridged {gap}m gap using parent growth",
        )
    return None


def build_one(by_source: dict, parent: dict[str, float] | None = None) -> tuple[list[dict], list[dict]]:
    """Splice all sources for a single (area, property_type)."""
    segments = []
    for source in SOURCES:
        for seg in segment(by_source.get(source, {})):
            if seg:
                segments.append((source, seg))

    # Newest first: the most recent data defines the price level.
    segments.sort(key=lambda s: month_key(max(s[1], key=month_key)), reverse=True)

    accum: dict[str, float] = {}
    chosen: dict[str, dict] = {}
    splices: list[dict] = []
    basis_by_period: dict[str, str] = {}

    for source, seg in segments:
        seg_prices = {p: price_of(r) for p, r in seg.items()}
        if not accum:
            factor, how = 1.0, "anchor"
        else:
            linked = link_factor(accum, seg_prices, parent)
            if linked is None:
                continue  # cannot be placed on the modern level; drop it
            factor, how = linked
        basis = (
            "as_published"
            if factor == 1.0
            else ("bridged" if "bridged" in how else "chain_linked")
        )
        for period, rec in seg.items():
            if period in accum:
                continue
            accum[period] = round(seg_prices[period] * factor, 2)
            chosen[period] = rec
            basis_by_period[period] = basis
        if factor != 1.0:
            splices.append({
                "source": source,
                "factor": round(factor, 6),
                "how": how,
                "from": min(seg, key=month_key),
                "to": max(seg, key=month_key),
            })

    out = []
    for period in sorted(accum, key=month_key):
        rec = chosen[period]
        adjusted = accum[period]
        original = price_of(rec)
        out.append({
            "period": period,
            "benchmark_price": adjusted,
            "source": rec["source"],
            "hpi": rec.get("hpi"),
            "sales": rec.get("sales"),
            "median_price": rec.get("median_price"),
            "mean_price": rec.get("mean_price"),
            "is_adjusted": abs(adjusted - original) > 0.5,
            "basis": basis_by_period.get(period, "as_published"),
            "as_published": original,
        })
    return out, splices


def parent_of(area: str) -> str:
    """Which wider market to borrow growth from when an area has a long hole."""
    if area in AGGREGATE_AREAS or area in BOARD_AREAS:
        return ""
    if area in GVR_AREAS:
        return "greater-vancouver"
    if area in FVREB_AREAS:
        return "fraser-valley"
    # Neighbourhood names carry their municipality as a prefix.
    for m in sorted(GVR_AREAS | FVREB_AREAS, key=len, reverse=True):
        if area.startswith(m):
            return "greater-vancouver" if m in GVR_AREAS else "fraser-valley"
    if area.startswith(("vancouver", "burnaby", "north-vancouver", "west-vancouver")):
        return "greater-vancouver"
    return "lower-mainland"


def main() -> int:
    data = load_all()
    series: list[dict] = []
    splice_log: dict[str, list] = {}
    stats = defaultdict(int)

    # Pass 1: the wide markets. CREA covers these continuously from 2005, so
    # they need no bridging and can serve as the reference for everything else.
    reference: dict[tuple, dict[str, float]] = {}
    for (area, ptype), by_source in sorted(data.items()):
        if area not in (AGGREGATE_AREAS | BOARD_AREAS):
            continue
        points, _ = build_one(by_source)
        if points:
            reference[(area, ptype)] = {p["period"]: p["benchmark_price"] for p in points}

    def reference_for(area: str, ptype: str) -> dict[str, float] | None:
        p = parent_of(area)
        if not p:
            return None
        return reference.get((p, ptype)) or reference.get((p, "composite"))

    # Pass 2: everything, now able to bridge long gaps.
    for (area, ptype), by_source in sorted(data.items()):
        points, splices = build_one(by_source, reference_for(area, ptype))
        if not points:
            continue
        if splices:
            splice_log[f"{area}|{ptype}"] = splices
            stats["series_with_splice"] += 1
        stats["series"] += 1
        for p in points:
            p["area_slug"] = area
            p["property_type"] = ptype
            stats["points"] += 1
            if p["is_adjusted"]:
                stats["adjusted_points"] += 1
            series.append(p)

    series.sort(key=lambda r: (r["area_slug"], r["property_type"], month_key(r["period"])))

    areas: dict[str, dict] = {}
    for rec in series:
        a = areas.setdefault(rec["area_slug"], {
            "slug": rec["area_slug"],
            "name": rec["area_slug"].replace("-", " ").title(),
            "property_types": set(),
            "first_period": rec["period"],
            "last_period": rec["period"],
        })
        a["property_types"].add(rec["property_type"])
        if month_key(rec["period"]) < month_key(a["first_period"]):
            a["first_period"] = rec["period"]
        if month_key(rec["period"]) > month_key(a["last_period"]):
            a["last_period"] = rec["period"]

    for slug, a in areas.items():
        a["property_types"] = sorted(a["property_types"])
        if slug in AGGREGATE_AREAS:
            a["board"], a["level"] = "both", "aggregate"
        elif slug in BOARD_AREAS:
            a["board"] = "GVR" if slug == "greater-vancouver" else "FVREB"
            a["level"] = "board"
        elif slug in GVR_AREAS:
            a["board"], a["level"] = "GVR", "municipality"
        elif slug in FVREB_AREAS:
            a["board"], a["level"] = "FVREB", "municipality"
        else:
            a["board"], a["level"] = "legacy", "neighbourhood"

    write_jsonl(OUT / "series.jsonl", series)
    (OUT / "areas.json").write_text(json.dumps(areas, indent=2, sort_keys=True))
    (OUT / "splices.json").write_text(json.dumps(splice_log, indent=2, sort_keys=True))

    periods = sorted({r["period"] for r in series}, key=month_key)
    by_level = defaultdict(int)
    for a in areas.values():
        by_level[a["level"]] += 1

    print(f"\nwrote {stats['points']:,} points -> data/out/series.jsonl")
    print(f"  areas    : {len(areas)}   levels: {dict(by_level)}")
    print(f"  series   : {stats['series']:,}  ({stats['series_with_splice']:,} needed splicing)")
    print(f"  periods  : {periods[0]} .. {periods[-1]}  ({len(periods)} months)")
    print(f"  adjusted : {stats['adjusted_points']:,} points rescaled onto the modern level")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
