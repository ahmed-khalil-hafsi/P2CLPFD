"""
P2CLPFD MCP Server

Exposes the procurement engine as tools any AI agent can call, over stdio
JSON-RPC. No dependencies beyond p2clpfd + stdlib.

The tool descriptions are part of the product. An agent picks tools by
reading them, so each one says what question it answers and when to reach
for it — `get_advice` leads because "what should I do?" is almost always
the real question, and a bare TCO invites an agent to editorialize where
it should be quoting computed findings instead.

Usage:
    p2clpfd mcp             # via the CLI
    p2clpfd-mcp             # dedicated entry point
    python -m p2clpfd.mcp   # directly
"""

from __future__ import annotations

import json
import sys
from traceback import format_exc
from typing import Any

from .solver import Solver

PROTOCOL_VERSION = "2024-11-05"

_CSV_ARG = {
    "type": "string",
    "description": "Absolute path to the CSV file with procurement data.",
}

# ── tool schemas ──────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_advice",
        "description": (
            "START HERE for any sourcing question. Solves for the cheapest legal "
            "award and then interprets it: whether the data is fit to decide on, "
            "where supply risk is concentrated, which constraint is worth "
            "negotiating, and whether a rebate is nearly within reach. Returns a "
            "one-line verdict plus ranked findings, each with a 'say_to_user' "
            "sentence already written in plain procurement language — quote those "
            "rather than describing the numbers yourself. If the model is "
            "infeasible this explains WHICH rule to relax instead of just saying no."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "csv_path": _CSV_ARG,
                "sensitivity_step": {
                    "type": "integer",
                    "description": (
                        "How far to relax quantity limits when pricing negotiation "
                        "levers. Use roughly 5-10% of a typical order quantity; "
                        "1 (the default) can report zero savings on large volumes "
                        "simply because one extra unit changes nothing."
                    ),
                },
            },
            "required": ["csv_path"],
        },
    },
    {
        "name": "solve_allocation",
        "description": (
            "Find the cost-optimal supplier allocation. Returns TCO and per-part "
            "quantities with unit costs. This is a proof of optimality, not a "
            "heuristic guess — no cheaper legal award exists. Use get_advice "
            "instead when the user wants to know what to DO about the result."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "csv_path": _CSV_ARG,
                "max_cost": {
                    "type": "integer",
                    "description": (
                        "Optional budget ceiling. Returns infeasible if the "
                        "cheapest legal award costs more than this."
                    ),
                },
            },
            "required": ["csv_path"],
        },
    },
    {
        "name": "validate_data",
        "description": (
            "Check procurement data for problems before trusting any result: "
            "price-break gaps, minimum orders above capacity, shares that cannot "
            "sum to demand, capacity below demand, missing prices, and suppliers "
            "excluded by qualification rules. Returns status 'error' (the answer "
            "would be wrong or impossible), 'warning' (looks unintended), or 'ok'. "
            "Call this first when the data is unfamiliar; on 'error', fix the data "
            "before quoting any cost."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"csv_path": _CSV_ARG},
            "required": ["csv_path"],
        },
    },
    {
        "name": "analyze_sensitivity",
        "description": (
            "Answer 'where should I negotiate?'. Finds the constraints the optimal "
            "award is pressed against (binding) and prices each one by re-solving "
            "with it relaxed one step. Returns negotiation_levers sorted by "
            "savings, largest first — that ordering IS the negotiation agenda. "
            "A lever worth 0 means loosening that rule saves nothing, which is "
            "just as useful: it tells the buyer not to spend effort there."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "csv_path": _CSV_ARG,
                "step": {
                    "type": "integer",
                    "description": (
                        "Relaxation size for quantity limits (capacity, minimum "
                        "order). Percentages and supplier counts always move by 1."
                    ),
                },
            },
            "required": ["csv_path"],
        },
    },
    {
        "name": "compare_scenarios",
        "description": (
            "Answer 'what if?'. Compares sourcing scenarios against a baseline and "
            "returns each one's cost plus the delta. Use for questions like 'what "
            "if we dropped the dual-sourcing rule?' or 'what if supplier2 raises "
            "prices 10%?'. Overrides do not mutate the underlying data."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "csv_path": _CSV_ARG,
                "scenarios": {
                    "type": "array",
                    "description": (
                        "Scenarios to compare. Put the untouched baseline first so "
                        "the deltas are measured against it."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "overrides": {
                                "type": "array",
                                "description": (
                                    "Each override is one of: "
                                    '{"set": "cost(supplier1,part1,50)"}, '
                                    '{"remove": "dual_source(part1)"}, '
                                    '{"cost_delta": ["supplier2","part1",10]} (percent), '
                                    '{"demand_delta": ["part1",10]} (percent)'
                                ),
                                "items": {"type": "object"},
                            },
                        },
                        "required": ["name"],
                    },
                },
            },
            "required": ["csv_path", "scenarios"],
        },
    },
    {
        "name": "solve_multiperiod",
        "description": (
            "Allocate across time periods with inventory carryover, when the CSV "
            "has a 'period' column. The plan may deliberately buy ahead of demand "
            "when a later period's capacity is too tight and carrying stock is "
            "cheaper than the shortfall. Returns per-period awards and the closing "
            "inventory for each period; the cost includes holding cost."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"csv_path": _CSV_ARG},
            "required": ["csv_path"],
        },
    },
    {
        "name": "list_disqualified",
        "description": (
            "Show which suppliers were excluded by qualification rules (on-time "
            "delivery, lead time, certifications) before price was considered, and "
            "why. Use when the user asks why a supplier they expected is missing "
            "from an award — the answer is usually a gate rather than price."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"csv_path": _CSV_ARG},
            "required": ["csv_path"],
        },
    },
    {
        "name": "solve_trace",
        "description": (
            "Return an NDJSON trace of the solver's internal search: how each "
            "constraint narrows the possible quantities, then the final award. "
            "This is for explaining or debugging HOW the answer was reached — for "
            "the answer itself use solve_allocation, which is far cheaper."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "csv_path": _CSV_ARG,
                "max_cost": {"type": "integer", "description": "Optional cost ceiling."},
            },
            "required": ["csv_path"],
        },
    },
]

