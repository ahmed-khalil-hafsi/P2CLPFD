"""
Render benchmarks/scaling.json as a self-contained HTML chart.

    python scripts/benchmark.py          # produces benchmarks/scaling.json
    python scripts/make_chart.py         # produces benchmarks/scaling.html

Kept separate from the benchmark so the chart can be redrawn without
re-running a sweep that takes half an hour.
"""

from __future__ import annotations

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_IN = os.path.join(REPO, "benchmarks", "scaling.json")
DEFAULT_OUT = os.path.join(REPO, "benchmarks", "scaling.html")

# Chart geometry, in SVG user units.
W, H = 560, 330
PAD_L, PAD_R, PAD_T, PAD_B = 62, 26, 20, 46


def _nice_axis(value: float, divisions: int = 4) -> tuple[float, float]:
    """
    Pick an axis maximum and step so every tick is a clean number.

    Rounding only the maximum is not enough — a max of 50 over 4
    divisions still prints 12.5. Choose the STEP from the 1/2/2.5/5
    family instead, then the max is step x divisions and every tick
    inherits the cleanliness.
    """
    if value <= 0:
        return 1.0, 0.25
    import math
    target = value / divisions
    exp = math.floor(math.log10(target))
    base = 10.0 ** exp
    for mult in (1, 2, 2.5, 5, 10):
        step = mult * base
        if step * divisions >= value:
            return step * divisions, step
    step = 10 * base
    return step * divisions, step


def _fmt(n: float) -> str:
    if n == 0:
        return "0"
    if n >= 1000:
        return f"{n:,.0f}"
    if n >= 10:
        return f"{n:.0f}"
    if n >= 1:
        return f"{n:.1f}"
    return f"{n:.2f}"


def _growth_exponent(points: list[tuple[float, float]]) -> float:
    """
    Fit y = a·x^k on log-log and return k.

    Quoting a measured exponent beats calling a curve "roughly quadratic"
    by eye — the reader can check whether 2.0 is really in the data.
    """
    import math
    pts = [(x, y) for x, y in points if x > 0 and y > 0]
    if len(pts) < 2:
        return float("nan")
    n = len(pts)
    lx = [math.log(x) for x, _ in pts]
    ly = [math.log(y) for _, y in pts]
    mx, my = sum(lx) / n, sum(ly) / n
    denom = sum((v - mx) ** 2 for v in lx)
    if denom == 0:
        return float("nan")
    return sum((lx[i] - mx) * (ly[i] - my) for i in range(n)) / denom


