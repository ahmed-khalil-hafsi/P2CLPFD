"""
P2CLPFD command line interface.

Two audiences share one entry point. A category manager runs `p2clpfd advise
quotes.csv` and reads sentences. An agent runs the same command with `--json`
and gets the structured findings. Neither is a second-class citizen: the JSON
is the same data the tables are rendered from, so they can never disagree.

    p2clpfd solve quotes.csv                 cheapest legal award
    p2clpfd advise quotes.csv                award + what to do about it
    p2clpfd rules quotes.csv                 what did it understand?
    p2clpfd validate quotes.csv              is this data fit to decide on?
    p2clpfd sensitivity quotes.csv           where should I negotiate?
    p2clpfd scenarios quotes.csv -s ...      what if?
    p2clpfd multiperiod quotes.csv           allocate across periods
    p2clpfd trace quotes.csv                 how the solver got there
    p2clpfd report quotes.csv -o award.html  the whole decision, as a document
    p2clpfd mcp                              serve over MCP for agents

Awards are restricted to whole 5% steps of demand by default, because an
unbounded model does not finish otherwise. `--increment 0` searches every
quantity; `--increment N` sets a different step. Runs that used a grid say
so on stderr, since "optimal on a 5% grid" is a smaller claim than optimal.

Exit codes are meaningful, so this composes in a shell:
    0  success
    1  no feasible award, or validation found an error
    2  bad usage / unreadable input
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from typing import Any, Optional

EXIT_OK = 0
EXIT_NO_ANSWER = 1
EXIT_BAD_INPUT = 2

# ── presentation helpers ──────────────────────────────────────────────────
#
# Deliberately dependency-free: this has to run anywhere SWI-Prolog runs,
# and a procurement laptop is not always allowed to pip install a table
# renderer.


def _money(n: Any) -> str:
    return f"{round(n):,}" if isinstance(n, (int, float)) else str(n)


def _table(rows: list[list[str]], headers: list[str]) -> str:
    """Render a left-aligned table, numeric-looking columns right-aligned."""
    if not rows:
        return "  (none)"
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    def is_num(col: int) -> bool:
        return all(
            str(r[col]).replace(",", "").replace("-", "").replace(".", "").isdigit()
            for r in rows
            if str(r[col]).strip()
        )

    numeric = [is_num(i) for i in range(len(headers))]

    def fmt(cells: list[str]) -> str:
        out = []
        for i, cell in enumerate(cells):
            out.append(
                str(cell).rjust(widths[i]) if numeric[i] else str(cell).ljust(widths[i])
            )
        return "  " + "  ".join(out).rstrip()

    lines = [fmt(headers), "  " + "  ".join("-" * w for w in widths)]
    lines.extend(fmt([str(c) for c in row]) for row in rows)
    return "\n".join(lines)


def _heading(text: str) -> str:
    return f"\n{text}\n{'=' * len(text)}"


def _emit_json(payload: Any) -> None:
    json.dump(payload, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


# ── solver plumbing ───────────────────────────────────────────────────────


def _grid_note(info: dict) -> str:
    """
    Say what the award grid did, or say nothing.

    A grid changes the answer — it is optimal *on the grid*, which is not
    the same claim as optimal. Since it is on by default, a run that used
    one has to admit it, or the tool overstates what it proved.
    """
    requested = (info or {}).get("requested")
    per_part = (info or {}).get("per_part") or {}
    if not requested and not per_part:
        return ""
    lines = []
    if requested:
        lines.append(
            f"note: awards split volume in {requested}% steps, rounded to "
            f"whole units — optimal on that grid, not proven optimal overall."
        )
    if per_part:
        which = ", ".join(f"{k} {v}%" for k, v in sorted(per_part.items()))
        lead = "      " if requested else "note: "
        lines.append(f"{lead}steps set in the file itself: {which}.")
    if requested:
        lines.append("      use --increment 0 to search every quantity.")
    return "\n".join(lines) + "\n"


#: The solver the current command loaded; main() reads its grid state
#: once the command has run, since only then is it known whether the
#: default grid had to be dropped.
_ACTIVE_SOLVER = None


def _dropped_grid_note(solver) -> str:
    grid = getattr(solver, "award_grid", None) or {}
    if not grid.get("dropped"):
        return ""
    return (
        f"note: no award fits whole {grid['requested']}% steps under these "
        f"rules, so every quantity was searched instead — the award above "
        f"is proven optimal, not just optimal on a grid.\n"
    )


def _load(args, announce_grid: bool = True):
    """
    Build a Solver with the CSV loaded and the award grid applied.

    Takes the parsed args rather than a bare path so every command picks
    up --increment without each one remembering to.
    """
    path = args.csv if hasattr(args, "csv") else args
    try:
        from .solver import Solver
    except ImportError as exc:  # janus-swi / SWI-Prolog missing
        sys.stderr.write(
            f"error: cannot load the solver ({exc}).\n"
            "P2CLPFD needs SWI-Prolog and janus-swi. See INSTALL.md.\n"
        )
        raise SystemExit(EXIT_BAD_INPUT)

    solver = Solver()
    try:
        solver.load_csv(path)
    except Exception as exc:
        sys.stderr.write(f"error: could not load {path}: {exc}\n")
        raise SystemExit(EXIT_BAD_INPUT)

    increment = getattr(args, "increment", None) if hasattr(args, "csv") else None
    try:
        solver.award_grid = solver.set_award_grid(increment)
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        raise SystemExit(EXIT_BAD_INPUT)
    if announce_grid:
        # Only commands that produce an award have a claim to qualify.
        sys.stderr.write(_grid_note(solver.award_grid))
    global _ACTIVE_SOLVER
    _ACTIVE_SOLVER = solver
    return solver


# ── rendering per command ─────────────────────────────────────────────────


def _render_allocation(result: dict) -> str:
    out = [_heading(f"Optimal award — total cost {_money(result['tco'])}")]
    for part in result.get("allocations", []):
        rows = [
            [
                s["supplier"],
                s["qty"],
                _money(s.get("unit_cost", 0)),
                _money(s.get("subtotal", 0)),
                _money(s["fixed_cost"]) if s.get("fixed_cost") else "",
            ]
            for s in part.get("suppliers", [])
            if s.get("qty", 0) > 0
        ]
        out.append(f"\n{part['part']}")
        out.append(_table(rows, ["supplier", "qty", "unit", "subtotal", "one-off"]))
    return "\n".join(out)


def _render_findings(findings: list[dict]) -> str:
    marks = {
        "critical": "!!",
        "warning": " !",
        "opportunity": " +",
        "info": "  ",
    }
    lines = []
    for f in findings:
        lines.append(f"{marks.get(f['severity'], '  ')} {f['say_to_user']}")
    return "\n".join(lines) if lines else "  (nothing worth flagging)"


def _render_validation(report: dict) -> str:
    status = report.get("status", "unknown")
    headline = {
        "ok": "Data looks fit to decide on.",
        "warning": "Data is usable but something looks unintended.",
        "error": "Do not trust a result from this data until it is fixed.",
    }.get(status, status)
    out = [_heading(f"Validation — {headline}")]
    issues = report.get("issues", [])
    if not issues:
        out.append("  No issues found.")
    else:
        for issue in issues:
            out.append(f"  [{issue['severity']}] {issue['message']}")
    return "\n".join(out)


def _render_sensitivity(report: dict) -> str:
    if report.get("status") != "ok":
        return "\nNo feasible award, so there is nothing to negotiate over."

    out = [_heading(f"Where to negotiate — baseline cost {_money(report['tco'])}")]

    levers = report.get("negotiation_levers", [])
    worth = [l for l in levers if l.get("savings", 0) > 0]
    if worth:
        rows = [
            [
                l["constraint"],
                l.get("supplier") if l.get("supplier") not in (None, "null") else "",
                l.get("part") if l.get("part") not in (None, "null") else "",
                l.get("relaxed_limit"),
                _money(l.get("savings", 0)),
            ]
            for l in worth
        ]
        out.append(_table(rows, ["constraint", "supplier", "part", "relax to", "saves"]))
    else:
        out.append(
            "  No constraint is costing you money. To save here you need\n"
            "  better prices, not looser rules."
        )

    binding = report.get("binding_constraints", [])
    if binding:
        rows = [
            [
                b["constraint"],
                b.get("supplier") if b.get("supplier") not in (None, "null") else "",
                b.get("part") if b.get("part") not in (None, "null") else "",
                b.get("used"),
                b.get("limit"),
            ]
            for b in binding
        ]
        out.append("\nConstraints the award is pressed against:")
        out.append(_table(rows, ["constraint", "supplier", "part", "used", "limit"]))
    return "\n".join(out)


def _render_multiperiod(plan: dict) -> str:
    out = [_heading(f"Multi-period plan — total cost {_money(plan['tco'])}")]
    rows = []
    for row in plan.get("plan", []):
        awarded = " ".join(
            f"{s['supplier']}={s['qty']}" for s in row.get("suppliers", [])
        )
        rows.append(
            [row["period"], row["part"], awarded or "-", row.get("end_inventory", 0)]
        )
    out.append(_table(rows, ["period", "part", "award", "carried"]))
    return "\n".join(out)


def _render_scenarios(report: dict) -> str:
    out = [_heading("Scenario comparison")]
    deltas = {d["name"]: d for d in report.get("deltas", [])}
    rows = []
    for r in report.get("results", []):
        delta = deltas.get(r["name"])
        rows.append(
            [
                r["name"],
                r.get("status", ""),
                _money(r["tco"]) if r.get("tco") not in (None, "-") else "-",
                f"{delta['delta']:+,}" if delta else "",
                f"{delta['pct']:+}%" if delta else "",
            ]
        )
    out.append(_table(rows, ["scenario", "status", "cost", "delta", "pct"]))
    return "\n".join(out)


# ── commands ──────────────────────────────────────────────────────────────


def cmd_solve(args) -> int:
    solver = _load(args)
    result = solver.solve(max_cost=args.max_cost)
    if result is None:
        if args.json:
            _emit_json({"status": "infeasible", "tco": None, "allocations": []})
        else:
            sys.stdout.write(
                "\nNo award satisfies every rule.\n"
                "Run `p2clpfd validate` to see which rule is impossible, or\n"
                "`p2clpfd advise` for a plain-language diagnosis.\n"
            )
        return EXIT_NO_ANSWER
    if args.json:
        _emit_json(result)
    else:
        sys.stdout.write(_render_allocation(result) + "\n")
    return EXIT_OK


def _quote_limits(q: dict) -> str:
    """One quote's rules as a short phrase list; '—' when it has none."""
    bits = []
    if not q.get("qualified", True):
        why = "; ".join(q.get("excluded_because") or []) or "fails a qualification gate"
        bits.append(f"EXCLUDED — {why}")
    for tier in q.get("price_tiers") or []:
        upper = "+" if tier.get("to") in (None, "null") else f"–{_money(tier['to'])}"
        bits.append(f"{_money(tier['from'])}{upper} at {_money(tier['unit_cost'])}")
    landed = q.get("lowest_landed_unit_cost")
    if landed is not None and landed != q.get("unit_cost") and not q.get("price_tiers"):
        bits.append(f"effective {_money(landed)}")
    if "capacity" in q:
        bits.append(f"capacity {_money(q['capacity'])}")
    if "moq" in q:
        bits.append(f"min order {_money(q['moq'])}")
    lo, hi = q.get("share_min_pct"), q.get("share_max_pct")
    if lo is not None and hi is not None:
        bits.append(f"{lo}–{hi}% of the part")
    elif lo is not None:
        bits.append(f"at least {lo}% of the part")
    elif hi is not None:
        bits.append(f"at most {hi}% of the part")
    if "fixed_cost" in q:
        bits.append(f"one-off {_money(q['fixed_cost'])} if awarded")
    if "lead_time_days" in q:
        bits.append(f"lead time {q['lead_time_days']}d")
    return ", ".join(bits) or "—"


