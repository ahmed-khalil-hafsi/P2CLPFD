"""
P2CLPFD report — the award as a document you can hand to someone else.

`p2clpfd advise` prints to a terminal; `p2clpfd trace` emits NDJSON that only
trace.html can read. Neither survives the meeting. But the premise of this
whole tool is that the award gets contested later — by the supplier who lost,
by a stakeholder who wanted their incumbent, by an auditor who was not in the
room — and what that person needs is a document, not a scrollback buffer.

So this module renders one file: the verdict, what to look at, the award
itself, the data check, the negotiation agenda, any scenarios, and the
solver's own reasoning — with the source file's checksum and the command that
produced it, so anyone can re-run it and get the same answer.

Self-contained by design. No stylesheet, font, or script is loaded from
anywhere: it has to open from an email attachment on a locked-down laptop in
five years, and it has to print.

    build(solver, "quotes.csv")   -> the report payload, a JSON-safe dict
    render_html(payload)          -> one HTML document, as a string

`render_html` never touches a solver, so the entire presentation layer is
testable without SWI-Prolog.
"""

from __future__ import annotations

import datetime
import hashlib
import html
import json
import os
from typing import Any, Optional

# ── trace phases ──────────────────────────────────────────────────────────
#
# The tracer names its phases after the code that posts them. A buyer reading
# the report has never seen that code, so each one gets a sentence saying
# which of *their* rules just narrowed the options.

_PHASE_LABELS: dict[str, tuple[str, str]] = {
    "parts": (
        "Demand, capacity, minimum orders and share bounds",
        "Every part must be bought in full, nobody may exceed the capacity "
        "they quoted, and minimum orders and share bounds apply per part.",
    ),
    "capacity": (
        "Each supplier's total capacity across all parts",
        "A supplier who can only make so much in total cannot be the answer "
        "to every part at once.",
    ),
    "risk": (
        "Sourcing rules — how many suppliers each part must have",
        "Dual-sourcing and supplier-count rules take options away from any "
        "split that would leave a part too thinly sourced.",
    ),
    "global_share": (
        "Portfolio share caps",
        "No supplier may hold more of the total than their ceiling allows, "
        "however cheap they are.",
    ),
    "routes": (
        "Route ceilings",
        "Suppliers who share a shipping corridor are capped together, so a "
        "chokepoint limits all of them at once.",
    ),
    "rebates": (
        "Portfolio rebates folded into the cost",
        "A rebate earned across all parts changes which award is actually "
        "cheapest, so it is priced in before the search starts.",
    ),
    "tco": (
        "Total cost assembled from the part costs",
        "The objective the search is about to minimise.",
    ),
    "final": (
        "The award",
        "Every quantity is settled: this is the allocation, and no cheaper "
        "one satisfies the rules above. Suppliers who ended at zero are not "
        "listed.",
    ),
}