def build_plot(series: list[dict], x_label: str, y_label: str,
               series_var: str, plot_id: str) -> str:
    """
    A line chart with one or more series.

    Each series is {"name", "points", "slot"}. A single series carries no
    legend — the card heading already names it, and a one-swatch box just
    restates the title. Two or more always get one, because identity must
    never rest on colour alone.
    """
    series = [s for s in series if s["points"]]
    if not series:
        return '<p class="empty">No data for this sweep.</p>'

    xs = [p[0] for s in series for p in s["points"]]
    ys = [p[1] for s in series for p in s["points"]]
    x_max, _ = _nice_axis(max(xs))
    y_max, y_step = _nice_axis(max(ys))
    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B

    def px(x: float) -> float:
        return PAD_L + (x / x_max) * plot_w

    def py(y: float) -> float:
        return PAD_T + plot_h - (y / y_max) * plot_h

    # Gridlines: solid hairlines, one step off surface, recessive.
    grid, y_ticks = [], []
    for i in range(5):
        v = y_step * i
        y = py(v)
        grid.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" '
                    f'y2="{y:.1f}" class="grid"/>')
        y_ticks.append(f'<text x="{PAD_L - 10}" y="{y + 4:.1f}" '
                       f'class="tick tick-y">{_fmt(v)}</text>')

    # Ticks come from every series, so dedupe — otherwise two series that
    # share x positions stack labels on top of each other. Then drop any
    # label that would collide with the last one kept: an unreadable smear
    # of overlapping numbers is worse than a sparser axis.
    x_ticks = []
    last_x = None
    for x in sorted(set(xs)):
        pos = px(x)
        width = 7.0 * len(_fmt(x))          # rough advance at 11px
        if last_x is not None and pos - last_x < width:
            continue
        last_x = pos
        x_ticks.append(f'<text x="{pos:.1f}" y="{H - PAD_B + 20}" '
                       f'class="tick tick-x">{_fmt(x)}</text>')

    paths, dots, hits, end_labels = [], [], [], []
    for s_i in series:
        slot = s_i["slot"]
        pts = s_i["points"]
        paths.append(
            '<path d="' + " ".join(
                ("M" if i == 0 else "L") + f"{px(x):.1f},{py(y):.1f}"
                for i, (x, y) in enumerate(pts)
            ) + f'" class="line s{slot}"/>'
        )
        for x, y in pts:
            cx, cy = px(x), py(y)
            # 2px surface ring keeps the marker legible where lines cross.
            dots.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.5" '
                        f'class="dot s{slot}"/>')
            # Hit target far exceeds the 9px mark (interaction.md: ~24px).
            hits.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="13" class="hit" '
                f'tabindex="0" role="img" '
                f'data-x="{_fmt(x)}" data-y="{y:.3f}" data-var="{series_var}" '
                f'data-series="{s_i["name"]}" '
                f'aria-label="{s_i["name"]}, {_fmt(x)} {series_var}: '
                f'{y:.3f} seconds"/>'
            )

        # Direct-label the endpoint only — never a number on every point.
        lx, ly = pts[-1]
        anchor = "end" if px(lx) > W - PAD_R - 60 else "start"
        dx = -10 if anchor == "end" else 10
        end_labels.append(
            f'<text x="{px(lx) + dx:.1f}" y="{py(ly) - 12:.1f}" '
            f'class="end-label" text-anchor="{anchor}">{_fmt(ly)}s</text>'
        )

    legend = ""
    if len(series) > 1:
        chips = "".join(
            f'<span class="key"><span class="swatch s{s_i["slot"]}"></span>'
            f'{s_i["name"]}</span>' for s_i in series
        )
        legend = f'<div class="legend">{chips}</div>'

    return f"""<figure class="chart" id="{plot_id}">
  {legend}
  <svg viewBox="0 0 {W} {H}" role="img"
       aria-label="{y_label} against {x_label}" preserveAspectRatio="xMidYMid meet">
    {''.join(grid)}
    <line x1="{PAD_L}" y1="{PAD_T}" x2="{PAD_L}" y2="{H - PAD_B}" class="axis"/>
    <line x1="{PAD_L}" y1="{H - PAD_B}" x2="{W - PAD_R}" y2="{H - PAD_B}" class="axis"/>
    {''.join(y_ticks)}
    {''.join(x_ticks)}
    {''.join(paths)}
    {''.join(dots)}
    {''.join(end_labels)}
    <text class="axis-title-y" transform="translate(14,{PAD_T + plot_h / 2}) rotate(-90)">{y_label}</text>
    <text class="axis-title-x" x="{PAD_L + plot_w / 2}" y="{H - 6}">{x_label}</text>
    {''.join(hits)}
  </svg>
</figure>"""