def _supplier_rules(s: dict) -> list:
    out = []
    if "global_capacity" in s:
        out.append(f"can make {_money(s['global_capacity'])} in total across parts")
    if "max_share_of_total_pct" in s:
        out.append(f"at most {s['max_share_of_total_pct']}% of total volume")
    if "rebate" in s:
        r = s["rebate"]
        out.append(f"{r['pct']}% back on all its spend above "
                   f"{_money(r['threshold'])} units")
    if "otif_pct" in s:
        out.append(f"on-time delivery {s['otif_pct']}%")
    if "region" in s:
        extra = []
        if "fx_rate_pct" in s:
            extra.append(f"FX {s['fx_rate_pct']}%")
        if "logistics_per_unit" in s:
            extra.append(f"freight {_money(s['logistics_per_unit'])}/unit")
        out.append(f"region {s['region']}" + (f" ({', '.join(extra)})" if extra else ""))
    if s.get("noncost_adjustment"):
        adj = s["noncost_adjustment"]
        out.append(f"{'+' if adj > 0 else ''}{adj}/unit non-cost adjustment")
    if s.get("certifications"):
        out.append("certified " + ", ".join(s["certifications"]))
    if "route" in s:
        out.append(f"ships via {s['route']}")
    return out


def _render_rules(rules: dict, path: str) -> str:
    title = f"Rules as the solver reads them — {os.path.basename(path)}"
    lines = ["", title, "=" * len(title)]
    for part in rules.get("parts", []):
        lines += ["", f"{part['part']} — buy {_money(part['demand'])}"]
        n = part.get("min_suppliers", 0)
        count = []
        if n:
            count.append(f"at least {n} supplier{'s' if n != 1 else ''}"
                         + (" (dual sourcing)" if part.get("dual_source") else ""))
        if "max_suppliers" in part:
            count.append(f"at most {part['max_suppliers']}")
        if count:
            lines.append("  " + ", ".join(count))
        if "award_step_pct" in part:
            lines.append(f"  awards in {part['award_step_pct']}% steps, "
                         f"rounded to whole units")
        if "max_lead_time_days" in part:
            lines.append(f"  lead time at most {part['max_lead_time_days']} days")
        if part.get("required_certifications"):
            lines.append("  suppliers must hold "
                         + ", ".join(part["required_certifications"]))
        rows = [
            [q["supplier"],
             _money(q["unit_cost"]) if "unit_cost" in q else "tiered",
             _quote_limits(q)]
            for q in part.get("quotes", [])
        ]
        lines.append(_table(rows, ["supplier", "price", "rules"]))

    supplier_lines = [
        f"  {s['supplier']}: " + "; ".join(_supplier_rules(s))
        for s in rules.get("suppliers", []) if _supplier_rules(s)
    ]
    if supplier_lines:
        lines += ["", "Across all parts"] + supplier_lines

    port = rules.get("portfolio") or {}
    portfolio = []
    if "min_otif_pct" in port:
        portfolio.append(f"every supplier needs on-time delivery of at least "
                         f"{port['min_otif_pct']}%")
    if port.get("required_certifications"):
        portfolio.append("every supplier must hold "
                         + ", ".join(port["required_certifications"]))
    for r in port.get("route_capacity") or []:
        portfolio.append(f"route {r['route']} carries at most {_money(r['capacity'])}")
    for r in port.get("route_share_cap") or []:
        portfolio.append(f"route {r['route']} carries at most {r['max_pct']}% of volume")
    if portfolio:
        lines += ["", "Portfolio"] + [f"  {p}" for p in portfolio]

    lines += ["", "Anything not listed has no limit."]
    return "\n".join(lines)