#: Every rule the document can name, as (label, what it means, an example).
#:
#: `sensitivity.pl` names a binding rule after the fact that posts it —
#: `moq`, `max_global_share`. A reader of this document has never seen those
#: names, and the judgment layer already refuses to say them aloud, so the
#: document does not print them either. But a label alone still assumes the
#: reader knows what a minimum order quantity is, and the person who most
#: needs this document is often the one who was not in the room. So each rule
#: also carries a sentence and a worked example, shown on hover and collected
#: into a glossary at the end for whoever is reading it on paper.
#:
#: The examples use the parts and suppliers from `sample.csv` on purpose: they
#: are concrete without pretending to describe the reader's own award, which
#: a generated example would risk getting wrong.
_RULES = {
    "capacity": (
        "capacity on this part",
        "The most this supplier can make of this one part.",
        "supplier2 can supply at most 150 of part1, so however cheap they "
        "are, unit 151 has to come from somebody else.",
    ),
    "global_capacity": (
        "total capacity",
        "The most this supplier can make across every part together, however "
        "the award is split between them.",
        "supplier2 can produce 400 units in total, so winning 300 of part1 "
        "leaves them only 100 for everything else.",
    ),
    "moq": (
        "minimum order",
        "The smallest order this supplier will accept. They take nothing at "
        "all, or at least this much — there is no middle.",
        "With a minimum order of 75 on part1, supplier2 can be awarded 0 or "
        "75 and up, but never 40.",
    ),
    "share_min": (
        "minimum share of this part",
        "The least of a part's demand this supplier must win if they are used "
        "at all — usually there to keep a second source warm.",
        "A 30% floor on part1's 250 units means supplier2 is awarded at least "
        "75 of them.",
    ),
    "share_max": (
        "maximum share of this part",
        "The most of a part's demand this supplier may win, however cheap "
        "they are.",
        "A 70% ceiling on part1's 250 units caps supplier2 at 175, and the "
        "remaining 75 go elsewhere even at a higher price.",
    ),
    "min_suppliers": (
        "minimum suppliers per part",
        "How many different suppliers this part has to be split across. "
        "Dual-sourcing is this rule set to two.",
        "Requiring two suppliers on part1 splits it even when one supplier is "
        "cheapest on every single unit — that difference is the cost of the "
        "policy, not a worse answer.",
    ),
    "max_suppliers": (
        "maximum suppliers per part",
        "The most suppliers this part may be split across, which is how you "
        "keep the supply base from sprawling.",
        "A cap of 2 on part2 leaves the third-cheapest supplier out of the "
        "award however close their price was.",
    ),
    "max_global_share": (
        "cap on share of total volume",
        "The most of your whole awarded volume any one supplier may hold — "
        "the rule that stops a cheap supplier quietly becoming critical.",
        "A 40% cap over 470 total units stops supplier2 being awarded more "
        "than 188 of them, whatever they quote.",
    ),
    "route_capacity": (
        "route ceiling",
        "A limit on the combined volume of every supplier shipping through "
        "the same corridor. It binds a set of suppliers at once, which no "
        "per-supplier cap can express.",
        "Three suppliers all routing through one strait, with a ceiling of "
        "600 units, must have awards adding up to 600 or less between them.",
    ),
    "max_route_share": (
        "cap on a route's share",
        "The most of your total volume allowed to travel one route, so a "
        "single chokepoint cannot carry the whole portfolio.",
        "A 25% route cap keeps at most a quarter of your volume behind any "
        "one border crossing.",
    ),
}


def _rule(name: Any) -> str:
    """Say a constraint the way a buyer would name it."""
    entry = _RULES.get(str(name))
    return entry[0] if entry else str(name).replace("_", " ")


def _rule_html(name: Any) -> str:
    """
    A rule name that explains itself when you point at it.

    `tabindex` earns the same tooltip from the keyboard, and the glossary at
    the end of the document repeats every definition — hover is the quick
    answer, not the only one, because this file gets printed.
    """
    entry = _RULES.get(str(name))
    if not entry:
        return _e(_rule(name))
    label, meaning, example = entry
    return (
        '<span class="rule" tabindex="0">' + _e(label)
        + '<span class="tip"><strong>' + _e(label[:1].upper() + label[1:])
        + "</strong>" + _e(meaning)
        + '<em>For example</em>' + _e(example) + "</span></span>"
    )


def _glossary(payload: dict) -> str:
    """
    Define every rule that actually shaped this award, and no others.

    A reader on paper has no tooltips, and a reader on a phone has no hover.
    Listing only the rules that appear keeps this from becoming a manual.
    """
    report = payload.get("sensitivity") or {}
    named = [
        row.get("constraint")
        for row in list(report.get("binding_constraints", []))
        + list(report.get("negotiation_levers", []))
    ]
    seen = [kind for kind in _RULES if kind in set(map(str, named))]
    if not seen:
        return ""

    rows = []
    for kind in seen:
        label, meaning, example = _RULES[kind]
        rows.append(
            "<dt>" + _e(label) + "</dt><dd>" + _e(meaning)
            + ' <span class="eg">For example: ' + _e(example) + "</span></dd>"
        )
    return (
        "<p>Only the rules that actually shaped this award are listed. A rule "
        "you wrote that does not appear here did not change the outcome.</p>"
        "<dl>" + "".join(rows) + "</dl>"
    )


_SEVERITY_LABELS = {
    "critical": "must fix",
    "warning": "check this",
    "opportunity": "worth doing",
    "info": "for the record",
}


# ── formatting ────────────────────────────────────────────────────────────


def _money(n: Any) -> str:
    return f"{round(n):,}" if isinstance(n, (int, float)) else str(n)


def _pct(part: float, whole: float) -> float:
    return 0.0 if not whole else round(part * 100 / whole, 1)


def _e(text: Any) -> str:
    """Escape for HTML. Supplier and part names come from a user's CSV."""
    return html.escape(str(text), quote=True)


# ── assembling the payload ────────────────────────────────────────────────


