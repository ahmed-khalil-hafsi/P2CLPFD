"""
P2CLPFD — Procurement Allocation Optimizer

A constraint-based allocation engine for procurement professionals.
Minimizes Total Cost of Ownership (TCO) across multiple parts and suppliers
subject to capacity, MOQ, sourcing strategy, risk, and pricing constraints.

Requires SWI-Prolog installed on the system.

Usage:
    from p2clpfd import Solver

    s = Solver()
    s.load_csv("quotes.csv")
    result = s.solve()
    print(result["tco"])  # 19534

    result = s.solve(max_cost=15000)  # None if infeasible

    results = s.compare_scenarios([
        {"name": "baseline", "overrides": []},
        {"name": "price_up", "overrides": [{"cost_delta": ["supplier2", "part1", 10]}]},
    ])
"""

from .solver import Solver

__version__ = "0.1.0"
__all__ = ["Solver"]
