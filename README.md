# P2CLPFD: A Constraint Logic Programming Framework for Procurement

P2CLPFD allocates demand for multiple parts across multiple suppliers while
**minimizing the Total Cost of Ownership (TCO)**, subject to realistic
procurement constraints: per-pair capacity, minimum order quantities (MOQ),
sourcing-strategy share bounds, global supplier capacity, fixed costs
(NRE/tooling/setup), risk (dual-sourcing, supplier-count limits), and
global share caps. It also folds non-cost adjustments (quality, logistics,
risk) into the objective.

It is built on SWI-Prolog's CLP(FD) library and solves the allocation as a
finite-domain optimization problem with guaranteed optimality.

## Getting Started

### Prerequisites

- [SWI-Prolog](http://www.swi-prolog.org/Download.html) (developed with v9.x)

### Running

```bash
swipl -q -g run -g halt main.pl
```

Or interactively:

```prolog
?- ['main.pl'].
?- run.                       % solve, pretty-print, verify
?- solve(A, TCO).             % raw solve
?- solve(A, TCO), print_allocation(A, TCO).
```

## API

| Predicate | Description |
|---|---|
| `solve(-Allocation, -TCO)` | Optimal allocation minimizing TCO. |
| `solve(-Allocation, -TCO, +MaxCost)` | As above, with `TCO =< MaxCost`. |
| `print_allocation(+Allocation, +TCO)` | Pretty-print + verify all constraints. |
| `run` / `run(+MaxCost)` | Convenience: solve + print. |

`Allocation` is a list of `alloc(Part, [q(Supplier, Qty), ...])`.

## Fact Schema

All quantities are **absolute integers** (not percentages). A `(Supplier, Part)`
pair with no `cost/3` fact is simply non-allocatable (forced to 0).

| Fact | Meaning |
|---|---|
| `demand(Part, Qty)` | Total quantity of Part to source. |
| `cost(Supplier, Part, UnitCost)` | Flat unit price. Required for allocatable pairs without tiers. |
| `price_tier(Supplier, Part, MinQty, MaxQty, UnitCost)` | Volume-based tiered pricing. Use `sup` for unbounded `MaxQty`. Tiers must be non-overlapping and cover 0..sup. Overrides `cost/3` for that pair. |
| `capacity(Supplier, Part, MaxQty)` | Per-pair maximum. Absent = unlimited. |
| `moq(Supplier, Part, MinQty)` | Minimum order quantity. Absent = 0. |
| `share(Part, Supplier, MinPct, MaxPct)` | Strategy bounds as % of demand (0–100). Absent = unrestricted. |
| `global_capacity(Supplier, MaxQty)` | Total across all parts. Absent = unlimited. |
| `noncost_adjustment(Supplier, Adj)` | Per-unit TCO adjustment (may be negative). Absent = 0. |
| `fixed_cost(Supplier, Part, Amount)` | One-time charge (NRE/tooling) when Q > 0. Absent = 0. |
| `min_suppliers(Part, N)` | Part must be sourced from at least N suppliers. Absent = no lower bound. |
| `max_suppliers(Part, N)` | Part may use at most N suppliers. Absent = no upper bound. |
| `dual_source(Part)` | Shorthand for `min_suppliers(Part, 2)`. |
| `max_global_share(Supplier, Pct)` | Supplier may not exceed Pct% of total demand across all parts. Absent = unrestricted. |

Suppliers are discovered automatically from `cost/3` facts — no need to declare them.

## Example

With the shipped `facts.pl` (250 units of part1, 220 of part2, three
suppliers, tiered pricing on supplier1/part1, dual-source on part1,
supplier2 capped at 40% of total volume), the optimal allocation is:

```
Part: part1
  supplier2: 75 units  (unit: 13, subtotal: 975)
  supplier3: 175 units  (unit: 45, subtotal: 7875)

Part: part2
  supplier2: 113 units  (unit: 33, subtotal: 3729)
  supplier3: 107 units  (unit: 65, subtotal: 6955)

*** Total Cost of Ownership: 19534 ***
```

Note: the reported TCO includes non-cost adjustments (+3 for supplier2, −5 for
supplier3). The global share cap (supplier2 at 40%) and dual-source requirement
force a more balanced award, increasing TCO from ~13k (unconstrained) to ~19k.

## How It Works

The solver builds one finite-domain variable per `(Part, Supplier)` pair, posts
all constraints declaratively, then calls `labeling([min(TCO)], Vars)` to find
the cost-optimal solution. Backtracking yields further solutions in increasing
TCO order.

Key constraint techniques:

- **MOQ as a gap domain:** `Q in 0 \/ Moq..sup` — either order nothing or at
  least the MOQ. This avoids fragile disjunctions and keeps propagation strong.
- **Share bounds as integer ratios:** `MinPct * Demand #=< 100 * Q` avoids
  floating-point and keeps everything in exact integer arithmetic.
- **Tiered pricing via `element/3` + reified bounds:** a `TierVar` selects the
  active price tier; `element/3` maps it to the unit cost; reified `#==>`
  constraints enforce `Q` within the selected tier's `[Min, Max]` range. This
  lets the solver reason about which tier is optimal without enumerating.
- **Fixed costs via reified active variables:** a binary `B` per pair with
  `B #= 1 #<==> Q #>= 1`; cost contribution `B * FixedAmount` added to TCO.
- **Risk constraints on active counts:** per-part `sum(Bs, #>=, MinN)` and
  `sum(Bs, #=<, MaxN)` enforce dual-sourcing and supplier-count limits.
- **Global share via recursive weighted sums:** avoids `forall/2` (whose
  negation-as-failure swallows CLP(FD) constraints) and posts the bound
  directly on the supplier's Q variables.
- **TCO objective:** `Q * (RawUnitCost + NonCostAdjustment) + B * FixedAmount`
  per pair, summed.

## Project Layout

```
facts.pl          Data (demand, costs, capacities, strategy)
solver.pl         The CLP(FD) engine + pretty-printer + verifier
main.pl           Entry point: loads facts+solver, provides run/0,1
```

## License

GPLv3. Copyright (c) 2023 Ahmed Khalil Hafsi.
