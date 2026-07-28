import {
  type PricePoint,
  getPointNear,
  getSeries,
  monthIndex,
  periodFromIndex,
} from "./db";

export function cagr(from: number, to: number, months: number): number {
  if (from <= 0 || months <= 0) return 0;
  return (Math.pow(to / from, 12 / months) - 1) * 100;
}

export function fmtMoney(v: number | null | undefined): string {
  if (v == null) return "n/a";
  return "$" + Math.round(v).toLocaleString("en-CA");
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "n/a";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

export type Change = {
  from: PricePoint;
  to: PricePoint;
  months: number;
  changePct: number;
  multiple: number;
  cagrPct: number;
};

export function change(
  areaSlug: string,
  propertyType: string,
  fromPeriod: string,
  toPeriod: string,
): Change | null {
  const a = getPointNear(areaSlug, propertyType, fromPeriod);
  const b = getPointNear(areaSlug, propertyType, toPeriod);
  if (!a || !b || !a.benchmark_price || !b.benchmark_price) return null;
  const months = b.month_index - a.month_index;
  return {
    from: a,
    to: b,
    months,
    changePct: (b.benchmark_price / a.benchmark_price - 1) * 100,
    multiple: b.benchmark_price / a.benchmark_price,
    cagrPct: cagr(a.benchmark_price, b.benchmark_price, months),
  };
}

export type Extremes = {
  peak: PricePoint;
  trough: PricePoint;
  latest: PricePoint;
  first: PricePoint;
  fromPeakPct: number;
  /** Largest peak-to-trough drawdown across the whole history. */
  maxDrawdown: { peak: PricePoint; trough: PricePoint; dropPct: number; months: number } | null;
};

export function extremes(areaSlug: string, propertyType: string): Extremes | null {
  const rows = getSeries(areaSlug, propertyType).filter((r) => r.benchmark_price);
  if (rows.length < 2) return null;

  let peak = rows[0];
  let trough = rows[0];
  for (const r of rows) {
    if (r.benchmark_price! > peak.benchmark_price!) peak = r;
    if (r.benchmark_price! < trough.benchmark_price!) trough = r;
  }

  let runningPeak = rows[0];
  let worst: Extremes["maxDrawdown"] = null;
  for (const r of rows) {
    if (r.benchmark_price! >= runningPeak.benchmark_price!) {
      runningPeak = r;
      continue;
    }
    const dropPct = (r.benchmark_price! / runningPeak.benchmark_price! - 1) * 100;
    if (!worst || dropPct < worst.dropPct) {
      worst = {
        peak: runningPeak,
        trough: r,
        dropPct,
        months: r.month_index - runningPeak.month_index,
      };
    }
  }

  const latest = rows[rows.length - 1];
  return {
    peak,
    trough,
    latest,
    first: rows[0],
    fromPeakPct: (latest.benchmark_price! / peak.benchmark_price! - 1) * 100,
    maxDrawdown: worst,
  };
}

/** Downsample a long series so a reply stays readable. */
export function sample(rows: PricePoint[], maxPoints: number): PricePoint[] {
  if (rows.length <= maxPoints) return rows;
  const step = Math.ceil(rows.length / maxPoints);
  const out = rows.filter((_, i) => i % step === 0);
  const last = rows[rows.length - 1];
  if (out[out.length - 1] !== last) out.push(last);
  return out;
}

export function annualise(rows: PricePoint[]): PricePoint[] {
  const byYear = new Map<string, PricePoint>();
  for (const r of rows) byYear.set(r.period.slice(0, 4), r);
  return [...byYear.values()];
}

export { monthIndex, periodFromIndex };

/**
 * The sales-to-active-listings ratio is what the boards themselves cite when
 * they call the market. Their published guidance: under 12% for a sustained
 * period tends to mean downward price pressure, over 20% upward.
 */
export function marketTone(ratioPct: number): string {
  if (ratioPct < 12) return "buyer's market (downward pressure)";
  if (ratioPct > 20) return "seller's market (upward pressure)";
  return "balanced";
}