def _checksum(path: str) -> Optional[str]:
    """SHA-256 of the input, so the report names the exact file it read."""
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def summarize_trace(ndjson: str) -> Optional[dict]:
    """
    Turn a raw NDJSON trace into the narrowing story.

    The raw trace carries every value still in every domain — at 20,000 units
    per part that is megabytes of integers nobody will read. What a reader
    actually wants is which rule struck options out, so each phase keeps only
    the variables whose range *changed*, with the range before and after.

    Returns None when the trace carries no domain snapshots (an infeasible
    model, or a solve that never got that far).
    """
    parts: list[str] = []
    suppliers: list[str] = []
    solutions: list[dict] = []
    tco: Optional[int] = None
    phases: list[dict] = []
    previous: dict[str, tuple[int, int, int]] = {}

    for line in ndjson.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # a partial line is not worth failing a report over

        kind = event.get("event")
        if kind == "model_built":
            parts = event.get("parts", [])
            suppliers = event.get("suppliers", [])
        elif kind == "solution_found":
            solutions.append(
                {"tco": event.get("tco"), "type": event.get("type", "better")}
            )
        elif kind == "optimal":
            tco = event.get("tco")
        elif kind == "domain_snapshot":
            phase = event.get("phase", "")
            changed = []
            for var in event.get("vars", []):
                domain = var.get("domain") or []
                if "size" in var:
                    now = (var["min"], var["max"], var["size"])
                elif domain:
                    now = (domain[0], domain[-1], len(domain))
                else:
                    continue
                before = previous.get(var["name"])
                if before != now:
                    changed.append(
                        {
                            "name": var["name"],
                            "min": now[0],
                            "max": now[1],
                            "size": now[2],
                            "was_min": before[0] if before else None,
                            "was_max": before[1] if before else None,
                            "was_size": before[2] if before else None,
                        }
                    )
                previous[var["name"]] = now
            label, explanation = _PHASE_LABELS.get(phase, (phase, ""))
            phases.append(
                {
                    "phase": phase,
                    "label": label,
                    "explanation": explanation,
                    "changed": changed,
                    "tco": event.get("tco"),
                }
            )

    if not phases:
        return None
    return {
        "parts": parts,
        "suppliers": suppliers,
        "phases": phases,
        "solutions": solutions,
        "tco": tco,
    }


def _award_summary(solution: Optional[dict]) -> dict:
    """
    Roll the award up per supplier — the view the concentration finding is
    talking about, so a reader can check the claim rather than take it.

    `awarded` is what the line items add up to. It can differ from the TCO
    when a portfolio rebate applies, so the difference is reported rather
    than quietly absorbed.
    """
    if not solution:
        return {"suppliers": [], "awarded": 0, "adjustment": 0}

    totals: dict[str, dict] = {}
    for part in solution.get("allocations", []):
        for row in part.get("suppliers", []):
            qty = row.get("qty", 0)
            if qty <= 0:
                continue
            entry = totals.setdefault(
                row["supplier"], {"supplier": row["supplier"], "qty": 0, "spend": 0}
            )
            entry["qty"] += qty
            entry["spend"] += row.get("subtotal", 0) + row.get("fixed_cost", 0)

    awarded = sum(e["spend"] for e in totals.values())
    for entry in totals.values():
        entry["share_pct"] = _pct(entry["spend"], awarded)

    tco = solution.get("tco") or 0
    return {
        "suppliers": sorted(totals.values(), key=lambda e: -e["spend"]),
        "awarded": awarded,
        "adjustment": tco - awarded,
    }


def build(
    solver,
    csv_path: str,
    *,
    scenarios: Optional[list[dict]] = None,
    include_trace: bool = True,
    sensitivity_step: int = 1,
    command: Optional[str] = None,
) -> dict:
    """
    Run everything the report shows and return it as one JSON-safe payload.

    One solve feeds the award, the findings and the sensitivity, via
    :meth:`Solver.assess`. The trace is the exception — it needs its own
    instrumented solve, which is why `include_trace` exists: on a model that
    takes minutes, the reader may not want to pay for it twice.

    Args:
        solver: a Solver with the CSV already loaded.
        csv_path: the file it was loaded from, for provenance.
        scenarios: [{name, overrides}, ...] to compare, or None to skip.
        include_trace: run the second, instrumented solve for the reasoning
            section.
        sensitivity_step: relaxation size when pricing constraints.
        command: the command line that produced this, shown so a reader can
            reproduce it.

    Returns:
        The payload `render_html` consumes, which is also what `--json`
        emits — so the document and the data can never disagree.
    """
    assessment = solver.assess(sensitivity_step=sensitivity_step)
    solution = assessment["solution"]

    trace = None
    if include_trace and solution is not None:
        trace = summarize_trace(solver.solve_trace().get("trace", ""))

    comparison = solver.compare_scenarios(scenarios) if scenarios else None

    from . import __version__

    return {
        "generated_at": datetime.datetime.now()
        .astimezone()
        .isoformat(timespec="seconds"),
        "version": __version__,
        "command": command,
        "source": {
            "path": os.path.abspath(csv_path),
            "name": os.path.basename(csv_path),
            "sha256": _checksum(csv_path),
        },
        "verdict": assessment["advice"]["verdict"],
        "findings": assessment["advice"]["findings"],
        "tco": assessment["advice"]["tco"],
        "solve_seconds": round(assessment["solve_seconds"], 2),
        "allocation": solution,
        "summary": _award_summary(solution),
        "validation": assessment["validation"],
        "sensitivity": assessment["sensitivity"],
        "disqualified": assessment["disqualified"],
        "rebates": assessment["rebates"],
        "scenarios": comparison,
        "trace": trace,
        "award_grid": getattr(solver, "award_grid", None),
    }