def build_table(rows: list[tuple[str, str, str]], caption: str) -> str:
    body = "".join(
        f"<tr><td>{a}</td><td>{b}</td><td>{c}</td></tr>" for a, b, c in rows
    )
    return f"""<table>
  <caption>{caption}</caption>
  <thead><tr><th>Size</th><th>Solve time</th><th>Per unit</th></tr></thead>
  <tbody>{body}</tbody>
</table>"""


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IN
    out = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT

    with open(src) as fh:
        payload = json.load(fh)
    cfg = payload["config"]
    results = payload["results"]

    def ok(records):
        return [r for r in records if r.get("seconds") is not None]

    items = ok(results.get("items", []))
    demand = ok(results.get("demand", []))
    demand_grid = ok(results.get("demand_grid", []))
    coupled = ok(results.get("coupled", []))

    item_pts = [(r["items"], r["seconds"]) for r in items]
    demand_pts = [(r["demand"], r["seconds"]) for r in demand]
    grid_pts_all = [(r["demand"], r["seconds"]) for r in demand_grid]

    # Overlay the two demand series only where both have data. The grid
    # run reaches far higher quantities precisely because it stays flat;
    # plotting its full range would squash the free curve into the left
    # edge and hide the very divergence the chart exists to show. The
    # lede and the table carry what happens beyond.
    free_max = max((x for x, _ in demand_pts), default=0)
    grid_pts = [(x, y) for x, y in grid_pts_all if x <= free_max]

    # Headline numbers, computed rather than asserted.
    item_k = _growth_exponent(item_pts)
    demand_k = _growth_exponent(demand_pts)
    grid_k = _growth_exponent(grid_pts_all)

    if len(item_pts) >= 2:
        first, last = item_pts[0], item_pts[-1]
        ms_first = first[1] / first[0] * 1000
        ms_last = last[1] / last[0] * 1000
        item_verdict = (
            f"Per-item cost is flat at roughly {ms_last:.0f} ms — {ms_first:.0f} ms "
            f"at {first[0]:,.0f} items, {ms_last:.0f} ms at {last[0]:,.0f}. "
            f"Measured growth is x<sup>{item_k:.2f}</sup>, i.e. linear: doubling "
            f"the catalogue doubles the time and no worse, because nothing here "
            f"ties one item to another."
        )
    else:
        item_verdict = "Not enough data points."

    if len(demand_pts) >= 2:
        (x0, y0), (x1, y1) = demand_pts[0], demand_pts[-1]
        x_ratio = x1 / x0 if x0 else 0
        y_ratio = y1 / y0 if y0 else 0
        demand_verdict = (
            f"With quantities free, {x_ratio:.0f}× the demand costs "
            f"{y_ratio:.0f}× the time — measured growth x<sup>{demand_k:.2f}</sup>, "
            f"near-quadratic, because the quantity sets each variable's domain "
            f"and therefore the space the search must cover."
        )
        if grid_pts_all:
            gx = max(x for x, _ in grid_pts_all)
            gy = max(y for _, y in grid_pts_all)
            demand_verdict += (
                f" Restrict awards to a {cfg.get('share_increment', 5)}% grid and "
                f"the curve flattens: x<sup>{grid_k:.2f}</sup>, still "
                f"{gy:.2f}s at {gx:,.0f} units — {gx / x1:.0f}× further out than "
                f"the free run could reach at all."
            )
    else:
        demand_verdict = "Not enough data points."

    if grid_pts_all and demand_pts:
        gx = max(x for x, _ in grid_pts_all)
        gy = max(y for _, y in grid_pts_all)
        worst_free = max(y for _, y in demand_pts)
        grid_headline = (
            f"Restricting awards to a {cfg.get('share_increment', 5)}% grid removes "
            f"quantity from the problem altogether: {gy:.2f}s at {gx:,.0f} units, "
            f"against {worst_free:.0f}s at "
            f"{max(x for x, _ in demand_pts):,.0f} units without it."
        )
    else:
        grid_headline = ""

    timed_out = [r for r in results.get("items", []) if r.get("timed_out")]
    timeout_note = ""
    if timed_out:
        n = timed_out[0]["items"]
        timeout_note = (
            f'<p class="note">The sweep stopped at {n:,} items: that solve '
            f'passed the {cfg["timeout"]:.0f}s budget. Larger sizes can only '
            f'be slower, so they were not attempted.</p>'
        )

    coupled_section = ""
    coupled_all = results.get("coupled", [])
    coupled_timeouts = [r for r in coupled_all if r.get("timed_out")]

    if not coupled and coupled_timeouts:
        # Every coupled run blew the budget. That is the result, not a gap —
        # say it plainly rather than rendering an empty card.
        smallest = coupled_timeouts[0]
        matching = next((s for n, s in item_pts if n == smallest["items"]), None)
        against = (f", against {matching:.0f}s for the same items with no "
                   f"portfolio rule" if matching else "")
        coupled_section = f"""
  <section class="card">
    <h2>What one portfolio-wide rule costs</h2>
    <p class="lede">Adding a cap on any supplier's share of <em>total</em> volume
    ties every item into a single search — minimizing a sum couples everything
    the sum touches, so the per-item decomposition no longer applies.</p>
    <p class="hero">&gt; {smallest['timeout']:.0f}s</p>
    <p class="hero-label">at just {smallest['items']:,} items{against}. The sweep
    could not produce a curve because its very first point exceeded the budget.
    This is the case <code>decompose.pl</code> still cannot split, and it is the
    next thing worth fixing.</p>
    <div style="height:14px"></div>
  </section>"""
    elif coupled:
        cpts = [(r["items"], r["seconds"]) for r in coupled]
        biggest = cpts[-1]
        matching = next((s for n, s in item_pts if n == biggest[0]), None)
        compare = ""
        if matching:
            compare = (f" At {biggest[0]:,.0f} items it takes {biggest[1]:.1f}s "
                       f"against {matching:.1f}s decomposed.")
        coupled_section = f"""
  <section class="card">
    <h2>What one portfolio-wide rule costs</h2>
    <p class="lede">Adding a cap on any supplier's share of <em>total</em> volume
    ties every item into a single search. Minimizing a sum couples everything the
    sum touches, so the per-item decomposition no longer applies.{compare}</p>
    {build_plot([{"name": "coupled", "points": cpts, "slot": 2}],
                "items sourced", "solve time (seconds)", "items", "coupled")}
  </section>"""

    item_rows = [
        (f'{r["items"]:,}', f'{r["seconds"]:.2f}s',
         f'{r["seconds"] / r["items"] * 1000:.1f} ms/item') for r in items
    ]
    demand_rows = [
        (f'{r["demand"]:,} units', f'{r["seconds"]:.2f}s',
         f'{r["seconds"] / r["demand"] * 1000:.1f} ms/unit') for r in demand
    ]
    grid_rows = [
        (f'{r["demand"]:,} units', f'{r["seconds"]:.2f}s',
         f'{r["seconds"] / r["demand"] * 1000:.2f} ms/unit') for r in demand_grid
    ]
    grid_table = (build_table(grid_rows, f"Solve time on a "
                              f"{cfg.get('share_increment', 5)}% award grid, one item")
                  if grid_rows else "")

    html = f"""<style>
  .viz-root {{
    color-scheme: light;
    --surface-1: #fcfcfb;
    --plane: #f9f9f7;
    --text-primary: #0b0b0b;
    --text-secondary: #52514e;
    --text-muted: #898781;
    --grid: #e1e0d9;
    --axis: #c3c2b7;
    --border: rgba(11,11,11,0.10);
    --series-1: #2a78d6;
    --series-2: #eb6834;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) .viz-root {{
      color-scheme: dark;
      --surface-1: #1a1a19;
      --plane: #0d0d0d;
      --text-primary: #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted: #898781;
      --grid: #2c2c2a;
      --axis: #383835;
      --border: rgba(255,255,255,0.10);
      --series-1: #3987e5;
      --series-2: #d95926;
    }}
  }}
  :root[data-theme="dark"] .viz-root {{
    color-scheme: dark;
    --surface-1: #1a1a19;
    --plane: #0d0d0d;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted: #898781;
    --grid: #2c2c2a;
    --axis: #383835;
    --border: rgba(255,255,255,0.10);
    --series-1: #3987e5;
    --series-2: #d95926;
  }}

  .viz-root {{
    /* Two type roles: sans for prose, mono for every measured figure.
       The page is nothing but measurements, so the mono is subject
       matter rather than decoration — and digits align for free. */
    --sans: system-ui, -apple-system, "Segoe UI", sans-serif;
    --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
    background: var(--plane);
    color: var(--text-primary);
    font-family: var(--sans);
    line-height: 1.55;
    padding: 32px 20px 56px;
    min-height: 100vh;
  }}
  .wrap {{ max-width: 940px; margin: 0 auto; }}
  h1 {{ font-size: 1.6rem; font-weight: 600; margin: 0 0 6px;
        letter-spacing: -0.015em; text-wrap: balance; }}
  .sub {{ color: var(--text-secondary); margin: 0 0 28px; }}
  .card {{
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 22px 24px 10px;
    margin-bottom: 22px;
  }}
  .card h2 {{ font-size: 1.05rem; font-weight: 600; margin: 0 0 4px; }}
  .lede {{ color: var(--text-secondary); margin: 0 0 14px; font-size: 0.94rem; }}
  .hero {{ font-family: var(--mono); font-size: 2.1rem; font-weight: 600;
           letter-spacing: -0.03em; margin: 4px 0 6px; }}
  .hero-label {{ color: var(--text-secondary); font-size: 0.94rem; margin: 0; }}
  .note {{ color: var(--text-muted); font-size: 0.85rem; margin: 4px 0 14px; }}
  .chart {{ margin: 0 0 6px; }}
  .chart svg {{ width: 100%; height: auto; display: block; overflow: visible; }}

  .grid {{ stroke: var(--grid); stroke-width: 1; }}
  .axis {{ stroke: var(--axis); stroke-width: 1; }}
  .line {{ fill: none; stroke-width: 2;
           stroke-linejoin: round; stroke-linecap: round; }}
  .dot {{ stroke: var(--surface-1); stroke-width: 2; }}
  .line.s1 {{ stroke: var(--series-1); }}
  .line.s2 {{ stroke: var(--series-2); }}
  .dot.s1 {{ fill: var(--series-1); }}
  .dot.s2 {{ fill: var(--series-2); }}
  .legend {{ display: flex; gap: 18px; flex-wrap: wrap; margin: 0 0 8px 4px; }}
  .key {{ display: inline-flex; align-items: center; gap: 7px;
          color: var(--text-secondary); font-size: 0.85rem; }}
  .swatch {{ width: 16px; height: 2px; border-radius: 1px; flex: none; }}
  .swatch.s1 {{ background: var(--series-1); }}
  .swatch.s2 {{ background: var(--series-2); }}
  .hit {{ fill: transparent; cursor: crosshair; outline: none; }}
  .hit:focus-visible {{ stroke: var(--text-primary); stroke-width: 2; }}
  summary:focus-visible {{ outline: 2px solid var(--series-1); outline-offset: 2px;
                           border-radius: 4px; }}
  @media (prefers-reduced-motion: reduce) {{
    .tip {{ transition: none; }}
  }}
  .tick {{ fill: var(--text-muted); font-size: 10.5px; font-family: var(--mono);
           font-variant-numeric: tabular-nums; }}
  .tick-y {{ text-anchor: end; }}
  .tick-x {{ text-anchor: middle; }}
  .axis-title-x, .axis-title-y {{ fill: var(--text-secondary); font-size: 12px;
                                  text-anchor: middle; }}
  .end-label {{ fill: var(--text-primary); font-size: 12px; font-weight: 600;
                font-family: var(--mono); }}

  table {{ width: 100%; border-collapse: collapse; margin: 10px 0 18px;
           font-size: 0.88rem; }}
  caption {{ text-align: left; color: var(--text-secondary); padding-bottom: 8px;
             font-size: 0.88rem; }}
  th, td {{ text-align: right; padding: 6px 10px; border-bottom: 1px solid var(--border);
            font-family: var(--mono); font-variant-numeric: tabular-nums;
            font-size: 0.85rem; }}
  th:first-child, td:first-child {{ text-align: left; }}
  th {{ color: var(--text-secondary); font-weight: 600; font-family: var(--sans);
        font-size: 0.82rem; }}
  details {{ margin-top: 6px; }}
  summary {{ cursor: pointer; color: var(--text-secondary); font-size: 0.88rem;
             padding: 6px 0; }}
  .tip {{
    position: fixed; pointer-events: none; opacity: 0;
    background: var(--surface-1); color: var(--text-primary);
    border: 1px solid var(--border); border-radius: 8px;
    padding: 8px 11px; font-size: 0.85rem; z-index: 20;
    box-shadow: 0 4px 14px rgba(0,0,0,0.13); transition: opacity .1s;
  }}
  .tip b {{ font-size: 1.05rem; font-weight: 600; font-family: var(--mono); }}
  .tip span {{ color: var(--text-secondary); }}
  .method {{ color: var(--text-secondary); font-size: 0.9rem; }}
  .method code {{ background: var(--plane); padding: 1px 5px; border-radius: 4px;
                  font-size: 0.85em; }}
  .table-scroll {{ overflow-x: auto; }}
</style>

<div class="viz-root">
<div class="wrap">
  <h1>P2CLPFD scaling</h1>
  <p class="sub">{cfg['suppliers']} suppliers, quad sourcing,
  {cfg['min_share_pct']}% minimum share per supplier. Everything else held fixed.</p>

  <section class="card">
    <h2>Where the time goes</h2>
    <p class="hero">quantity, not catalogue size</p>
    <p class="hero-label">Sourcing ten times as many items costs ten times the
    time — that scales fine. Ordering ten times the <em>quantity</em> of one item
    costs far more than ten times, and that is the ceiling you hit first.
    {grid_headline}</p>
    <div style="height:14px"></div>
  </section>

  <section class="card">
    <h2>Time against number of items</h2>
    <p class="lede">{item_verdict}</p>
    {build_plot([{"name": "items", "points": item_pts, "slot": 1}],
                "items sourced", "solve time (seconds)", "items", "items")}
    {timeout_note}
    <details><summary>Table view</summary>
      <div class="table-scroll">
      {build_table(item_rows, f"Solve time by item count, {cfg['fixed_demand']} units per item")}
      </div>
    </details>
  </section>

  <section class="card">
    <h2>Time against demand per item</h2>
    <p class="lede">{demand_verdict}</p>
    {build_plot([
        {"name": "free quantities", "points": demand_pts, "slot": 1},
        {"name": f"{cfg.get('share_increment', 5)}% award grid", "points": grid_pts, "slot": 2},
     ], "units demanded (single item)", "solve time (seconds)", "units", "demand")}
    <details><summary>Table view</summary>
      <div class="table-scroll">
      {build_table(demand_rows, "Solve time by demand, one item, free quantities")}
      {grid_table}
      </div>
    </details>
  </section>
{coupled_section}

  <section class="card">
    <h2>Method</h2>
    <p class="method">Each point is one <code>solve()</code> on generated data, timed
    in a fresh process so a run that overruns can be killed — CLP(FD) labeling does
    not reliably yield to Prolog's own timeout. Prices rotate per item so the optimum
    is a real choice rather than a tie. Capacity is set to demand, so it never binds.
    Timeout {cfg['timeout']:.0f}s per solve.</p>
    <p class="method">Reproduce with <code>python scripts/benchmark.py</code>, then
    <code>python scripts/make_chart.py</code>.</p>
  </section>
</div>
</div>

<div class="tip" id="tip"></div>
<script>
(function () {{
  var tip = document.getElementById('tip');
  function show(el) {{
    // textContent, never innerHTML concatenation — values are data.
    tip.textContent = '';
    var b = document.createElement('b');
    b.textContent = Number(el.dataset.y).toFixed(2) + 's';
    var s = document.createElement('span');
    s.textContent = '  at ' + el.dataset.x + ' ' + el.dataset.var;
    tip.appendChild(b); tip.appendChild(s);
    var r = el.getBoundingClientRect();
    tip.style.opacity = '1';
    var tw = tip.offsetWidth;
    var left = Math.min(Math.max(8, r.left + r.width / 2 - tw / 2),
                        window.innerWidth - tw - 8);
    tip.style.left = left + 'px';
    tip.style.top = Math.max(8, r.top - tip.offsetHeight - 10) + 'px';
  }}
  function hide() {{ tip.style.opacity = '0'; }}
  document.querySelectorAll('.hit').forEach(function (el) {{
    el.addEventListener('pointerenter', function () {{ show(el); }});
    el.addEventListener('pointerleave', hide);
    el.addEventListener('focus', function () {{ show(el); }});
    el.addEventListener('blur', hide);
  }});
}})();
</script>"""

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        fh.write(html)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
