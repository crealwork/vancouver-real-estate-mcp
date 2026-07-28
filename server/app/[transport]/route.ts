import { createMcpHandler } from "mcp-handler";
import { z } from "zod";

import { keyFromRequest, verifyKey } from "@/lib/auth";
import {
  PROPERTY_TYPES,
  getDb,
  getSeries,
  listAreas,
  meta,
  monthIndex,
  resolveArea,
} from "@/lib/db";
import {
  annualise,
  change,
  extremes,
  fmtMoney,
  fmtPct,
  sample,
} from "@/lib/analysis";

const PropertyType = z
  .enum(PROPERTY_TYPES)
  .default("composite")
  .describe(
    "Property type. 'composite' blends all types and is the right default for " +
      "general questions about 'house prices'.",
  );

const Period = z
  .string()
  .regex(/^\d{4}-\d{2}$/, "use YYYY-MM")
  .describe("Month as YYYY-MM, e.g. 2016-08.");

function mark(basis: string): string {
  return basis === "bridged" ? " +" : basis === "chain_linked" ? " *" : "";
}

function legend(bases: string[]): string {
  const out: string[] = [];
  if (bases.includes("chain_linked"))
    out.push("* chain-linked onto the current index level (see data_coverage).");
  if (bases.includes("bridged"))
    out.push("+ estimated across a hole in the published record (see data_coverage).");
  return out.length ? "\n" + out.join("\n") : "";
}

function text(body: string) {
  return { content: [{ type: "text" as const, text: body }] };
}

function areaOrError(input: string) {
  const area = resolveArea(input);
  if (!area) {
    const near = listAreas()
      .map((a) => a.slug)
      .filter((s) => s.includes(input.toLowerCase().split(/\s+/)[0] ?? ""))
      .slice(0, 8);
    return {
      error: text(
        `No area matching "${input}". ` +
          (near.length ? `Did you mean: ${near.join(", ")}?` : "Call list_areas to see options."),
      ),
    };
  }
  return { area };
}

