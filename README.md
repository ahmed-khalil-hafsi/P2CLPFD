# P2CLPFD — Procurement Allocation Optimizer

```
  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
  │ PART A  │   │ PART B  │   │ PART C  │   │ PART D  │
  │ 500 pcs │   │ 220 pcs │   │ 800 pcs │   │ 150 pcs │
  └────┬────┘   └────┬────┘   └────┬────┘   └────┬────┘
       │             │             │             │
       └──────────┬──┴─────────────┴──────────────┘
                  │
          ┌───────┴───────┐
          │   P2CLPFD     │  minimize TCO
          │   SOLVER      │  subject to:
          │               │  - capacity  - MOQ
          │               │  - share     - risk
          │               │  - tiers     - fixed costs
          └───────┬───────┘
                  │
       ┌──────────┼──────────┐
       v          v          v
  ┌─────────┐┌─────────┐┌─────────┐
  │Supplier1││Supplier2││Supplier3│
  │ 300 pcs ││ 470 pcs ││ 230 pcs │
  └─────────┘└─────────┘└─────────┘
```

## What it does

You have parts to buy and suppliers to buy them from. Some suppliers are cheap but too
small. Some want volume commitments for a discount. Some can't do more than 500 units.
You need at least two suppliers on each part for risk. And nobody should get more than
40% of the total spend.

This is the allocation problem — and P2CLPFD solves it optimally.

P2CLPFD is a **constraint-based optimization engine** for procurement. Give it your
demand, your supplier quotes, and your business rules. It returns the single
cost-optimal award that satisfies every constraint. No heuristics, no approximations —
the result is mathematically guaranteed to be the best.

## What "CLPFD" means (and why you should care)

**CLP(FD)** = **Constraint Logic Programming over Finite Domains**

That sounds academic. Here's what it means for your award:

Think of it like Sudoku. A Sudoku solver doesn't try every possible combination — it
uses constraints ("this row already has a 7", "this square must be ≤ 9") to eliminate
impossible values until only the correct one remains. That's constraint propagation.

P2CLPFD does the same for procurement: "supplier2 can't exceed 150 units of part1",
"part1 must have at least 2 suppliers", "supplier2 must win 30-70% of part1". The
solver propagates these constraints to eliminate impossible quantities, then searches
what's left for the one with the lowest TCO.

This is different from tools that guess and check. A heuristic might find a *good*
solution. Constraint solving finds the *best* one — and proves it.

## Use cases

### Automotive:

> 5,000 part numbers, 50 suppliers, dual-sourcing required on safety-critical
> parts, supplier2's volume discount kicks in at 10,000 units, no supplier
> above 30% of total spend, and supplier7 needs $50k of tooling if you use them.

P2CLPFD solves this in seconds. A spreadsheet can't.

### Pharmaceuticals:

> 12 active pharmaceutical ingredients, 8 qualified manufacturers. Each has a
> quality score that adjusts the effective unit cost. Some plants are capacity-
> constrained. Regulatory rules require at least 2 sources per API.

Fold quality into the objective. The solver trades off price against quality
across the entire portfolio — not per part in isolation.

### Electronics:

> 80 components, 15 suppliers across 3 regions. Different logistics costs per
> region. Tiered pricing on 6 high-volume parts. Minimum 3 suppliers per
> critical component. Supply chain resilience means capping any single
> supplier at 25% of total volume.

A single CSV file, a single `solve()` call, and you have the optimal award.

### Construction / CAPEX:

> 200 line items, each with 3-5 bidders. Volume discounts, fixed mobilization
> costs, and a requirement to keep the supply base manageable (max 2-3
> bidders per category).

The solver can decide whether paying a $50k mobilization charge is worth the
lower unit price — automatically.

### Beyond procurement:

Any resource allocation problem with the same structure:
- Distributing production across factories (capacity, cost, risk)
- Allocating marketing spend across channels (budget, ROI, diversification)
- Staff scheduling across shifts (availability, cost, fairness)

The engine is domain-agnostic. If you can express a constraint, it can enforce it.

## How it works

### You bring the data

A single CSV — one row per supplier-part pair. Columns for demand, price,
capacity, MOQ, share bounds, risk rules, and more.

### You define the rules

Every procurement constraint gets expressed as a declarative rule:

