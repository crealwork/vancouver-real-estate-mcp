"""Pack the merged series into a read-only SQLite file the server ships with.

61k points is small enough to embed, which keeps the MCP server free of any
database dependency: no connection pool, no cold-start round trip, and the
data is versioned in git alongside the code that reads it.
"""

from __future__ import annotations

import json
import sqlite3

from build import canonical_slug
from common import OUT, month_key, read_jsonl

DB_PATH = OUT / "vanre.db"

SCHEMA = """
PRAGMA journal_mode = OFF;

CREATE TABLE area (
    slug            TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    board           TEXT,
    level           TEXT,
    first_period    TEXT,
    last_period     TEXT,
    property_types  TEXT
);

CREATE TABLE price (
    area_slug       TEXT NOT NULL,
    property_type   TEXT NOT NULL,
    period          TEXT NOT NULL,        -- 'YYYY-MM'
    month_index     INTEGER NOT NULL,     -- sortable
    benchmark_price REAL,
    hpi             REAL,
    sales           INTEGER,
    new_listings    INTEGER,
    active_listings INTEGER,
    median_price    REAL,
    mean_price      REAL,
    source          TEXT NOT NULL,
    is_adjusted     INTEGER NOT NULL,
    basis           TEXT NOT NULL,
    as_published    REAL,
    PRIMARY KEY (area_slug, property_type, period)
);

CREATE INDEX idx_price_lookup ON price (area_slug, property_type, month_index);
CREATE INDEX idx_price_period ON price (period, property_type);

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def main() -> int:
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)

    areas = json.loads((OUT / "areas.json").read_text())
    con.executemany(
        "INSERT INTO area VALUES (?,?,?,?,?,?,?)",
        [
            (
                a["slug"], a["name"], a["board"], a["level"],
                a["first_period"], a["last_period"], json.dumps(a["property_types"]),
            )
            for a in areas.values()
        ],
    )

    # Market activity is keyed the same way, so fold it in rather than
    # keeping a second table the server would have to join.
    activity: dict[tuple, dict] = {}
    act_path = OUT / "activity.jsonl"
    if act_path.exists():
        for r in read_jsonl(act_path):
            key = (canonical_slug(r["area_slug"]), r["property_type"], r["period"])
            activity.setdefault(key, {}).update(
                {k: v for k, v in r.items()
                 if k in ("sales", "new_listings", "active_listings", "median_price", "mean_price")
                 and v is not None}
            )

    rows = []
    matched = 0
    for r in read_jsonl(OUT / "series.jsonl"):
        key = (r["area_slug"], r["property_type"], r["period"])
        act = activity.get(key, {})
        if act:
            matched += 1
        rows.append((
            r["area_slug"], r["property_type"], r["period"], month_key(r["period"]),
            r["benchmark_price"], r.get("hpi"),
            act.get("sales", r.get("sales")),
            act.get("new_listings"),
            act.get("active_listings"),
            act.get("median_price", r.get("median_price")),
            act.get("mean_price", r.get("mean_price")),
            r["source"], 1 if r.get("is_adjusted") else 0, r.get("basis", "as_published"), r.get("as_published"),
        ))
    con.executemany("INSERT INTO price VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    print(f"  activity merged into {matched:,} of {len(rows):,} points")

    periods = con.execute("SELECT MIN(period), MAX(period) FROM price").fetchone()
    con.executemany(
        "INSERT INTO meta VALUES (?,?)",
        [
            ("first_period", periods[0]),
            ("last_period", periods[1]),
            ("area_count", str(len(areas))),
            ("point_count", str(len(rows))),
            ("sources", json.dumps([
                "CREA MLS(R) HPI archive",
                "Greater Vancouver REALTORS monthly stats packages",
                "Fraser Valley Real Estate Board monthly stats packages",
                "FVREB HPIMLX historical database",
            ])),
        ],
    )

    con.commit()
    con.execute("VACUUM")
    con.close()

    size_mb = DB_PATH.stat().st_size / 1_048_576
    print(f"wrote {DB_PATH}  ({size_mb:.1f} MB)")
    print(f"  areas  : {len(areas)}")
    print(f"  points : {len(rows):,}")
    print(f"  range  : {periods[0]} .. {periods[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