def cmd_rules(args) -> int:
    solver = _load(args, announce_grid=False)
    rules = solver.rules()
    if args.json:
        _emit_json(rules)
    else:
        sys.stdout.write(_render_rules(rules, args.csv) + "\n")
    return EXIT_OK


def cmd_validate(args) -> int:
    solver = _load(args, announce_grid=False)
    report = solver.validate()
    if args.json:
        _emit_json(report)
    else:
        sys.stdout.write(_render_validation(report) + "\n")
    return EXIT_NO_ANSWER if report.get("status") == "error" else EXIT_OK


def cmd_advise(args) -> int:
    solver = _load(args)
    report = solver.advise(sensitivity_step=args.step)
    if args.json:
        _emit_json(report)
        return EXIT_OK if report.get("tco") is not None else EXIT_NO_ANSWER

    sys.stdout.write(_heading("Verdict") + "\n")
    sys.stdout.write(report["verdict"] + "\n")
    sys.stdout.write(_heading("What to look at") + "\n")
    sys.stdout.write(_render_findings(report.get("findings", [])) + "\n")
    return EXIT_OK if report.get("tco") is not None else EXIT_NO_ANSWER


def cmd_sensitivity(args) -> int:
    solver = _load(args)
    report = solver.sensitivity(step=args.step)
    if args.json:
        _emit_json(report)
    else:
        sys.stdout.write(_render_sensitivity(report) + "\n")
    return EXIT_OK if report.get("status") == "ok" else EXIT_NO_ANSWER


