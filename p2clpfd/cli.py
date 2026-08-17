"""
P2CLPFD command line interface.

Two audiences share one entry point. A category manager runs `p2clpfd advise
quotes.csv` and reads sentences. An agent runs the same command with `--json`
and gets the structured findings. Neither is a second-class citizen: the JSON
is the same data the tables are rendered from, so they can never disagree.

    p2clpfd solve quotes.csv                 cheapest legal award
    p2clpfd advise quotes.csv                award + what to do about it
    p2clpfd validate quotes.csv              is this data fit to decide on?
    p2clpfd sensitivity quotes.csv           where should I negotiate?
    p2clpfd scenarios quotes.csv -s ...      what if?
    p2clpfd multiperiod quotes.csv           allocate across periods
    p2clpfd trace quotes.csv                 how the solver got there
    p2clpfd mcp                              serve over MCP for agents

Exit codes are meaningful, so this composes in a shell:
    0  success
    1  no feasible award, or validation found an error
    2  bad usage / unreadable input
"""

from __future__ import annotations

import argparse
import json
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


def _load(path: str):
    """Build a Solver with the CSV loaded, or exit with a useful message."""
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
    solver = _load(args.csv)
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


def cmd_validate(args) -> int:
    solver = _load(args.csv)
    report = solver.validate()
    if args.json:
        _emit_json(report)
    else:
        sys.stdout.write(_render_validation(report) + "\n")
    return EXIT_NO_ANSWER if report.get("status") == "error" else EXIT_OK


def cmd_advise(args) -> int:
    solver = _load(args.csv)
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
    solver = _load(args.csv)
    report = solver.sensitivity(step=args.step)
    if args.json:
        _emit_json(report)
    else:
        sys.stdout.write(_render_sensitivity(report) + "\n")
    return EXIT_OK if report.get("status") == "ok" else EXIT_NO_ANSWER


def cmd_multiperiod(args) -> int:
    solver = _load(args.csv)
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
    solver = _load(args.csv)
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


def cmd_trace(args) -> int:
    solver = _load(args.csv)
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
            "      --scenario price_up:'[{\"cost_delta\": [\"supplier2\", \"part1\", 10]}]'\n"
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

    p = sub.add_parser("mcp", help="serve over MCP on stdio for agents")
    p.set_defaults(func=cmd_mcp, json=False)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        sys.stderr.write("\ninterrupted\n")
        return EXIT_BAD_INPUT


if __name__ == "__main__":
    raise SystemExit(main())