# ── rendering ─────────────────────────────────────────────────────────────

_CSS = """
:root {
  --ink: #1a1d21; --muted: #5c6670; --faint: #8a939c;
  --rule: #dfe3e8; --panel: #f7f8fa; --bg: #ffffff;
  --critical: #b42318; --warning: #b54708; --opportunity: #067647;
  --info: #5c6670; --bar: #c8cdd4; --bar-final: #067647;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 40px 24px 80px; background: var(--bg); color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
               Helvetica, Arial, sans-serif;
  font-size: 15px; line-height: 1.55;
}
.sheet { max-width: 860px; margin: 0 auto; }
header { border-bottom: 2px solid var(--ink); padding-bottom: 20px; }
h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -0.01em; }
.subtitle { color: var(--muted); font-size: 14px; margin: 0; }
.headline {
  font-size: 34px; font-weight: 600; letter-spacing: -0.02em;
  margin: 24px 0 2px;
}
.headline .unit { font-size: 15px; font-weight: 400; color: var(--muted); }
section { margin-top: 40px; }
h2 {
  font-size: 12px; text-transform: uppercase; letter-spacing: 0.09em;
  color: var(--muted); margin: 0 0 14px; padding-bottom: 8px;
  border-bottom: 1px solid var(--rule); font-weight: 600;
}
h3 { font-size: 15px; margin: 24px 0 8px; font-weight: 600; }
p { margin: 0 0 12px; }
.verdict { font-size: 17px; line-height: 1.5; margin: 0; }
.scroll { overflow-x: auto; margin: 8px 0 4px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th {
  text-align: left; font-weight: 600; font-size: 11px; color: var(--muted);
  text-transform: uppercase; letter-spacing: 0.06em;
  border-bottom: 1px solid var(--rule); padding: 6px 10px 6px 0;
}
td { padding: 7px 10px 7px 0; border-bottom: 1px solid var(--rule); }
td.num, th.num {
  text-align: right; padding-right: 0; padding-left: 12px;
  font-variant-numeric: tabular-nums;
}
tr.total td { font-weight: 600; border-bottom: 2px solid var(--ink); }
tr.total td.label { color: var(--muted); font-weight: 400; }
.finding {
  display: flex; align-items: flex-start; gap: 12px; padding: 12px 0;
  border-bottom: 1px solid var(--rule);
}
.finding:last-child { border-bottom: none; }
.chip {
  flex: 0 0 auto; font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.06em; padding: 3px 7px; border-radius: 3px;
  border: 1px solid currentColor; white-space: nowrap; margin-top: 2px;
  align-self: flex-start;
}
.chip.critical { color: var(--critical); }
.chip.warning { color: var(--warning); }
.chip.opportunity { color: var(--opportunity); }
.chip.info { color: var(--info); }
.panel {
  background: var(--panel); border: 1px solid var(--rule); border-radius: 4px;
  padding: 14px 16px; font-size: 13px; color: var(--muted);
}
.phase { margin: 0 0 4px; padding: 16px 0 4px; border-top: 1px solid var(--rule); }
.phase:first-of-type { border-top: none; }
.phase-why { color: var(--muted); font-size: 13px; margin: 0 0 10px; }
.bar-track {
  background: var(--panel); border: 1px solid var(--rule); height: 9px;
  border-radius: 2px; overflow: hidden; min-width: 90px;
}
.bar-fill { background: var(--bar); height: 100%; }
.bar-fill.final { background: var(--bar-final); }
.was { color: var(--faint); }
.rule {
  position: relative; border-bottom: 1px dotted var(--faint); cursor: help;
}
.rule .tip {
  position: absolute; left: 0; top: calc(100% + 6px); z-index: 20;
  display: none; width: 320px; max-width: calc(100vw - 48px);
  background: var(--ink); color: #f4f5f7; border-radius: 4px;
  padding: 11px 13px; font-size: 12.5px; line-height: 1.5; font-weight: 400;
  text-transform: none; letter-spacing: 0; box-shadow: 0 6px 20px rgba(0,0,0,.28);
}
.rule:hover .tip, .rule:focus .tip, .rule:focus-within .tip { display: block; }
.rule .tip strong, .rule .tip em {
  display: block; font-style: normal; margin-bottom: 3px;
}
.rule .tip strong { color: #fff; }
.rule .tip em {
  margin-top: 9px; color: var(--faint); font-size: 10px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.07em;
}
dl { margin: 0; }
dt { font-weight: 600; margin-top: 16px; }
dt:first-child { margin-top: 0; }
dd { margin: 3px 0 0; color: var(--muted); }
.eg { display: block; margin-top: 3px; color: var(--faint); }
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
}
footer {
  margin-top: 56px; padding-top: 16px; border-top: 1px solid var(--rule);
  color: var(--faint); font-size: 12px;
}
/* A SHA-256 is 64 unbreakable characters — the one thing on the page that
   can push a phone-width layout sideways. */
footer .mono { overflow-wrap: anywhere; }
footer code {
  display: block; margin: 6px 0; padding: 8px 10px; background: var(--panel);
  border: 1px solid var(--rule); border-radius: 3px; color: var(--muted);
  overflow-wrap: anywhere;
}
.none { color: var(--faint); font-style: italic; }
@media print {
  body { padding: 0; font-size: 11pt; }
  section { break-inside: avoid; margin-top: 26px; }
  .phase, .finding, table, dd { break-inside: avoid; }
  /* Paper has no pointer. The glossary carries these definitions. */
  .rule { border-bottom: none; }
  .rule .tip { display: none !important; }
  a { text-decoration: none; color: inherit; }
}
"""