def cmd_multiperiod(args) -> int:
    solver = _load(args)
    plan = solver.solve_multiperiod()
    if plan is None:
        if args.json:
            _emit_json({"status": "infeasible", "tco": None, "plan": []})
        else:
            sys.stdout.write(
                "\nNo multi-period plan is possible.\n"
                "Check that the CSV has period demand, and that capacity across\n"
                "the whole horizon can cover it.\n"
            )
        return EXIT_NO_ANSWER
    if args.json:
        _emit_json(plan)
    else:
        sys.stdout.write(_render_multiperiod(plan) + "\n")
    return EXIT_OK


def cmd_scenarios(args) -> int:
    scenarios = _parse_scenarios(args)
    solver = _load(args)
    report = solver.compare_scenarios(scenarios)
    if args.json:
        _emit_json(report)
    else:
        sys.stdout.write(_render_scenarios(report) + "\n")
    return EXIT_OK


def _parse_scenarios(args) -> list[dict]:
    """
    Scenarios come either as a JSON file (--scenarios-file) or as repeated
    --scenario NAME:OVERRIDE_JSON pairs, so simple cases stay typeable.
    """
    if args.scenarios_file:
        try:
            with open(args.scenarios_file) as fh:
                return json.load(fh)
        except Exception as exc:
            sys.stderr.write(f"error: could not read {args.scenarios_file}: {exc}\n")
            raise SystemExit(EXIT_BAD_INPUT)

    scenarios: list[dict] = [{"name": "baseline", "overrides": []}]
    for spec in args.scenario or []:
        name, _, raw = spec.partition(":")
        if not raw:
            sys.stderr.write(
                f"error: --scenario expects NAME:JSON, got {spec!r}\n"
                'example: --scenario no_cap:\'[{"remove": "max_global_share(supplier2,_)"}]\'\n'
            )
            raise SystemExit(EXIT_BAD_INPUT)
        try:
            overrides = json.loads(raw)
        except json.JSONDecodeError as exc:
            sys.stderr.write(f"error: scenario {name!r} has invalid JSON: {exc}\n")
            raise SystemExit(EXIT_BAD_INPUT)
        scenarios.append({"name": name, "overrides": overrides})

    if len(scenarios) == 1:
        sys.stderr.write(
            "error: give at least one scenario with --scenario or --scenarios-file\n"
        )
        raise SystemExit(EXIT_BAD_INPUT)
    return scenarios


