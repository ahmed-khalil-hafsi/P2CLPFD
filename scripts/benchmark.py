"""
Scaling benchmark — where P2CLPFD's time actually goes.

Constraint set is deliberately ORDINARY, the kind most category managers
run: 4 suppliers, quad sourcing (every item must use all four), and each
supplier guaranteed at least a 5% share of the item.

Two things can grow, and they behave nothing alike:

  items   How many parts are being sourced. Nothing in this constraint
          set ties one item to another, so decompose.pl proves each item
          optimal on its own. Expect LINEAR.

  demand  Units per item. This sets the size of each quantity variable's
          domain, and therefore the size of the space branch-and-bound
          must search to prove optimality. Expect roughly QUADRATIC —
          and this, not the item count, is what limits the tool.

A third sweep is available for the coupled case: adding one portfolio
rule (a cap on any supplier's share of TOTAL volume) welds every item
into a single search, because minimizing a sum couples everything the
sum touches.

Usage:
    python scripts/benchmark.py                       # items + demand
    python scripts/benchmark.py --sweep demand
    python scripts/benchmark.py --sweep items --sizes 100 500 1000
    python scripts/benchmark.py --sweep coupled --timeout 60

Results are written as JSON so the chart can be redrawn without
re-running the sweep, which takes a while.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SUPPLIERS = ["alpha", "beta", "gamma", "delta"]
MIN_SHARE_PCT = 5           # every supplier guaranteed at least this
GLOBAL_SHARE_CAP = 40       # coupled sweep only: % of TOTAL volume
SHARE_INCREMENT = 5         # grid sweep only: award granularity, % of demand

# Held fixed while the other variable moves. 20 units/item is small on
# purpose — at 1000 units a SINGLE item does not solve in a minute, so a
# larger figure would make the item sweep impossible to run at all.
FIXED_DEMAND = 20
FIXED_ITEMS = 1

DEFAULT_ITEM_SIZES = [100, 250, 500, 750, 1000, 1500, 2000, 2500, 3000]
DEFAULT_DEMAND_SIZES = [10, 20, 40, 80, 120, 160, 200, 300, 400]
# The grid decouples time from quantity, so this sweep can go far further
# than the free-quantity one — that contrast is the whole point.
DEFAULT_GRID_DEMAND_SIZES = [10, 20, 40, 80, 200, 400, 1000, 5000, 20000]
# The realistic configuration: a portfolio cap plus an award grid.
CAPPED_SHARE_CAP = 30       # capped sweep: no supplier above this % of TOTAL
CAPPED_DEMAND = 1000
DEFAULT_CAPPED_SIZES = [1, 2, 4, 8, 16, 50, 100, 250, 500, 1000, 2000, 3000]


def generate_csv(path: str, n_items: int, demand: int, coupled: bool,
                 increment: int | None = None,
                 rotating_winner: bool = False) -> None:
    """
    Write a synthetic quote sheet.

    Prices rotate per item so the optimum is a real choice rather than a
    tie — a model where every supplier costs the same would flatter the
    solver by making the search trivial.
    """
    header = ["part", "supplier", "demand", "unit_cost", "capacity",
              "share_min", "min_suppliers"]
    if coupled:
        header.append("global_share_cap")
    if increment:
        header.append("share_increment")

    with open(path, "w") as fh:
        fh.write(",".join(header) + "\n")
        for i in range(n_items):
            for s, supplier in enumerate(SUPPLIERS):
                # Which supplier is cheapest matters enormously when a
                # portfolio cap is in play. Shifting every price by the
                # item index (the default) leaves the SAME supplier
                # cheapest throughout, so one supplier wins everything and
                # the cap binds hard. Rotating the winner is the realistic
                # case and lets the cap average out across a catalogue.
                if rotating_winner:
                    cost = 100 + ((s - i) % len(SUPPLIERS)) * 6 + ((i * 3) % 5)
                else:
                    cost = 100 + ((i + s * 7) % 23)
                row = [
                    f"item{i}", supplier, str(demand),
                    str(cost),
                    str(demand),                   # capacity: not binding
                    str(MIN_SHARE_PCT),
                    str(len(SUPPLIERS)),           # quad sourcing
                ]
                if coupled:
                    row.append(str(CAPPED_SHARE_CAP if rotating_winner
                                   else GLOBAL_SHARE_CAP))
                if increment:
                    row.append(str(increment))
                fh.write(",".join(row) + "\n")


# Each solve runs in its own process so an overrun can be killed: CLP(FD)
# labeling does not reliably yield to Prolog's call_with_time_limit/2, so
# an in-process timeout would simply hang.
_RUNNER = r"""
import json, sys, time
from p2clpfd.solver import Solver
s = Solver()
s.load_csv(sys.argv[1])
t0 = time.perf_counter()
result = s.solve()
print(json.dumps({
    "seconds": time.perf_counter() - t0,
    "tco": result["tco"] if result else None,
}))
"""


def run_one(n_items: int, demand: int, coupled: bool, timeout: float,
            increment: int | None = None,
            rotating_winner: bool = False) -> dict:
    fd, path = tempfile.mkstemp(suffix=".csv", prefix="p2bench_")
    os.close(fd)
    try:
        generate_csv(path, n_items, demand, coupled, increment, rotating_winner)
        try:
            proc = subprocess.run(
                [sys.executable, "-c", _RUNNER, path],
                capture_output=True, text=True, cwd=REPO, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {"items": n_items, "demand": demand, "seconds": None,
                    "increment": increment, "timed_out": True,
                    "timeout": timeout}

        if proc.returncode != 0:
            return {"items": n_items, "demand": demand, "seconds": None,
                    "increment": increment,
                    "error": (proc.stderr or "").strip()[-300:]}

        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        return {"items": n_items, "demand": demand,
                "increment": increment,
                "seconds": round(payload["seconds"], 4),
                "tco": payload["tco"], "timed_out": False}
    finally:
        os.unlink(path)


def sweep(label: str, cases: list[tuple[int, int]], coupled: bool,
          timeout: float, per_unit: str,
          increment: int | None = None,
          rotating_winner: bool = False,
          stop_on_timeout: bool = True) -> list[dict]:
    print(f"\n{label}")
    print(f"  {'items':>6} {'demand':>7} {'seconds':>10}  {per_unit}")
    records = []
    for n_items, demand in cases:
        record = run_one(n_items, demand, coupled, timeout, increment,
                         rotating_winner)
        records.append(record)

        if record.get("timed_out"):
            print(f"  {n_items:>6} {demand:>7} {'>' + str(int(timeout)) + 's':>10}"
                  "   gave up")
            # With a portfolio cap, slow does NOT imply slower forever:
            # the cap stops binding once the catalogue is big enough to
            # average out, so keep going.
            if stop_on_timeout:
                break
            continue
        if record.get("error"):
            print(f"  {n_items:>6} {demand:>7}      ERROR {record['error'][:80]}")
            break

        divisor = n_items if per_unit.endswith("item") else demand
        print(f"  {n_items:>6} {demand:>7} {record['seconds']:>10.3f}"
              f"   {record['seconds'] / divisor * 1000:.2f} ms")
        sys.stdout.flush()
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="P2CLPFD scaling benchmark")
    parser.add_argument("--sweep",
                        choices=["items", "demand", "grid", "capped",
                                 "coupled", "both", "all"],
                        default="all")
    parser.add_argument("--sizes", type=int, nargs="+")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--out",
                        default=os.path.join(REPO, "benchmarks", "scaling.json"))
    args = parser.parse_args()

    print("P2CLPFD scaling benchmark")
    print(f"  {len(SUPPLIERS)} suppliers, quad sourcing, "
          f"{MIN_SHARE_PCT}% minimum share")
    print(f"  timeout {args.timeout:.0f}s per solve")

    wanted = {
        "items": ["items"], "demand": ["demand"], "grid": ["grid"],
        "capped": ["capped"], "coupled": ["coupled"],
        "both": ["items", "demand"],
        "all": ["items", "demand", "grid", "coupled"],
    }[args.sweep]

    results = {}
    if "items" in wanted:
        sizes = args.sizes or DEFAULT_ITEM_SIZES
        results["items"] = sweep(
            f"items sweep (demand fixed at {FIXED_DEMAND}/item)",
            [(n, FIXED_DEMAND) for n in sizes], False, args.timeout, "ms/item")
    if "demand" in wanted:
        sizes = args.sizes or DEFAULT_DEMAND_SIZES
        results["demand"] = sweep(
            f"demand sweep ({FIXED_ITEMS} item)",
            [(FIXED_ITEMS, d) for d in sizes], False, args.timeout, "ms/unit")
    if "grid" in wanted:
        sizes = args.sizes or DEFAULT_GRID_DEMAND_SIZES
        results["demand_grid"] = sweep(
            f"demand sweep on a {SHARE_INCREMENT}% award grid ({FIXED_ITEMS} item)",
            [(FIXED_ITEMS, d) for d in sizes], False, args.timeout, "ms/unit",
            increment=SHARE_INCREMENT)
    if "capped" in wanted:
        sizes = args.sizes or DEFAULT_CAPPED_SIZES
        results["capped"] = sweep(
            f"portfolio cap {CAPPED_SHARE_CAP}% + {SHARE_INCREMENT}% grid, "
            f"{CAPPED_DEMAND} units/item, rotating winner",
            [(n, CAPPED_DEMAND) for n in sizes], True, args.timeout, "ms/item",
            increment=SHARE_INCREMENT, rotating_winner=True,
            stop_on_timeout=False)
    if "coupled" in wanted:
        sizes = args.sizes or DEFAULT_ITEM_SIZES
        results["coupled"] = sweep(
            f"coupled sweep (global share cap, demand {FIXED_DEMAND}/item)",
            [(n, FIXED_DEMAND) for n in sizes], True, args.timeout, "ms/item")

    payload = {
        "config": {
            "suppliers": len(SUPPLIERS),
            "min_suppliers": len(SUPPLIERS),
            "min_share_pct": MIN_SHARE_PCT,
            "fixed_demand": FIXED_DEMAND,
            "global_share_cap": GLOBAL_SHARE_CAP,
            "capped_share_cap": CAPPED_SHARE_CAP,
            "capped_demand": CAPPED_DEMAND,
            "share_increment": SHARE_INCREMENT,
            "timeout": args.timeout,
        },
        "results": results,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(payload, fh, indent=2)
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
