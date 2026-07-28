"""Sanity checks on the merged series before it goes anywhere near the server."""

from __future__ import annotations

import json
from collections import defaultdict

from common import OUT, month_key, read_jsonl

# Figures published by GVR/FVREB that we can check ourselves.
KNOWN = [
    # (area, type, period, benchmark, source of the claim)
    ("greater-vancouver", "composite", "2026-06", 1_099_100, "GVR June 2026 release"),
    ("greater-vancouver", "detached", "2026-06", 1_842_900, "GVR June 2026 release"),
    ("greater-vancouver", "apartment", "2026-06", 695_200, "GVR June 2026 release"),
    ("greater-vancouver", "townhouse", "2026-06", 1_046_200, "GVR June 2026 release"),
    ("greater-vancouver", "composite", "2026-04", 1_098_000, "GVR April 2026 package"),
    ("greater-vancouver", "detached", "2026-04", 1_840_700, "GVR April 2026 package"),
    ("fraser-valley", "composite", "2026-04", 899_200, "FVREB April 2026 package"),
    ("fraser-valley", "detached", "2026-04", 1_374_800, "FVREB April 2026 package"),
    ("lower-mainland", "composite", "2026-04", 1_031_500, "both April 2026 packages"),
    ("richmond", "composite", "2026-04", 1_047_200, "GVR April 2026 package"),
    ("vancouver-west", "composite", "2026-04", 1_225_700, "GVR April 2026 package"),
    ("abbotsford", "detached", "2026-04", 1_186_600, "FVREB April 2026 package"),
]

JUMP_LIMIT = 0.20


def main() -> int:
    series = list(read_jsonl(OUT / "series.jsonl"))
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for r in series:
        by_key[(r["area_slug"], r["property_type"])].append(r)
    for rows in by_key.values():
        rows.sort(key=lambda r: month_key(r["period"]))

    failures = 0

    print("=== published figures (latest data must be untouched) ===")
    for area, ptype, period, expected, note in KNOWN:
        rows = by_key.get((area, ptype), [])
        hit = next((r for r in rows if r["period"] == period), None)
        if hit is None:
            print(f"  MISS  {area}/{ptype} {period}: not in series  [{note}]")
            failures += 1
            continue
        got = hit["benchmark_price"]
        delta = abs(got - expected) / expected
        # CREA's archive and the boards' own releases disagree by a few tenths
        # of a percent on detached (CREA regenerates the file a few days after
        # the board publishes). Board-level series follow CREA for internal
        # consistency, so allow that much drift against a board release.
        ok = delta < 0.01
        flag = "ok  " if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"  {flag}  {area}/{ptype} {period}: {got:>12,.0f} vs {expected:>12,.0f} "
              f"({delta*100:.2f}%)  [{note}]")

    print("\n=== continuity: month-over-month jumps above 20% ===")
    jumps = []
    for (area, ptype), rows in by_key.items():
        for a, b in zip(rows, rows[1:]):
            gap = month_key(b["period"]) - month_key(a["period"])
            if gap != 1 or not a["benchmark_price"]:
                continue
            rate = b["benchmark_price"] / a["benchmark_price"] - 1
            if abs(rate) > JUMP_LIMIT:
                jumps.append((abs(rate), area, ptype, a["period"], b["period"], rate))
    jumps.sort(reverse=True)
    if not jumps:
        print("  none")
    else:
        failures += len(jumps)
        for _, area, ptype, p0, p1, rate in jumps[:15]:
            print(f"  FAIL  {area}/{ptype} {p0}->{p1}: {rate*100:+.1f}%")
        print(f"  ({len(jumps)} total)")

    print("\n=== coverage ===")
    areas = json.loads((OUT / "areas.json").read_text())
    depth = sorted(areas.values(), key=lambda a: month_key(a["first_period"]))
    print(f"  areas: {len(areas)}   series: {len(by_key)}   points: {len(series):,}")
    print("  deepest history:")
    for a in depth[:5]:
        print(f"    {a['slug']:38} {a['first_period']} .. {a['last_period']}  {a['level']}")
    print("  shallowest history:")
    for a in depth[-3:]:
        print(f"    {a['slug']:38} {a['first_period']} .. {a['last_period']}  {a['level']}")

    print("\n=== spot check: Greater Vancouver detached across the cycles ===")
    rows = {r["period"]: r for r in by_key[("greater-vancouver", "detached")]}
    for period in ["1991-06", "1995-01", "2000-01", "2005-01", "2008-05", "2009-01",
                   "2016-08", "2018-06", "2020-04", "2022-04", "2023-01", "2026-06"]:
        r = rows.get(period)
        if r:
            tag = " (rescaled)" if r["is_adjusted"] else ""
            print(f"  {period}  ${r['benchmark_price']:>12,.0f}  [{r['source']}]{tag}")

    print(f"\n{'PASS' if failures == 0 else f'{failures} PROBLEMS'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