def _command_line() -> str:
    """The command that produced this run, for a report to quote verbatim."""
    argv = [os.path.basename(sys.argv[0] or "p2clpfd")] + sys.argv[1:]
    return " ".join(shlex.quote(arg) for arg in argv)


def cmd_report(args) -> int:
    """
    Render the whole decision as one file someone else can open.

    Every other command talks to whoever is at the terminal. This one
    produces the artifact that outlives the conversation — the thing you
    forward when the award is questioned six months later — so it carries
    the award, the reasoning and the provenance in a single document with
    no external dependencies.
    """
    from . import report as _report

    scenarios = (
        _parse_scenarios(args) if (args.scenario or args.scenarios_file) else None
    )
    solver = _load(args)
    payload = _report.build(
        solver,
        args.csv,
        scenarios=scenarios,
        include_trace=not args.no_trace,
        sensitivity_step=args.step,
        command=_command_line(),
    )

    document = (
        json.dumps(payload, indent=2, default=str)
        if args.json
        else _report.render_html(payload)
    )

    if args.output in (None, "-"):
        sys.stdout.write(document)
        if not document.endswith("\n"):
            sys.stdout.write("\n")
    else:
        try:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(document)
        except OSError as exc:
            sys.stderr.write(f"error: could not write {args.output}: {exc}\n")
            raise SystemExit(EXIT_BAD_INPUT)
        sys.stdout.write(f"wrote {args.output}\n")

    # An infeasible model still earns a document — it records which rules
    # conflict — but the exit code has to say there is no award to quote.
    return EXIT_OK if payload.get("tco") is not None else EXIT_NO_ANSWER


def cmd_trace(args) -> int:
    solver = _load(args)
    result = solver.solve_trace(max_cost=args.max_cost)
    if result.get("tco") is None and (solver.award_grid or {}).get("requested"):
        # solve() drops the default grid if the grid alone is the problem;
        # trace again so the reasoning shown matches the award reported.
        if solver.solve(max_cost=args.max_cost) is not None:
            result = solver.solve_trace(max_cost=args.max_cost)
    sys.stdout.write(result.get("trace", ""))
    if not result.get("trace", "").endswith("\n"):
        sys.stdout.write("\n")
    return EXIT_OK if result.get("tco") is not None else EXIT_NO_ANSWER


def cmd_mcp(_args) -> int:
    from .mcp import serve

    serve()
    return EXIT_OK