#: Written out rather than interpolated: an f-string cannot carry a
#: backslash-escaped quote on Python 3.9, which this package still supports.
_NUM = ' class="num"'


def _table(headers: list[tuple[str, bool]], rows: list[list[str]],
           total: Optional[list[str]] = None, scroll: bool = True) -> str:
    """
    Render a table. Each header is (label, is_numeric).

    Cells are inserted as-is, because callers pass HTML fragments (a bar, a
    struck-through range). Every caller is therefore responsible for running
    user-supplied text — supplier and part names — through :func:`_e` first.

    `scroll` wraps the table so a wide one scrolls inside itself instead of
    dragging the page sideways on a phone. Pass False when a cell carries a
    tooltip: the wrapper clips in both directions, which would cut the
    tooltip off.
    """
    if not rows:
        return '<p class="none">Nothing to show.</p>'

    head = "".join(
        "<th" + (_NUM if num else "") + ">" + _e(label) + "</th>"
        for label, num in headers
    )
    body = []
    for row in rows:
        cells = "".join(
            "<td" + (_NUM if headers[i][1] else "") + ">" + str(cell) + "</td>"
            for i, cell in enumerate(row)
        )
        body.append("<tr>" + cells + "</tr>")
    if total:
        cells = "".join(
            '<td class="' + ("num" if headers[i][1] else "label") + '">'
            + str(cell) + "</td>"
            for i, cell in enumerate(total)
        )
        body.append('<tr class="total">' + cells + "</tr>")
    table = (
        "<table><thead><tr>" + head + "</tr></thead><tbody>"
        + "".join(body) + "</tbody></table>"
    )
    return '<div class="scroll">' + table + "</div>" if scroll else table


def _render_findings(findings: list[dict]) -> str:
    if not findings:
        return '<p class="none">Nothing worth flagging.</p>'
    out = []
    for finding in findings:
        severity = finding.get("severity", "info")
        label = _SEVERITY_LABELS.get(severity, severity)
        out.append(
            f'<div class="finding"><span class="chip {_e(severity)}">{_e(label)}</span>'
            f'<span>{_e(finding.get("say_to_user", ""))}</span></div>'
        )
    return "".join(out)