| Rule | Example |
|---|---|
| **Demand** | "part1 needs 250 units total" |
| **Capacity** | "supplier2 can only make 150 of part1" |
| **MOQ** | "supplier2 won't take less than 75 units" |
| **Share bounds** | "supplier2 must hold 30-70% of part1" |
| **Volume discount** | "supplier1 charges $100 under 40 units, $40 above" |
| **Fixed cost** | "supplier1 needs $2,000 tooling if awarded" |
| **Dual-source** | "part1 must come from at least 2 suppliers" |
| **Supply base cap** | "part2 at most 2 suppliers" |
| **Global share** | "no supplier above 40% of total volume" |
| **Quality** | "supplier2 has a +3 logistics penalty per unit" |

### You get the optimal award

```
Part: part1
  supplier2: 75 units  (unit: 13, subtotal: 975)
  supplier3: 175 units  (unit: 45, subtotal: 7875)

Part: part2
  supplier2: 113 units  (unit: 33, subtotal: 3729)
  supplier3: 107 units  (unit: 65, subtotal: 6955)

*** Total Cost of Ownership: 19,534 ***
```

The dual-source rule forced part1 to split across two suppliers. The global
share cap (40%) stopped supplier2 from taking more volume. The resulting TCO
is higher than if you ignored these rules — but that's the point: the solver
tells you the *real* cost of your sourcing policy.

### You run what-if scenarios

```python
results = s.compare_scenarios([
    {"name": "current policy",  "overrides": []},
    {"name": "relax share cap", "overrides": [
        {"remove": "max_global_share(supplier2,_)"}
    ]},
    {"name": "+10% on supplier2", "overrides": [
        {"cost_delta": ["supplier2", "part1", 10]}
    ]},
])
```

```
           current policy: 19,534
          relax share cap: 13,742  (-5,792, -30%)
        +10% on supplier2: 19,609  (+75, +0%)
```

This answers the questions your stakeholders actually ask: *"What if we drop
the dual-source rule?"* → saves 5,792. *"What if supplier2 raises prices?"* →
costs 75 more. The numbers are exact because the solver is exact.

## Getting started

### Python

```python
from p2clpfd import Solver

s = Solver()
s.load_csv("quotes.csv")
result = s.solve()
print(f"Optimal TCO: {result['tco']}")

for alloc in result["allocations"]:
    for sup in alloc["suppliers"]:
        print(f"  {alloc['part']} -> {sup['supplier']}: {sup['qty']} units")
```

### Command line

```bash
swipl -q -g run -g halt main.pl
```

### MCP server (Claude Desktop, Cursor, agents)

```bash
p2clpfd-mcp
```

Add to Claude Desktop config:

```json
{
  "mcpServers": {
    "p2clpfd": { "command": "p2clpfd-mcp" }
  }
}
```

The agent can then call `solve_allocation`, `compare_scenarios`, and
`validate_data` as native tools — no swipl or CLI knowledge needed.

### HTTP API (for agents and integrations)

```bash
swipl -g "['main.pl','json_api.pl'], server(8080), thread_get_message(_)" &
curl -s -X POST localhost:8080/solve \
  -H "Content-Type: application/json" \
  -d '{"csv_path":"sample.csv"}'
```

## CSV format

One row per supplier-part pair. All quantities are absolute integers. Empty
cells mean "no constraint" (unlimited / 0 / unrestricted).

| Column | Required | Description |
|---|---|---|
| `part` | yes | Part name |
| `supplier` | yes | Supplier name |
| `demand` | yes | Total demand for this part |
| `unit_cost` | yes | Unit price |
| `capacity` | no | Max this supplier can provide of this part |
| `moq` | no | Minimum order quantity |
| `share_min` | no | Min % of part demand this supplier must win |
| `share_max` | no | Max % of part demand this supplier may win |
| `noncost_adj` | no | Per-unit TCO adjustment (±) |
| `fixed_cost` | no | One-time charge when awarded |
| `min_suppliers` | no | Part must have at least N suppliers |
| `max_suppliers` | no | Part may use at most N suppliers |
| `dual_source` | no | Shorthand: at least 2 suppliers |
| `global_capacity` | no | Supplier's total across all parts |
| `global_share_cap` | no | Supplier may not exceed % of total volume |

Suppliers are auto-discovered from the data — no separate declaration needed.

## Validation

P2CLPFD checks your data before solving:

```python
s.validate()
# ✓ tier coverage continuous
# ✓ MOQ ≤ capacity
# ✓ every priced part has demand
# ✓ share bounds in [0, 100]
```

## Documentation

- [INSTALL.md](INSTALL.md) — installation (macOS, Linux, Conda, Docker)
- [TECHNICAL.md](TECHNICAL.md) — architecture, constraint modeling deep dive, full API reference

## License

GPLv3. Copyright (c) 2023 Ahmed Khalil Hafsi.