# ── argument parsing ──────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="p2clpfd",
        description="Procurement allocation optimizer — provably optimal, not a guess.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  p2clpfd advise quotes.csv\n"
            "  p2clpfd solve quotes.csv --max-cost 15000\n"
            "  p2clpfd sensitivity quotes.csv --step 10\n"
            "  p2clpfd scenarios quotes.csv \\\n"
            "      --scenario price_up:'[{\"cost_delta\": [\"TI\", \"ABC\", 10]}]' \\\n"
            "      --scenario split:'[{\"set\": \"share(ABC,TI,70,70)\"}]'\n"
            "  p2clpfd report quotes.csv -o award.html\n"
            "  p2clpfd solve quotes.csv --json | jq .tco\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p, with_csv: bool = True) -> None:
        if with_csv:
            p.add_argument("csv", help="CSV file of procurement data")
        p.add_argument(
            "--json",
            action="store_true",
            help="emit machine-readable JSON instead of tables",
        )
        if with_csv:
            p.add_argument(
                "--increment",
                type=int,
                default=5,
                metavar="PCT",
                help=(
                    "restrict awards to whole PCT%% steps of demand "
                    "(default: 5; use 0 for an exact solve, which on an "
                    "unbounded model may not finish)"
                ),
            )

    p = sub.add_parser("solve", help="find the cheapest legal award")
    add_common(p)
    p.add_argument("--max-cost", type=int, help="reject awards above this cost")
    p.set_defaults(func=cmd_solve)

    p = sub.add_parser("advise", help="award plus what to do about it")
    add_common(p)
    p.add_argument(
        "--step",
        type=int,
        default=1,
        help="relaxation size for quantity constraints when pricing levers",
    )
    p.set_defaults(func=cmd_advise)

    p = sub.add_parser("rules", help="read the rules back before deciding on them")
    add_common(p)
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser("validate", help="check the data before deciding on it")
    add_common(p)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("sensitivity", help="binding constraints and shadow prices")
    add_common(p)
    p.add_argument("--step", type=int, default=1, help="relaxation size")
    p.set_defaults(func=cmd_sensitivity)

    p = sub.add_parser("scenarios", help="compare what-if scenarios")
    add_common(p)
    p.add_argument(
        "--scenario",
        action="append",
        metavar="NAME:JSON",
        help="a named scenario and its override list (repeatable)",
    )
    p.add_argument(
        "--scenarios-file", help="JSON file of [{name, overrides}, ...] instead"
    )
    p.set_defaults(func=cmd_scenarios)

    p = sub.add_parser("multiperiod", help="allocate across periods with carryover")
    add_common(p)
    p.set_defaults(func=cmd_multiperiod)

    p = sub.add_parser("trace", help="NDJSON trace of the solver's search")
    add_common(p)
    p.add_argument("--max-cost", type=int, help="reject awards above this cost")
    p.set_defaults(func=cmd_trace)

    p = sub.add_parser(
        "report", help="the whole decision as one self-contained HTML document"
    )
    add_common(p)
    p.add_argument(
        "-o", "--output", metavar="FILE", help="write here instead of stdout"
    )
    p.add_argument(
        "--no-trace",
        action="store_true",
        help="leave out the solver's reasoning, and the second solve it costs",
    )
    p.add_argument(
        "--step", type=int, default=1, help="relaxation size when pricing constraints"
    )
    p.add_argument(
        "--scenario",
        action="append",
        metavar="NAME:JSON",
        help="also compare this what-if in the report (repeatable)",
    )
    p.add_argument(
        "--scenarios-file", help="JSON file of [{name, overrides}, ...] instead"
    )
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("mcp", help="serve over MCP on stdio for agents")
    p.set_defaults(func=cmd_mcp, json=False)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        code = args.func(args)
    except KeyboardInterrupt:
        sys.stderr.write("\ninterrupted\n")
        return EXIT_BAD_INPUT
    except ValueError as exc:
        # Input the solver refused, with a message written for the user.
        sys.stderr.write(f"error: {exc}\n")
        return EXIT_BAD_INPUT
    except Exception as exc:
        # A Prolog error reaching here is a bug, not bad input — but the
        # person at the terminal still deserves a sentence, not a stack.
        if type(exc).__module__.startswith("janus"):
            sys.stderr.write(
                "error: the solver failed on this input and could not say why.\n"
                f"       ({exc})\n"
                "       This is a bug in P2CLPFD, not in your data — please "
                "report it with the CSV and the command you ran.\n"
            )
            return EXIT_BAD_INPUT
        raise
    sys.stderr.write(_dropped_grid_note(_ACTIVE_SOLVER))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