const handler = createMcpHandler(
  (server) => {
    server.tool(
      "data_coverage",
      "What this server holds: sources, date range, area count, and the caveats " +
        "that matter when quoting figures. Call this first if you are unsure what " +
        "can be answered.",
      {},
      async () => {
        const m = meta();
        const areas = listAreas();
        const byLevel = areas.reduce<Record<string, number>>((acc, a) => {
          acc[a.level ?? "?"] = (acc[a.level ?? "?"] ?? 0) + 1;
          return acc;
        }, {});
        return text(
          [
            `Metro Vancouver + Fraser Valley benchmark prices, ${m.first_period} to ${m.last_period}.`,
            `${m.point_count} monthly data points across ${m.area_count} areas.`,
            `Areas by level: ${Object.entries(byLevel)
              .map(([k, v]) => `${k} ${v}`)
              .join(", ")}.`,
            "",
            "Sources: " + (JSON.parse(m.sources ?? "[]") as string[]).join("; ") + ".",
            "",
            "How to read the numbers:",
            "- Prices are MLS(R) HPI benchmark prices: the modelled price of a 'typical'",
            "  home of that type in that area. They are not averages of what sold.",
            "- The boards have restated the index over the years, so figures published",
            "  long ago do not match today's series. Everything here is put on the",
            "  current level: recent data is as published, and older segments are",
            "  chain-linked onto it so the series is continuous. Points carrying a",
            "  rescale are flagged, with the originally published value alongside.",
            "- History before 2005 comes from FVREB's legacy HPIMLX database and is",
            "  chain-linked, so treat pre-2005 levels as consistent-basis estimates",
            "  rather than figures the boards published at the time.",
            "- Some areas have holes in the published record — GVR's neighbourhood",
            "  tables are missing 2011-10 to 2018-11, and GVR withdrew its January and",
            "  February 2025 HPI tables after finding a data-feed error. Where a hole",
            "  splits a series, the older part is placed using the wider market's growth",
            "  over the hole and marked '+' as estimated. Points marked '*' are",
            "  chain-linked; unmarked points are as published.",
            "- Board-level series follow CREA's archive, which can differ from a board's",
            "  own release by a few tenths of a percent on detached homes.",
          ].join("\n"),
        );
      },
    );

    server.tool(
      "list_areas",
      "List the areas with data, optionally filtered. Use this to find the exact " +
        "area name to pass to other tools, or to see which areas have deep history.",
      {
        board: z
          .enum(["GVR", "FVREB", "both", "legacy"])
          .optional()
          .describe("GVR = Greater Vancouver REALTORS, FVREB = Fraser Valley."),
        level: z
          .enum(["aggregate", "board", "municipality", "neighbourhood"])
          .optional()
          .describe("'municipality' is the usual level for questions about a city."),
        with_history_since: Period.optional().describe(
          "Only areas whose data starts on or before this month, e.g. 1995-01.",
        ),
      },
      async ({ board, level, with_history_since }) => {
        const areas = listAreas({ board, level, since: with_history_since });
        if (!areas.length) return text("No areas match that filter.");
        const lines = areas.map(
          (a) =>
            `${a.slug}  |  ${a.first_period}..${a.last_period}  |  ${a.level}  |  ` +
            `${(JSON.parse(a.property_types) as string[]).join(", ")}`,
        );
        return text(
          `${areas.length} areas (slug | coverage | level | property types):\n` +
            lines.join("\n"),
        );
      },
    );

    server.tool(
      "get_price",
      "Benchmark price for one area and property type in a given month. If that " +
        "exact month is missing, returns the closest earlier month and says so.",
      {
        area: z.string().describe("Area name or slug, e.g. 'Richmond' or 'vancouver-west'."),
        property_type: PropertyType,
        period: Period,
      },
      async ({ area, property_type, period }) => {
        const r = areaOrError(area);
        if (r.error) return r.error;
        const point = (await import("@/lib/db")).getPointNear(
          r.area.slug,
          property_type,
          period,
          6,
        );
        if (!point)
          return text(
            `No ${property_type} data for ${r.area.slug} within 6 months before ${period}. ` +
              `Coverage for this area runs ${r.area.first_period}..${r.area.last_period}, ` +
              `and some areas have interior gaps — call get_price_history to see what exists.`,
          );
        const exact = point.period === period;
        const extra =
          point.basis === "bridged"
            ? ` (estimated — the published record has a hole here; level inferred from the wider market)`
            : point.basis === "chain_linked"
              ? ` (rescaled onto the current index level; as published at the time: ${fmtMoney(point.as_published)})`
              : "";
        return text(
          `${r.area.name} — ${property_type}, ${point.period}${exact ? "" : ` (nearest to ${period})`}\n` +
            `Benchmark price: ${fmtMoney(point.benchmark_price)}${extra}\n` +
            `Source: ${point.source}`,
        );
      },
    );

    server.tool(
      "get_price_history",
      "Monthly benchmark price series for one area and property type. Use " +
        "granularity 'annual' for long spans so the reply stays readable.",
      {
        area: z.string().describe("Area name or slug."),
        property_type: PropertyType,
        from: Period.optional().describe("Defaults to the start of coverage."),
        to: Period.optional().describe("Defaults to the latest month."),
        granularity: z
          .enum(["monthly", "annual"])
          .default("monthly")
          .describe("'annual' keeps the last month of each year."),
      },
      async ({ area, property_type, from, to, granularity }) => {
        const r = areaOrError(area);
        if (r.error) return r.error;
        let rows = getSeries(r.area.slug, property_type, from, to);
        if (!rows.length)
          return text(
            `No ${property_type} data for ${r.area.slug} in that range. ` +
              `Coverage: ${r.area.first_period}..${r.area.last_period}, types: ${r.area.property_types}.`,
          );
        const actualFirst = rows[0].period;
        const gaps: string[] = [];
        for (let i = 1; i < rows.length; i++) {
          const step = rows[i].month_index - rows[i - 1].month_index;
          if (step > 1) gaps.push(`${rows[i - 1].period}..${rows[i].period}`);
        }

        if (granularity === "annual") rows = annualise(rows);
        rows = sample(rows, 300);

        const lines = rows.map((p) => {
          const flag = p.basis === "bridged" ? " +" : p.basis === "chain_linked" ? " *" : "";
          return `${p.period}  ${fmtMoney(p.benchmark_price)}${flag}`;
        });
        const anyLinked = rows.some((p) => p.basis === "chain_linked");
        const anyBridged = rows.some((p) => p.basis === "bridged");
        const notes: string[] = [];
        if (from && actualFirst > from)
          notes.push(
            `Requested from ${from}, but ${property_type} data for this area starts ${actualFirst}.`,
          );
        if (gaps.length)
          notes.push(`Missing months inside the range: ${gaps.join(", ")}.`);
        if (anyLinked)
          notes.push("* chain-linked onto the current index level (see data_coverage).");
        if (anyBridged)
          notes.push(
            "+ estimated: this area has a hole in its published record, so the level " +
              "was carried across it using the wider market's growth. Shape is the " +
              "area's own; level is inferred.",
          );

        return text(
          `${r.area.name} — ${property_type} benchmark price, ${rows[0].period}..${rows[rows.length - 1].period} (${rows.length} points)\n` +
            lines.join("\n") +
            (notes.length ? "\n\n" + notes.join("\n") : ""),
        );
      },
    );

    server.tool(
      "compare_periods",
      "How much prices moved between two months: total change, multiple, and " +
        "annualised rate. Answers 'how much has X gone up since Y'.",
      {
        area: z.string().describe("Area name or slug."),
        property_type: PropertyType,
        from: Period,
        to: Period.optional().describe("Defaults to the latest month available."),
      },
      async ({ area, property_type, from, to }) => {
        const r = areaOrError(area);
        if (r.error) return r.error;
        const end = to ?? r.area.last_period;
        const c = change(r.area.slug, property_type, from, end);
        if (!c)
          return text(
            `Not enough ${property_type} data for ${r.area.slug} between ${from} and ${end}. ` +
              `Coverage starts ${r.area.first_period}.`,
          );
        const years = (c.months / 12).toFixed(1);
        return text(
          [
            `${r.area.name} — ${property_type}`,
            `${c.from.period}: ${fmtMoney(c.from.benchmark_price)}${mark(c.from.basis)}`,
            `${c.to.period}: ${fmtMoney(c.to.benchmark_price)}${mark(c.to.basis)}`,
            "",
            `Change: ${fmtPct(c.changePct)} over ${c.months} months (${years} years)`,
            `Multiple: ${c.multiple.toFixed(2)}x`,
            `Annualised: ${fmtPct(c.cagrPct, 2)} per year`,
            legend([c.from.basis, c.to.basis]),
          ]
            .filter(Boolean)
            .join("\n"),
        );
      },
    );

    server.tool(
      "compare_areas",
      "Compare several areas at one month, ranked by price. Optionally include " +
        "each area's change since an earlier month.",
      {
        areas: z.array(z.string()).min(2).max(25).describe("Area names or slugs."),
        property_type: PropertyType,
        period: Period.optional().describe("Defaults to the latest month."),
        since: Period.optional().describe("If set, also show change from this month."),
      },
      async ({ areas, property_type, period, since }) => {
        const rows: string[] = [];
        const resolved = areas.map((a) => resolveArea(a));
        const missing = areas.filter((_, i) => !resolved[i]);
        const items: { name: string; price: number; line: string }[] = [];

        for (const area of resolved) {
          if (!area) continue;
          const end = period ?? area.last_period;
          const point = (await import("@/lib/db")).getPointNear(
            area.slug,
            property_type,
            end,
          );
          if (!point?.benchmark_price) continue;
          let line = `${area.name.padEnd(28)} ${fmtMoney(point.benchmark_price).padStart(12)}  (${point.period})`;
          if (since) {
            const c = change(area.slug, property_type, since, end);
            line += c ? `  ${fmtPct(c.changePct).padStart(8)} since ${since}` : "  n/a";
          }
          items.push({ name: area.name, price: point.benchmark_price, line });
        }
        if (!items.length) return text("None of those areas had data for that request.");
        items.sort((a, b) => b.price - a.price);
        rows.push(`${property_type} benchmark price${period ? `, ${period}` : ", latest"}:`);
        rows.push(...items.map((i) => i.line));
        if (missing.length) rows.push(`\nUnresolved: ${missing.join(", ")}`);
        return text(rows.join("\n"));
      },
    );

    server.tool(
      "rank_areas",
      "Rank areas by price level or by growth over a window. Answers 'which area " +
        "went up the most' or 'where is the cheapest'.",
      {
        property_type: PropertyType,
        metric: z
          .enum(["price", "change"])
          .default("price")
          .describe("'change' needs `since` and ranks by percentage growth."),
        period: Period.optional().describe("Month to evaluate. Defaults to latest."),
        since: Period.optional().describe("Start month, required when metric='change'."),
        level: z
          .enum(["aggregate", "board", "municipality", "neighbourhood"])
          .default("municipality")
          .describe("Which kind of area to rank."),
        order: z.enum(["desc", "asc"]).default("desc"),
        limit: z.number().int().min(1).max(50).default(15),
      },
      async ({ property_type, metric, period, since, level, order, limit }) => {
        if (metric === "change" && !since)
          return text("metric='change' needs `since` (e.g. since='2016-01').");
        const { getPointNear } = await import("@/lib/db");
        const areas = listAreas({ level });
        const scored: { name: string; value: number; detail: string }[] = [];
        const skipped: string[] = [];

        for (const a of areas) {
          const end = period ?? a.last_period;
          if (metric === "price") {
            const p = getPointNear(a.slug, property_type, end);
            if (p?.benchmark_price)
              scored.push({
                name: a.name,
                value: p.benchmark_price,
                detail: `${fmtMoney(p.benchmark_price)}  (${p.period})`,
              });
            else skipped.push(a.name);
          } else {
            const c = change(a.slug, property_type, since!, end);
            if (c)
              scored.push({
                name: a.name,
                value: c.changePct,
                detail: `${fmtPct(c.changePct).padStart(8)}   ${fmtMoney(c.from.benchmark_price)} → ${fmtMoney(c.to.benchmark_price)}  (${c.from.period}..${c.to.period})`,
              });
            else skipped.push(a.name);
          }
        }
        if (!scored.length)
          return text(
            `No ${level} areas have ${property_type} data covering that window. ` +
              "GVR neighbourhood coverage has a hole from 2011-10 to 2018-11 — " +
              "call list_areas to see each area's actual range.",
          );
        scored.sort((a, b) => (order === "desc" ? b.value - a.value : a.value - b.value));

        const head =
          metric === "price"
            ? `${property_type} benchmark price, ${level} level${period ? `, ${period}` : ", latest"}:`
            : `${property_type} price change since ${since}, ${level} level:`;
        return text(
          head +
            "\n" +
            scored
              .slice(0, limit)
              .map((s, i) => `${String(i + 1).padStart(2)}. ${s.name.padEnd(28)} ${s.detail}`)
              .join("\n") +
            (skipped.length
              ? `\n\nExcluded for lack of data in that window (${skipped.length}): ${skipped.join(", ")}`
              : ""),
        );
      },
    );

    server.tool(
      "market_extremes",
      "All-time high, all-time low, the deepest peak-to-trough fall, and where " +
        "prices sit today relative to the peak.",
      {
        area: z.string().describe("Area name or slug."),
        property_type: PropertyType,
      },
      async ({ area, property_type }) => {
        const r = areaOrError(area);
        if (r.error) return r.error;
        const e = extremes(r.area.slug, property_type);
        if (!e) return text(`Not enough ${property_type} data for ${r.area.slug}.`);
        const lines = [
          `${r.area.name} — ${property_type}, ${e.first.period}..${e.latest.period}`,
          "",
          `Latest    ${e.latest.period}  ${fmtMoney(e.latest.benchmark_price)}`,
          `All-time high  ${e.peak.period}  ${fmtMoney(e.peak.benchmark_price)}`,
          `All-time low   ${e.trough.period}  ${fmtMoney(e.trough.benchmark_price)}`,
          `Now vs peak: ${fmtPct(e.fromPeakPct)}`,
        ];
        if (e.maxDrawdown) {
          const d = e.maxDrawdown;
          lines.push(
            "",
            `Deepest fall: ${fmtPct(d.dropPct)} over ${d.months} months`,
            `  ${d.peak.period} ${fmtMoney(d.peak.benchmark_price)} → ${d.trough.period} ${fmtMoney(d.trough.benchmark_price)}`,
          );
        }
        return text(lines.join("\n"));
      },
    );
  },
  {},
  {
    basePath: "",
    maxDuration: 60,
    verboseLogs: false,
  },
);

async function authed(req: Request) {
  if (process.env.REQUIRE_API_KEY === "false") return handler(req);
  const claims = verifyKey(keyFromRequest(req));
  if (!claims) {
    return new Response(
      JSON.stringify({
        error: "unauthorized",
        message:
          "A free API key is required. Request one at https://" +
          (process.env.PUBLIC_HOST ?? "proof.getsundayable.com/vanre") +
          " and pass it as an Authorization: Bearer header.",
      }),
      { status: 401, headers: { "content-type": "application/json" } },
    );
  }
  return handler(req);
}

export { authed as GET, authed as POST, authed as DELETE };