def _render_award(payload: dict) -> str:
    solution = payload.get("allocation")
    if not solution:
        return (
            '<p class="none">No award — the rules as written cannot all be '
            "satisfied at once. See the data check below.</p>"
        )

    out = []
    for part in solution.get("allocations", []):
        rows = []
        awarded = [s for s in part.get("suppliers", []) if s.get("qty", 0) > 0]
        volume = sum(s["qty"] for s in awarded)
        spend = sum(s.get("subtotal", 0) + s.get("fixed_cost", 0) for s in awarded)
        for supplier in awarded:
            one_off = supplier.get("fixed_cost", 0)
            rows.append([
                _e(supplier["supplier"]),
                f"{supplier['qty']:,}",
                f"{_pct(supplier['qty'], volume)}%",
                _money(supplier.get("unit_cost", 0)),
                _money(one_off) if one_off else "&mdash;",
                _money(supplier.get("subtotal", 0) + one_off),
            ])
        out.append(f"<h3>{_e(part['part'])}</h3>")
        out.append(_table(
            [("supplier", False), ("quantity", True), ("share", True),
             ("unit", True), ("one-off", True), ("cost", True)],
            rows,
            ["total", f"{volume:,}", "100%", "", "", _money(spend)],
        ))
    return "".join(out)


def _render_summary(payload: dict) -> str:
    summary = payload.get("summary") or {}
    suppliers = summary.get("suppliers", [])
    if not suppliers:
        return ""

    rows = [
        [
            _e(row["supplier"]),
            f"{row['qty']:,}",
            _money(row["spend"]),
            f"{row['share_pct']}%",
        ]
        for row in suppliers
    ]
    table = _table(
        [("supplier", False), ("quantity", True), ("spend", True), ("% of spend", True)],
        rows,
        ["awarded", "", _money(summary.get("awarded", 0)), "100%"],
    )

    adjustment = summary.get("adjustment", 0)
    note = ""
    if adjustment:
        direction = "reduce" if adjustment < 0 else "add to"
        note = (
            f'<p class="panel">Portfolio effects — rebates earned across all '
            f"parts — {direction} the line-item total by "
            f"{_money(abs(adjustment))}, which is why the cost of ownership is "
            f"{_money(payload.get('tco'))} rather than "
            f"{_money(summary.get('awarded', 0))}.</p>"
        )
    return table + note


def _render_validation(payload: dict) -> str:
    report = payload.get("validation") or {}
    status = report.get("status", "unknown")
    headline = {
        "ok": "The data is fit to decide on.",
        "warning": "The data is usable, but something in it looks unintended.",
        "error": "Do not act on this result until the data is fixed.",
    }.get(status, status)
    issues = report.get("issues", [])
    if not issues:
        return f"<p>{_e(headline)}</p>"
    rows = [
        [_e(_SEVERITY_LABELS.get(i.get("severity"), i.get("severity", ""))),
         _e(i.get("message", ""))]
        for i in issues
    ]
    return f"<p>{_e(headline)}</p>" + _table(
        [("severity", False), ("what was found", False)], rows
    )


#: Rules whose limit is a percentage. `sensitivity.pl` reports what the award
#: *uses* in units even for these, so the raw pair reads as "used 188, limit
#: 40" — two different scales in one row. In a terminal that is confusing; in
#: a document someone audits it is a defect. So the report converts the used
#: side to the same scale, from the award it is already showing.
_SHARE_RULES = frozenset({"share_min", "share_max", "max_global_share"})


def _used_against_limit(payload: dict, binding: dict) -> tuple[str, str]:
    """Express one binding rule's usage and limit on the same scale."""
    used, limit = binding.get("used"), binding.get("limit")
    kind = str(binding.get("constraint"))
    if kind not in _SHARE_RULES or not isinstance(used, (int, float)):
        return _e(used), _e(limit)

    whole = _whole_for(payload, kind, binding.get("part"))
    if not whole:
        return _e(used), _e(limit)
    return f"{_pct(used, whole)}%", _limit(kind, limit)


def _limit(kind: Any, value: Any) -> str:
    """A share rule's limit is a percentage; a quantity rule's is units."""
    return f"{_e(value)}%" if str(kind) in _SHARE_RULES else _e(value)


def _whole_for(payload: dict, kind: str, part: Optional[str]) -> int:
    """The volume a share rule is a share *of* — one part, or the portfolio."""
    allocation = payload.get("allocation") or {}
    if kind == "max_global_share":
        return sum(
            row.get("qty", 0)
            for entry in allocation.get("allocations", [])
            for row in entry.get("suppliers", [])
        )
    for entry in allocation.get("allocations", []):
        if entry.get("part") == part:
            return sum(row.get("qty", 0) for row in entry.get("suppliers", []))
    return 0


