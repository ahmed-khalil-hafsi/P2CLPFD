"""
P2CLPFD MCP Server

A Model Context Protocol (MCP) server that exposes the P2CLPFD procurement
optimization engine as tools any AI agent can call.

Runs over stdio (JSON-RPC). No external dependencies beyond p2clpfd + stdlib.

Usage:
    uv run mcp-server       # via pip package entry point
    python -m p2clpfd.mcp   # directly
"""

from __future__ import annotations

import json
import sys
from traceback import format_exc
from typing import Any

from .solver import Solver

# ── tools schema ────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "solve_allocation",
        "description": "Find the cost-optimal supplier allocation for the given CSV. "
        "Returns TCO, per-part supplier quantities, and per-supplier costs. "
        "Provably optimal — not a heuristic guess.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "csv_path": {
                    "type": "string",
                    "description": "Absolute path to the CSV file with procurement data."
                },
                "max_cost": {
                    "type": "integer",
                    "description": "Optional cost ceiling. Only solutions with TCO <= max_cost are returned."
                },
            },
            "required": ["csv_path"],
        },
    },
    {
        "name": "compare_scenarios",
        "description": "Compare multiple what-if sourcing scenarios against a baseline. "
        "Returns TCO, status, and deltas for each scenario vs the baseline. "
        "Use this to answer 'what if we relaxed this constraint?' or 'what if supplier X raises prices?'",
        "inputSchema": {
            "type": "object",
            "properties": {
                "csv_path": {
                    "type": "string",
                    "description": "Absolute path to the CSV file with procurement data."
                },
                "scenarios": {
                    "type": "array",
                    "description": "List of scenario objects, each with 'name' and 'overrides'.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "overrides": {
                                "type": "array",
                                "description": "Override operations. Each is one of: "
                                "{'set': 'cost(s1,p1,50)'}, "
                                "{'remove': 'dual_source(part1)'}, "
                                "{'cost_delta': ['supplier2','part1',10]}, "
                                "{'demand_delta': ['part1',10]}",
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
        "name": "validate_data",
        "description": "Validate a CSV file for common procurement data issues: "
        "tier coverage gaps, MOQ > capacity, missing demand/cost facts, "
        "share range errors. Call this before solving to catch data problems early.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "csv_path": {
                    "type": "string",
                    "description": "Absolute path to the CSV file to validate."
                },
            },
            "required": ["csv_path"],
        },
    },
]

# ── JSON-RPC handler ──────────────────────────────────────────────────────

_solver: Solver | None = None


def _get_solver() -> Solver:
    global _solver
    if _solver is None:
        _solver = Solver()
    return _solver


def _handle_initialize(_params: dict) -> dict:
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {
            "name": "p2clpfd",
            "version": "0.1.0",
        },
    }


def _handle_tools_list(_params: dict) -> dict:
    return {"tools": TOOLS}


def _handle_tools_call(params: dict) -> dict:
    name = params.get("name", "")
    args = params.get("arguments", {})

    if name == "solve_allocation":
        csv_path = args.get("csv_path", "")
        max_cost = args.get("max_cost")
        solver = _get_solver()
        solver.load_csv(csv_path)
        result = solver.solve(max_cost=max_cost)
        return {
            "content": [{
                "type": "text",
                "text": json.dumps(result, indent=2) if result
                        else json.dumps({"status": "infeasible", "message": "No feasible allocation exists"}),
            }]
        }

    elif name == "compare_scenarios":
        csv_path = args.get("csv_path", "")
        scenarios = args.get("scenarios", [])
        solver = _get_solver()
        solver.load_csv(csv_path)
        result = solver.compare_scenarios(scenarios)
        return {
            "content": [{
                "type": "text",
                "text": json.dumps(result, indent=2),
            }]
        }

    elif name == "validate_data":
        csv_path = args.get("csv_path", "")
        solver = _get_solver()
        solver.load_csv(csv_path)
        result = solver.validate()
        return {
            "content": [{
                "type": "text",
                "text": json.dumps(result, indent=2),
            }]
        }

    return {
        "content": [{
            "type": "text",
            "text": f"Unknown tool: {name}",
        }],
        "isError": True,
    }


def _handle_request(msg: dict) -> dict | None:
    """Handle a single JSON-RPC request. Returns response or None for notifications."""
    method = msg.get("method", "")
    msg_id = msg.get("id")

    try:
        if method == "initialize":
            result = _handle_initialize(msg.get("params", {}))
        elif method == "tools/list":
            result = _handle_tools_list(msg.get("params", {}))
        elif method == "tools/call":
            result = _handle_tools_call(msg.get("params", {}))
        elif method == "notifications/initialized":
            return None  # Notification, no response
        else:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32603, "message": str(e), "data": format_exc()},
        }


def serve() -> None:
    """Run the MCP server on stdio."""
    # Unbuffered I/O required for MCP stdio transport
    sys.stdin = open(sys.stdin.fileno(), 'r', encoding='utf-8', closefd=False)
    sys.stdout = open(sys.stdout.fileno(), 'w', encoding='utf-8', closefd=False)
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