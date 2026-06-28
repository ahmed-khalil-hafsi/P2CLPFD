"""
P2CLPFD Solver — Python wrapper around the Prolog CLP(FD) engine.

Uses janus-swi to embed SWI-Prolog in-process for zero-overhead calls.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import janus_swi as janus

_PL_DIR = Path(__file__).parent / "pl"

_LOADED = False


def _ensure_loaded() -> None:
    """Consult all .pl files exactly once."""
    global _LOADED
    if _LOADED:
        return
    for name in ["facts", "solver", "csv_loader", "scenarios", "json_api"]:
        janus.consult(str(_PL_DIR / f"{name}.pl"))
    _LOADED = True


def _overrides_to_prolog(overrides: list[dict]) -> str:
    """Convert Python override dicts to a Prolog list of override terms."""
    parts = []
    for ov in overrides:
        if "set" in ov:
            parts.append(f"set({ov['set']})")
        elif "remove" in ov:
            parts.append(f"remove({ov['remove']})")
        elif "cost_delta" in ov:
            s, p, pct = ov["cost_delta"]
            parts.append(f"cost_delta({s},{p},{pct})")
        elif "demand_delta" in ov:
            p, pct = ov["demand_delta"]
            parts.append(f"demand_delta({p},{pct})")
    return "[" + ",".join(parts) + "]"


def _scenarios_to_prolog(scenarios: list[dict]) -> str:
    """Convert Python scenario dicts to a Prolog list of Name-Overrides pairs."""
    parts = []
    for sc in scenarios:
        name = sc["name"]
        overrides = _overrides_to_prolog(sc.get("overrides", []))
        parts.append(f"{name}-{overrides}")
    return "[" + ",".join(parts) + "]"


class Solver:
    """
    Procurement allocation solver.

    Wraps the P2CLPFD CLP(FD) engine. Each instance shares the same
    Prolog process (embedded via janus-swi).

    Example:
        >>> s = Solver()
        >>> s.load_csv("quotes.csv")
        >>> result = s.solve()
        >>> print(result["tco"])
        19534

        >>> result = s.solve(max_cost=15000)  # None if infeasible
        >>> print(result)
        None

        >>> results = s.compare_scenarios([
        ...     {"name": "baseline", "overrides": []},
        ...     {"name": "no_cap", "overrides": [
        ...         {"remove": "max_global_share(supplier2,_)"}
        ...     ]},
        ... ])
        >>> print(results["deltas"][0]["delta"])
        -5792
    """

    def __init__(self) -> None:
        _ensure_loaded()

    def load_csv(self, path: str) -> dict:
        """
        Load procurement data from a CSV file.

        Clears any previously loaded facts.

        Args:
            path: Path to CSV file with columns:
                part, supplier, demand, unit_cost, capacity, moq,
                share_min, share_max, noncost_adj, fixed_cost,
                min_suppliers, max_suppliers, dual_source,
                global_capacity, global_share_cap
        """
        janus.query_once(
            'with_output_to(string(_), load_csv(Path))',
            {'Path': path}
        )
        return {"status": "ok", "path": path}

    def solve(self, max_cost: Optional[int] = None) -> Optional[dict]:
        """
        Find the optimal allocation minimizing TCO.

        Args:
            max_cost: Optional cost ceiling. If provided, only solutions
                      with TCO <= max_cost are considered.

        Returns:
            Dict with keys:
                - "tco": Total cost of ownership (int)
                - "status": "ok"
                - "allocations": List of {part, suppliers} dicts
            Returns None if no feasible allocation exists.
        """
        if max_cost is not None:
            result = janus.query_once(
                'solve_to_json(MaxCost, JSON)',
                {'MaxCost': max_cost}
            )
        else:
            result = janus.query_once(
                'solve_to_json(JSON)'
            )
        json = result.get("JSON")
        if json and json.get("status") == "ok":
            return json
        return None

    def compare_scenarios(self, scenarios: list[dict]) -> dict:
        """
        Compare multiple what-if scenarios against a baseline.

        Args:
            scenarios: List of scenario dicts, each with:
                - "name": Scenario name (str)
                - "overrides": List of override dicts:
                    - {"set": "cost(supplier1,part1,50)"}
                    - {"remove": "dual_source(part1)"}
                    - {"cost_delta": ["supplier2", "part1", 10]}
                    - {"demand_delta": ["part1", 10]}

        Returns:
            Dict with:
                - "results": List of {name, status, tco} dicts
                - "deltas": List of {name, delta, pct} vs first scenario

        Example:
            >>> results = s.compare_scenarios([
            ...     {"name": "baseline", "overrides": []},
            ...     {"name": "no_cap", "overrides": [
            ...         {"remove": "max_global_share(supplier2,_)"}
            ...     ]},
            ... ])
            >>> print(results["results"][1]["tco"])
            13742
        """
        prolog_scenarios = _scenarios_to_prolog(scenarios)
        result = janus.query_once(
            f'compare_scenarios_to_json({prolog_scenarios}, JSON)'
        )
        return result.get("JSON", {"results": [], "deltas": []})

    def validate(self) -> dict:
        """
        Validate the currently loaded facts for common issues.

        Checks:
            - Tier coverage (gaps, overlaps)
            - MOQ > capacity
            - Missing demand or cost facts
            - Share range validity

        Returns:
            Dict with "status" and any warnings.
        """
        janus.query_once(
            'with_output_to(string(_), validate_facts)'
        )
        return {"status": "ok"}
