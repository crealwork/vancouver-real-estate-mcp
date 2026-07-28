"""Recover REBGV stats packages from the Wayback Machine.

GVR's own site only serves packages back to 2018-12, which leaves a hole in
the neighbourhood-level record from 2011-10. The board's earlier packages were
archived though, under a long tail of naming conventions:

    201209-REBGV-Stats-Package-for-Media.pdf
    201212_REBGVStatsPackage.pdf
    2015-08-REBGV-Stats-Package.pdf
    2018-Dec-stats-pkg.pdf
    1. REBGV Stats Pkg January 2017.pdf

Dating them is the tricky part. The filename is the reliable signal, but a
few name two months ("2017-01-March-Stats--Package.pdf"), so those are
disambiguated against the document. Reading the document *first* is a trap:
every package compares against the same month one year earlier and mentions
that prior year about as often, so a frequency-based read lands a year early
on nearly every file — silently, and consistently enough to look correct.

Writes data/out/wayback_pdf_index.json: {"YYYY-MM": wayback_url}.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from common import OUT, RAW, UA

CDX = "http://web.archive.org/cdx/search/cdx"
HOSTS = ["rebgv.org/*", "www.rebgv.org/*", "members.rebgv.org/*", "members.gvrealtors.ca/*"]
NAME_RE = re.compile(r"stat|pkg|package", re.I)
# Skip the ones that are clearly not the monthly residential package.
EXCLUDE_RE = re.compile(r"commercial|agm|forms|consultation|bcrea|q[1-4]", re.I)

MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june",
         "july", "august", "september", "october", "november", "december"]
    )
}
MONTHS.update({m[:3]: i for m, i in MONTHS.items()})
MONTHS["sept"] = 9

PERIOD_IN_DOC = re.compile(
    r"(?:home\s+price\s+index|residential\s+market|market\s+report)[^\n]{0,60}?\n?\s*"
    r"(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?\s+(\d{4})",
    re.I,
)
ANY_MONTH_YEAR = re.compile(
    r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?\s+(\d{4})\b", re.I
)


def cdx_rows(url_pattern: str) -> list[list[str]]:
    params = urllib.parse.urlencode({
        "url": url_pattern,
        "output": "json",
        "collapse": "urlkey",
        "filter": "mimetype:application/pdf",
        "limit": "3000",
    })
    req = urllib.request.Request(f"{CDX}?{params}", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 - the CDX API is flaky
        print(f"  ! CDX failed for {url_pattern}: {exc}", file=sys.stderr)
        return []
    return data[1:] if data else []


def candidates() -> dict[str, str]:
    """-> {wayback_url: original_url}, deduped by filename."""
    seen: dict[str, str] = {}
    for host in HOSTS:
        for row in cdx_rows(host):
            timestamp, original = row[1], row[2]
            name = original.split("?")[0].rsplit("/", 1)[-1]
            if not NAME_RE.search(name) or EXCLUDE_RE.search(name):
                continue
            if name in seen:
                continue
            seen[name] = f"https://web.archive.org/web/{timestamp}id_/{original}"
    return {v: k for k, v in seen.items()}


MON_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
FILENAME_PATTERNS = [
    re.compile(r"(?<!\d)(20\d{2})[-_ ]?(0[1-9]|1[0-2])(?!\d)"),          # 201209 / 2015-08
    re.compile(rf"({MON_ALT})[-_. ]+(20\d{{2}})", re.I),                   # August_2013
    re.compile(rf"(20\d{{2}})[-_. ]+({MON_ALT})", re.I),                   # 2018-Dec
]


def periods_from_name(name: str) -> set[str]:
    """Every (year, month) the filename could be claiming."""
    out: set[str] = set()
    text = urllib.parse.unquote(name)
    for i, pat in enumerate(FILENAME_PATTERNS):
        for a, b in pat.findall(text):
            if i == 0:
                yr, mo = int(a), int(b)
            elif i == 1:
                mo, yr = MONTHS.get(a.lower(), 0), int(b)
            else:
                yr, mo = int(a), MONTHS.get(b.lower(), 0)
            if mo and 1990 <= yr <= 2100:
                out.add(f"{yr:04d}-{mo:02d}")
    return out


def periods_from_doc(pdf_path) -> set[str]:
    """Every month/year mentioned near the front of the document."""
    out = subprocess.run(
        ["pdftotext", "-layout", "-f", "1", "-l", "6", str(pdf_path), "-"],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        return set()
    found = set()
    for mo, yr in ANY_MONTH_YEAR.findall(out.stdout[:8000]):
        m = MONTHS.get(mo.lower())
        if m and 1990 <= int(yr) <= 2100:
            found.add(f"{int(yr):04d}-{m:02d}")
    return found


def resolve_period(pdf_path, name: str) -> tuple[str | None, str]:
    """Date a package from its filename, checked against its contents.

    The filename is the reliable signal — a package called
    REBGV_Stats_Package_August_2013 is August 2013. Reading the document
    instead gets this wrong in a specific, silent way: every package compares
    against the same month a year earlier, and that prior year is mentioned
    just as often, so a frequency-based read lands one year early on nearly
    every file. The document is therefore used only to disambiguate filenames
    that name two different months.
    """
    from_name = periods_from_name(name)
    if len(from_name) == 1:
        return next(iter(from_name)), "filename"

    from_doc = periods_from_doc(pdf_path)
    if from_name:
        both = from_name & from_doc
        if len(both) == 1:
            return next(iter(both)), "filename+document"
        # Ambiguous filename: the package is the latest month it names.
        return max(from_name), "filename (latest of several)"
    if from_doc:
        return max(from_doc), "document only"
    return None, "undated"


def period_of(pdf_path) -> str | None:
    out = subprocess.run(
        ["pdftotext", "-layout", "-f", "1", "-l", "12", str(pdf_path), "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        return None
    text = out.stdout

    m = PERIOD_IN_DOC.search(text)
    if not m:
        # Fall back to the most common month/year mentioned up front.
        found = ANY_MONTH_YEAR.findall(text[:4000])
        if not found:
            return None
        m = None
        counts: dict[tuple[str, str], int] = {}
        for mo, yr in found:
            counts[(mo.lower(), yr)] = counts.get((mo.lower(), yr), 0) + 1
        (mo, yr), _ = max(counts.items(), key=lambda kv: kv[1])
    else:
        mo, yr = m.group(1).lower(), m.group(2)

    month = MONTHS.get(mo[:3] if len(mo) > 3 else mo) or MONTHS.get(mo)
    if not month or not (1990 <= int(yr) <= 2100):
        return None
    return f"{int(yr):04d}-{month:02d}"


def main() -> int:
    pdf_dir = RAW / "wayback_pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    found = candidates()
    print(f"candidate archived packages: {len(found)}")

    def grab(item):
        url, name = item
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", urllib.parse.unquote(name))[:120]
        dest = pdf_dir / safe
        if not (dest.exists() and dest.stat().st_size > 10_000):
            body = None
            for attempt in range(3):
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                try:
                    with urllib.request.urlopen(req, timeout=300) as resp:
                        body = resp.read()
                    break
                except Exception:  # noqa: BLE001 - the archive rate-limits
                    if attempt == 2:
                        return None
                    time.sleep(4 * (attempt + 1))
            if body is None:
                return None
            if len(body) < 10_000 or not body[:5].startswith(b"%PDF"):
                return None
            dest.write_bytes(body)
        period, how = resolve_period(dest, name)
        return (period, url, dest.name, how) if period else None

    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for r in pool.map(grab, list(found.items())):
            if r:
                results.append(r)
                print(f"  {r[0]}  {r[2][:58]:58} [{r[3]}]")

    index: dict[str, str] = {}
    for period, url, _, _how in sorted(results):
        index.setdefault(period, url)

    path = OUT / "wayback_pdf_index.json"
    path.write_text(json.dumps(dict(sorted(index.items())), indent=2))

    periods = sorted(index)
    print(f"\ndated {len(results)} archived packages -> {len(index)} distinct months")
    if periods:
        print(f"  range: {periods[0]} .. {periods[-1]}")
        in_gap = [p for p in periods if "2011-10" <= p <= "2018-11"]
        print(f"  inside the 2011-10..2018-11 gap: {len(in_gap)}")
    print(f"  wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
