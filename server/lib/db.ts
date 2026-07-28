import path from "node:path";
// Node's built-in SQLite (stable since Node 24, which is Vercel's default).
// Using it instead of better-sqlite3 keeps the deployment free of any native
// module to compile.
import { DatabaseSync } from "node:sqlite";

export type Area = {
  slug: string;
  name: string;
  board: string | null;
  level: string | null;
  first_period: string;
  last_period: string;
  property_types: string;
};

export type PricePoint = {
  area_slug: string;
  property_type: string;
  period: string;
  month_index: number;
  benchmark_price: number | null;
  hpi: number | null;
  sales: number | null;
  median_price: number | null;
  mean_price: number | null;
  source: string;
  is_adjusted: number;
  /** as_published | chain_linked | bridged */
  basis: string;
  as_published: number | null;
};

let db: DatabaseSync | null = null;

export function getDb(): DatabaseSync {
  if (!db) {
    // Bundled with the deployment — read-only, no external database.
    db = new DatabaseSync(path.join(process.cwd(), "data", "vanre.db"), {
      readOnly: true,
    });
  }
  return db;
}

export function monthIndex(period: string): number {
  const [y, m] = period.split("-").map(Number);
  return y * 12 + m - 1;
}

export function periodFromIndex(idx: number): string {
  const y = Math.floor(idx / 12);
  const m = (idx % 12) + 1;
  return `${String(y).padStart(4, "0")}-${String(m).padStart(2, "0")}`;
}

export const PROPERTY_TYPES = [
  "composite",
  "detached",
  "townhouse",
  "apartment",
  "detached_acreage",
  "detached_one_storey",
  "detached_two_storey",
] as const;

/** Resolve a user-supplied area name onto a slug, tolerantly. */
export function resolveArea(input: string): Area | null {
  const d = getDb();
  const raw = input.trim().toLowerCase();
  const slug = raw.replace(/&/g, " and ").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

  const exact = d.prepare("SELECT * FROM area WHERE slug = ?").get(slug) as Area | undefined;
  if (exact) return exact;

  // Try common shorthands people actually type.
  const candidates = d
    .prepare("SELECT * FROM area WHERE slug LIKE ? ORDER BY LENGTH(slug) ASC LIMIT 1")
    .get(`${slug}%`) as Area | undefined;
  if (candidates) return candidates;

  const contains = d
    .prepare("SELECT * FROM area WHERE slug LIKE ? ORDER BY LENGTH(slug) ASC LIMIT 1")
    .get(`%${slug}%`) as Area | undefined;
  return contains ?? null;
}

export function listAreas(filter?: {
  board?: string;
  level?: string;
  since?: string;
}): Area[] {
  const d = getDb();
  const where: string[] = [];
  const args: (string | number)[] = [];
  if (filter?.board) {
    where.push("board = ?");
    args.push(filter.board);
  }
  if (filter?.level) {
    where.push("level = ?");
    args.push(filter.level);
  }
  if (filter?.since) {
    where.push("first_period <= ?");
    args.push(filter.since);
  }
  const sql =
    "SELECT * FROM area" +
    (where.length ? ` WHERE ${where.join(" AND ")}` : "") +
    " ORDER BY level, slug";
  return d.prepare(sql).all(...args) as Area[];
}

export function getSeries(
  areaSlug: string,
  propertyType: string,
  from?: string,
  to?: string,
): PricePoint[] {
  const d = getDb();
  const where = ["area_slug = ?", "property_type = ?"];
  const args: (string | number)[] = [areaSlug, propertyType];
  if (from) {
    where.push("month_index >= ?");
    args.push(monthIndex(from));
  }
  if (to) {
    where.push("month_index <= ?");
    args.push(monthIndex(to));
  }
  return d
    .prepare(`SELECT * FROM price WHERE ${where.join(" AND ")} ORDER BY month_index`)
    .all(...args) as PricePoint[];
}

export function getPoint(
  areaSlug: string,
  propertyType: string,
  period: string,
): PricePoint | null {
  const d = getDb();
  return (
    (d
      .prepare(
        "SELECT * FROM price WHERE area_slug = ? AND property_type = ? AND period = ?",
      )
      .get(areaSlug, propertyType, period) as PricePoint | undefined) ?? null
  );
}

/**
 * Nearest available point at or before `period`, but only within
 * `maxBackMonths`. The bound matters: several areas have multi-year holes
 * (GVR neighbourhood data is missing 2011-10..2018-11), and an unbounded
 * lookup silently answers a question about 2016 with a 2011 figure, which
 * then propagates into rankings as if it were a like-for-like comparison.
 */
export function getPointNear(
  areaSlug: string,
  propertyType: string,
  period: string,
  maxBackMonths = 3,
): PricePoint | null {
  const d = getDb();
  const target = monthIndex(period);
  const row = d
    .prepare(
      `SELECT * FROM price WHERE area_slug = ? AND property_type = ?
         AND month_index <= ? AND month_index >= ?
       ORDER BY month_index DESC LIMIT 1`,
    )
    .get(areaSlug, propertyType, target, target - maxBackMonths) as
    | PricePoint
    | undefined;
  return row ?? null;
}

export function meta(): Record<string, string> {
  const d = getDb();
  const rows = d.prepare("SELECT key, value FROM meta").all() as {
    key: string;
    value: string;
  }[];
  return Object.fromEntries(rows.map((r) => [r.key, r.value]));
}
