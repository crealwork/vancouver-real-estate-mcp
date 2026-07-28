"""Discover GVR (formerly REBGV) monthly stats-package PDF URLs.

gvrealtors.ca returns 403 to non-browser clients, so there is no archive
index to scrape. The PDFs themselves are served fine — only the naming is
inconsistent (Dec-2024, January-2026, April-2026, November-2025 all exist).
So we probe the known URL shapes per month and record what answers.

Writes data/out/gvr_pdf_index.json: {"YYYY-MM": url}.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from common import OUT, UA

MONTHS_FULL = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
MONTHS_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# The boards are not consistent: Sept-2024 and June/July (full) both ship
# alongside the 3-letter form, and one month was reissued as "-v2".
MONTHS_ALT = {9: ["Sept"], 6: ["June"], 7: ["July"]}


def name_variants(month: int) -> list[str]:
    out = [MONTHS_FULL[month - 1], MONTHS_ABBR[month - 1]]
    out += MONTHS_ALT.get(month, [])
    seen, uniq = set(), []
    for n in out:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq


# Ordered by how recently each shape has been seen in the wild.
TEMPLATES = [
    "https://members.gvrealtors.ca/news/GVR-Stats-Package-{m}-{year}.pdf",
    "https://members.gvrealtors.ca/news/GVR-Stats-Package-{m}-{year}-v2.pdf",
    "https://membernews.gvrealtors.ca/content/dam/rebgv-blog/PDFs/REBGV-Stats-Pkg-{m}-{year}.pdf",
    "https://members.gvrealtors.ca/news/REBGV-Stats-Pkg-{m}-{year}.pdf",
    "https://www.rebgv.org/content/dam/rebgv-blog/PDFs/REBGV-Stats-Pkg-{m}-{year}.pdf",
]


def head_ok(url: str, timeout: int = 20) -> bool:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            return resp.status == 200 and "pdf" in ctype.lower()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return False


def probe_month(year: int, month: int):
    for tpl in TEMPLATES:
        for name in name_variants(month):
            url = tpl.format(m=name, year=year)
            if head_ok(url):
                return f"{year:04d}-{month:02d}", url
    return f"{year:04d}-{month:02d}", None


def main() -> int:
    start_year = int(sys.argv[1]) if len(sys.argv) > 1 else 2011
    end_year = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
    targets = [(y, m) for y in range(start_year, end_year + 1) for m in range(1, 13)]

    found: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for period, url in pool.map(lambda t: probe_month(*t), targets):
            if url:
                found[period] = url
                print(f"  {period}  {url.rsplit('/', 1)[-1]}")

    path = OUT / "gvr_pdf_index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(found.items())), indent=2))

    periods = sorted(found)
    print(f"\nfound {len(found)} GVR stats packages -> {path}")
    if periods:
        print(f"  range: {periods[0]} .. {periods[-1]}")
        missing = [
            f"{y:04d}-{m:02d}"
            for y in range(int(periods[0][:4]), int(periods[-1][:4]) + 1)
            for m in range(1, 13)
            if f"{y:04d}-{m:02d}" not in found
            and periods[0] <= f"{y:04d}-{m:02d}" <= periods[-1]
        ]
        print(f"  gaps in range: {len(missing)}" + (f" e.g. {missing[:6]}" if missing else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