# ── tool dispatch ─────────────────────────────────────────────────────────

_solver: Solver | None = None


def _get_solver() -> Solver:
    global _solver
    if _solver is None:
        _solver = Solver()
    return _solver


def _text(payload: Any) -> dict:
    """Wrap a result as MCP text content."""
    body = payload if isinstance(payload, str) else json.dumps(payload, indent=2, default=str)
    return {"content": [{"type": "text", "text": body}]}


def _error(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _loaded(args: dict) -> Solver:
    """
    Load the requested CSV, raising on failure.

    Every tool re-loads: agents call these in any order and a stale fact
    base from a previous file would answer confidently about the wrong data.
    """
    solver = _get_solver()
    solver.load_csv(args.get("csv_path", ""))
    return solver


def _tool_get_advice(args: dict) -> dict:
    solver = _loaded(args)
    step = args.get("sensitivity_step", 1)
    return _text(solver.advise(sensitivity_step=step))


def _tool_solve_allocation(args: dict) -> dict:
    solver = _loaded(args)
    result = solver.solve(max_cost=args.get("max_cost"))
    if result is None:
        return _text({
            "status": "infeasible",
            "message": (
                "No award satisfies every rule. Call validate_data to find the "
                "impossible rule, or get_advice for a diagnosis in plain language."
            ),
        })
    return _text(result)


def _tool_validate_data(args: dict) -> dict:
    solver = _loaded(args)
    return _text(solver.validate())


def _tool_analyze_sensitivity(args: dict) -> dict:
    solver = _loaded(args)
    return _text(solver.sensitivity(step=args.get("step", 1)))


def _tool_compare_scenarios(args: dict) -> dict:
    solver = _loaded(args)
    return _text(solver.compare_scenarios(args.get("scenarios", [])))


def _tool_solve_multiperiod(args: dict) -> dict:
    solver = _loaded(args)
    plan = solver.solve_multiperiod()
    if plan is None:
        return _text({
            "status": "infeasible",
            "message": (
                "No multi-period plan exists. Check the CSV has a 'period' column "
                "and that capacity across the whole horizon can cover demand."
            ),
        })
    return _text(plan)


def _tool_list_disqualified(args: dict) -> dict:
    solver = _loaded(args)
    excluded = solver.disqualified()
    if not excluded:
        return _text({
            "excluded": [],
            "message": "No supplier is excluded by qualification rules.",
        })
    return _text({"excluded": excluded})


def _tool_solve_trace(args: dict) -> dict:
    solver = _loaded(args)
    return _text(solver.solve_trace(max_cost=args.get("max_cost"))["trace"])


_HANDLERS = {
    "get_advice": _tool_get_advice,
    "solve_allocation": _tool_solve_allocation,
    "validate_data": _tool_validate_data,
    "analyze_sensitivity": _tool_analyze_sensitivity,
    "compare_scenarios": _tool_compare_scenarios,
    "solve_multiperiod": _tool_solve_multiperiod,
    "list_disqualified": _tool_list_disqualified,
    "solve_trace": _tool_solve_trace,
}

# ── JSON-RPC ──────────────────────────────────────────────────────────────


def _handle_initialize(_params: dict) -> dict:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "p2clpfd", "version": "0.1.0"},
    }


def _handle_tools_list(_params: dict) -> dict:
    return {"tools": TOOLS}


def _handle_tools_call(params: dict) -> dict:
    name = params.get("name", "")
    args = params.get("arguments", {}) or {}

    handler = _HANDLERS.get(name)
    if handler is None:
        return _error(f"Unknown tool: {name}")

    # Tool-level failures are reported as isError content rather than a
    # JSON-RPC error, so the agent can read the reason and correct itself
    # instead of seeing the whole call fail.
    try:
        return handler(args)
    except FileNotFoundError as exc:
        return _error(f"CSV not found: {exc}")
    except ValueError as exc:
        return _error(str(exc))
    except Exception as exc:
        return _error(f"{type(exc).__name__}: {exc}")


def _handle_request(msg: dict) -> dict | None:
    """Handle one JSON-RPC request. Returns None for notifications."""
    method = msg.get("method", "")
    msg_id = msg.get("id")

    try:
        if method == "initialize":
            result = _handle_initialize(msg.get("params", {}))
        elif method == "tools/list":
            result = _handle_tools_list(msg.get("params", {}))
        elif method == "tools/call":
            result = _handle_tools_call(msg.get("params", {}))
        elif method.startswith("notifications/"):
            return None
        else:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32603, "message": str(exc), "data": format_exc()},
        }


def serve() -> None:
    """Run the MCP server on stdio."""
    # Unbuffered I/O is required by the MCP stdio transport.
    sys.stdin = open(sys.stdin.fileno(), "r", encoding="utf-8", closefd=False)
    sys.stdout = open(sys.stdout.fileno(), "w", encoding="utf-8", closefd=False)
    sys.stdout.reconfigure(line_buffering=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = _handle_request(msg)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    serve()