def _render_sensitivity(payload: dict) -> str:
    report = payload.get("sensitivity") or {}
    if report.get("status") != "ok":
        return '<p class="none">No award, so there is nothing to negotiate over.</p>'

    out = []
    levers = [l for l in report.get("negotiation_levers", []) if l.get("savings", 0) > 0]
    if levers:
        rows = [
            [
                _rule_html(lever["constraint"]),
                _e(lever.get("supplier") or ""),
                _e(lever.get("part") or ""),
                _limit(lever["constraint"], lever.get("relaxed_limit")),
                _money(lever.get("savings", 0)),
                f"{_pct(lever.get('savings', 0), payload.get('tco') or 0)}%",
            ]
            for lever in levers
        ]
        out.append(
            "<p>Each row is a rule that is costing money, and what it would "
            "save to move it one step. This is the call sheet.</p>"
        )
        out.append(_table(
            [("rule", False), ("supplier", False), ("part", False),
             ("relax to", True), ("saves", True), ("of total", True)],
            rows, scroll=False,
        ))
    else:
        out.append(
            "<p>No rule is costing you money. Savings here would have to come "
            "from better prices, not looser rules.</p>"
        )

    binding = report.get("binding_constraints", [])
    if binding:
        rows = []
        for b in binding:
            used, limit = _used_against_limit(payload, b)
            rows.append([
                _rule_html(b["constraint"]),
                _e(b.get("supplier") or ""),
                _e(b.get("part") or ""),
                used,
                limit,
            ])
        out.append("<h3>What the award is pressed against</h3>")
        out.append(
            '<p class="phase-why">These rules are active — the award sits '
            "exactly on their limit. A rule not listed here is not shaping "
            "the outcome.</p>"
        )
        out.append(_table(
            [("rule", False), ("supplier", False), ("part", False),
             ("used", True), ("limit", True)],
            rows, scroll=False,
        ))
    return "".join(out)


def _render_scenarios(payload: dict) -> str:
    report = payload.get("scenarios")
    if not report:
        return ""
    deltas = {d["name"]: d for d in report.get("deltas", [])}
    rows = []
    for result in report.get("results", []):
        delta = deltas.get(result["name"])
        rows.append([
            _e(result["name"]),
            _e(result.get("status", "")),
            _money(result["tco"]) if result.get("tco") not in (None, "-") else "&mdash;",
            f"{delta['delta']:+,}" if delta else "&mdash;",
            f"{delta['pct']:+}%" if delta else "&mdash;",
        ])
    return (
        "<p>The same data under different rules. Every number is an exact "
        "optimum, not an estimate, so the differences are the real price of "
        "each policy.</p>"
        + _table(
            [("scenario", False), ("status", False), ("cost", True),
             ("difference", True), ("", True)],
            rows,
        )
    )


def _render_excluded(payload: dict) -> str:
    excluded = payload.get("disqualified") or []
    if not excluded:
        return ""
    rows = [
        [_e(row.get("supplier", "")), _e(row.get("part", "")),
         _e("; ".join(row.get("reasons", [])))]
        for row in excluded
    ]
    return (
        "<p>These suppliers were removed by qualification rules before price "
        "was considered at all. No price could have bought them back in — so "
        'if one of them should have been in the award, the rule is what to '
        "change.</p>"
        + _table([("supplier", False), ("part", False), ("why", False)], rows)
    )


def _render_trace(payload: dict) -> str:
    trace = payload.get("trace")
    if not trace:
        return ""

    widest = 1
    for phase in trace.get("phases", []):
        for var in phase.get("changed", []):
            widest = max(widest, var["size"])

    out = [
        "<p>Constraint solving works by striking out options until only the "
        "best remains. Each step below is one of your rules doing that — the "
        "range is what a supplier could still be awarded at that point. When "
        'someone asks why a supplier could not have more, this is the '
        "answer, in the order it happened.</p>"
    ]

    for phase in trace.get("phases", []):
        changed = phase.get("changed", [])
        out.append('<div class="phase">')
        out.append(f"<h3>{_e(phase['label'])}</h3>")
        if phase.get("explanation"):
            out.append(f'<p class="phase-why">{_e(phase["explanation"])}</p>')
        if not changed:
            out.append(
                '<p class="none">Nothing was struck out here.</p>' 
            )
            out.append("</div>")
            continue

        final = phase.get("phase") == "final"
        rows = []
        for var in changed:
            width = max(2, round(var["size"] * 100 / widest))
            before = (
                '<span class="was">' + _range(var["was_min"], var["was_max"])
                + "</span>"
                if var["was_min"] is not None
                else '<span class="was">&mdash;</span>'
            )
            rows.append([
                f'<span class="mono">{_e(_var_label(var["name"]))}</span>',
                before,
                _range(var["min"], var["max"]),
                f'{var["size"]:,}',
                f'<div class="bar-track"><div class="bar-fill'
                f'{" final" if final else ""}" style="width:{width}%"></div></div>',
            ])
        out.append(_table(
            [("supplier on part", False), ("could have been", True),
             ("now", True), ("options left", True), ("", False)],
            rows,
        ))
        out.append("</div>")
    return "".join(out)


