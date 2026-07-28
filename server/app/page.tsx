import { listAreas, meta } from "@/lib/db";
import { KeyForm } from "./key-form";

export const dynamic = "force-static";

export default function Home() {
  const m = meta();
  const areas = listAreas();
  const municipalities = areas.filter((a) => a.level === "municipality");
  const deep = areas.filter((a) => a.first_period <= "1995-01").length;

  return (
    <main>
      <style>{css}</style>

      <header className="hero">
        <p className="eyebrow">Model Context Protocol server</p>
        <h1>
          Vancouver real estate history,
          <br />
          wired into your AI agent.
        </h1>
        <p className="lede">
          Every monthly benchmark price the Greater Vancouver and Fraser Valley
          boards have published, from {m.first_period?.slice(0, 4)} to today.
          Connect it once and ask your agent anything — what a Kitsilano condo
          cost in 1998, how far detached homes fell after 2016, which
          municipality has grown fastest since the pandemic.
        </p>
      </header>

      <section className="stats">
        <div>
          <strong>{Number(m.point_count).toLocaleString("en-CA")}</strong>
          <span>monthly data points</span>
        </div>
        <div>
          <strong>{m.area_count}</strong>
          <span>areas, down to neighbourhood</span>
        </div>
        <div>
          <strong>
            {m.first_period} — {m.last_period}
          </strong>
          <span>35 years of history</span>
        </div>
        <div>
          <strong>{deep}</strong>
          <span>areas with data back to 1991</span>
        </div>
      </section>

      <section className="panel">
        <h2>Get a free key</h2>
        <p>
          Keys are free. We ask for an email so we know who is using the server.
        </p>
        <KeyForm />
      </section>

      <section className="panel">
        <h2>What your agent can ask</h2>
        <ul className="asks">
          <li>&ldquo;What did a detached house in Richmond cost in 2005 versus now?&rdquo;</li>
          <li>&ldquo;Which Metro Vancouver municipality fell the most after the 2016 peak?&rdquo;</li>
          <li>&ldquo;Show me Vancouver West apartment prices year by year since 1995.&rdquo;</li>
          <li>&ldquo;Compare Burnaby North, Coquitlam and Port Moody townhouses.&rdquo;</li>
          <li>&ldquo;What was the deepest drawdown in Fraser Valley history?&rdquo;</li>
        </ul>
      </section>

      <section className="panel">
        <h2>Tools</h2>
        <table>
          <tbody>
            {TOOLS.map(([name, desc]) => (
              <tr key={name}>
                <td>
                  <code>{name}</code>
                </td>
                <td>{desc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <h2>Coverage</h2>
        <p className="muted">
          {municipalities.length} municipalities plus {areas.length - municipalities.length}{" "}
          board, aggregate and neighbourhood areas.
        </p>
        <p className="slugs">{municipalities.map((a) => a.name).join(" · ")}</p>
      </section>

      <section className="panel">
        <h2>How the numbers are built</h2>
        <p>
          Prices are MLS&reg; HPI benchmark prices — the modelled price of a
          typical home of that type in that area, not an average of what sold.
        </p>
        <p>
          The boards have restated the index more than once, so figures
          published years ago do not line up with today&rsquo;s series. Rather
          than splicing them naively, every older segment is chain-linked onto
          the current level: recent data stands as published, and older data
          contributes its shape. Points that were rescaled are flagged, and the
          originally published figure travels with them.
        </p>
        <p className="muted">
          Sources: CREA MLS&reg; HPI archive; Greater Vancouver REALTORS&reg;
          monthly stats packages; Fraser Valley Real Estate Board monthly stats
          packages and HPIMLX historical database. All public data. This server
          carries aggregate statistics only — no listings, no individual
          transactions.
        </p>
      </section>

      <footer>
        <p className="muted">
          Not affiliated with GVR, FVREB or CREA. Figures are provided as-is for
          research; verify against the boards before relying on them for a
          transaction.
        </p>
      </footer>
    </main>
  );
}

const TOOLS: [string, string][] = [
  ["data_coverage", "What is in the dataset and how to read it"],
  ["list_areas", "Find area names and see coverage per area"],
  ["get_price", "Benchmark price for one area, type and month"],
  ["get_price_history", "Full monthly or annual series"],
  ["compare_periods", "Change, multiple and annualised rate between two months"],
  ["compare_areas", "Several areas side by side"],
  ["rank_areas", "Rank by price level or by growth over a window"],
  ["market_extremes", "All-time high and low, and the deepest fall"],
];

const css = `
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font: 16px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    background: #ffffff;
    color: #16181d;
  }
  main { max-width: 860px; margin: 0 auto; padding: 72px 24px 96px; }
  .eyebrow {
    text-transform: uppercase; letter-spacing: .12em; font-size: 12px;
    font-weight: 600; color: #6b7280; margin: 0 0 16px;
  }
  h1 { font-size: clamp(32px, 5vw, 46px); line-height: 1.12; letter-spacing: -.02em; margin: 0 0 20px; }
  .lede { font-size: 18px; color: #3f4650; max-width: 62ch; margin: 0; }
  .stats {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 20px; margin: 48px 0; padding: 28px 0;
    border-top: 1px solid #e5e7eb; border-bottom: 1px solid #e5e7eb;
  }
  .stats div { display: flex; flex-direction: column; gap: 4px; }
  .stats strong { font-size: 22px; letter-spacing: -.01em; }
  .stats span { font-size: 13px; color: #6b7280; }
  .panel { margin: 44px 0; }
  h2 { font-size: 20px; letter-spacing: -.01em; margin: 0 0 12px; }
  p { margin: 0 0 12px; }
  .muted { color: #6b7280; font-size: 14px; }
  .asks { margin: 0; padding-left: 20px; color: #3f4650; }
  .asks li { margin-bottom: 6px; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  td { padding: 9px 0; border-bottom: 1px solid #eef0f3; vertical-align: top; }
  td:first-child { width: 200px; }
  code {
    font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
    background: #f3f4f6; padding: 2px 6px; border-radius: 4px;
  }
  .slugs { font-size: 14px; color: #3f4650; line-height: 1.9; }
  footer { margin-top: 64px; padding-top: 24px; border-top: 1px solid #e5e7eb; }
  @media (prefers-color-scheme: dark) {
    body { background: #0d0f13; color: #e8eaed; }
    .lede, .asks, .slugs { color: #b3b8c2; }
    .muted, .eyebrow, .stats span { color: #8b919c; }
    .stats, footer { border-color: #23262d; }
    td { border-color: #1c1f25; }
    code { background: #1c1f25; }
  }
`;