def _range(low: int, high: int) -> str:
    """A settled variable is one number, not a range of one."""
    return f"{low:,}" if low == high else f"{low:,}&ndash;{high:,}"


def _var_label(name: str) -> str:
    """`q.supplier2.part1` is how the solver names it; say it in English."""
    bits = name.split(".")
    if len(bits) == 3 and bits[0] == "q":
        return f"{bits[1]} on {bits[2]}"
    return name


def _subtitle(payload: dict) -> str:
    """
    The claim the document makes about its own award.

    An ungridded solve really is provably optimal and should say so. A
    gridded one is optimal *among awards on the grid*, which is a smaller
    claim — and the document is the thing that gets forwarded to someone
    who will not be in the room to ask, so it has to make the smaller claim
    itself rather than let the reader assume the larger one.
    """
    grid = dict(payload.get("award_grid") or {})
    if grid.get("dropped"):
        grid["requested"] = None  # the search ended up covering every quantity
    steps = set((grid.get("per_part") or {}).values())
    if grid.get("requested"):
        steps.add(grid["requested"])
    if not steps:
        return (
            "Provably the cheapest award that satisfies every rule in the "
            "data below &mdash; not an estimate, and not a heuristic."
        )
    shown = "/".join(f"{s}%" for s in sorted(steps))
    hint = (
        "re-run with <span class=\"mono\">--increment 0</span> to search "
        "every quantity."
        if grid.get("requested")
        else "the steps are set in the data itself."
    )
    return (
        f"Provably the cheapest award that satisfies every rule in the data "
        f"below <em>and</em> splits volume in {shown} steps, rounded to whole "
        f"units. Awards between those steps were not considered; {hint}"
    )


def render_html(payload: dict) -> str:
    """
    Render the payload as one self-contained HTML document.

    Takes no solver and reads no files, so it is safe to call on a stored
    payload — and testable without SWI-Prolog.
    """
    source = payload.get("source", {})
    tco = payload.get("tco")
    title = f"Sourcing award — {_e(source.get('name', 'quotes'))}"

    sections = [
        ("The verdict", f'<p class="verdict">{_e(payload.get("verdict", ""))}</p>'),
        ("What to look at", _render_findings(payload.get("findings", []))),
        ("The award", _render_award(payload)),
        ("Who ends up with what", _render_summary(payload)),
        ("Where to negotiate", _render_sensitivity(payload)),
        ("What if", _render_scenarios(payload)),
        ("Suppliers not in the award", _render_excluded(payload)),
        ("Was the data fit to decide on", _render_validation(payload)),
        ("How the solver decided", _render_trace(payload)),
        ("What these rules mean", _glossary(payload)),
    ]

    body = "".join(
        f"<section><h2>{_e(heading)}</h2>{content}</section>"
        for heading, content in sections
        if content
    )

    headline = (
        f'<div class="headline">{_money(tco)} '
        '<span class="unit">total cost of ownership</span></div>'
        if tco is not None
        else '<div class="headline">No feasible award</div>'
    )

    generated = payload.get("generated_at", "")
    checksum = source.get("sha256") or "unavailable"
    command = payload.get("command")
    reproduce = (
        f"<p>Produced by:</p><code>{_e(command)}</code>" if command else ""
    )

    subtitle = _subtitle(payload)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="sheet">
<header>
  <h1>{title}</h1>
  <p class="subtitle">{subtitle}</p>
  {headline}
</header>
{body}
<footer>
  <p>Generated {_e(generated)} by P2CLPFD {_e(payload.get("version", ""))} from
     <span class="mono">{_e(source.get("path", ""))}</span>, which had
     SHA-256 <span class="mono">{_e(checksum)}</span>. The solve took
     {_e(payload.get("solve_seconds", 0))}s.</p>
  {reproduce}
  <p>Re-running the same command against a file with that checksum reproduces
     this document exactly. If the checksum differs, the data changed and so
     may the award.</p>
</footer>
</div>
</body>
</html>
"""
