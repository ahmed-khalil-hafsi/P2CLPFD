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

P2CLPFD answers one question: **given a set of parts, a set of suppliers, and your business rules — what is the cost-optimal award?**

It minimizes Total Cost of Ownership (TCO) while respecting every constraint you define. Every solution is verified against all constraints before it is returned.

## Who it's for

Category managers, sourcing leads, and procurement teams who need to:
- Split demand across multiple suppliers optimally
- Respect sourcing policies (dual-source, capacity caps, share limits)
- Compare what-if scenarios before committing to an award
- Get provably optimal results, not heuristic guesses

## What you can model

### Demand & supply
- **Multi-part, multi-supplier allocation** in a single optimization run
- **Continuous quantities** — any integer, not locked to fixed percentage steps
- **Per-pair capacity** — "supplier3 can only make 800 of part1"
- **Global supplier capacity** — "supplier2 cannot exceed 1000 units total"

### Minimum order quantities
- **MOQ per supplier-part pair** — either award 0 or at least the MOQ

### Pricing
- **Flat unit pricing** — a single price per supplier-part pair
- **Volume-based tiered pricing** — "supplier1 charges $100 for 0–39 units, $40 for 40+"
- **Non-cost adjustments** — fold quality, logistics, or risk premiums into the objective
- **Fixed costs (NRE / tooling / setup)** — "supplier1 needs $2000 tooling if awarded"

### Sourcing strategy
- **Per-part share bounds** — "supplier2 must hold 30–70% of part1"
- **Dual-sourcing** — "part1 must have at least 2 suppliers"
- **Min/max supplier count** — "part2 may use at most 2 suppliers"
- **Global share cap** — "no supplier may exceed 40% of total volume"

### Scenario comparison
- **What-if analysis** — run scenarios with temporary overrides without mutating base facts
- **Override types**:
  - `set` — replace a fact (e.g. change a price)
  - `remove` — remove a constraint (e.g. drop dual-source rule)
  - `cost_delta` — adjust price by percentage
  - `demand_delta` — adjust demand by percentage
- **Batch comparison** — compare multiple scenarios side-by-side with TCO deltas

### Output & verification
- **Pretty-printed allocation** with per-supplier quantities, unit costs, fixed costs, and subtotals
- **Built-in verification** — every solution is checked against all constraints

## Quick start

### Python

```python
from p2clpfd import Solver

s = Solver()
s.load_csv("quotes.csv")
result = s.solve()
print(f"TCO: {result['tco']}")

# With cost ceiling
result = s.solve(max_cost=15000)  # None if infeasible

# What-if scenarios
results = s.compare_scenarios([
    {"name": "baseline", "overrides": []},
    {"name": "no_cap", "overrides": [
        {"remove": "max_global_share(supplier2,_)"}
    ]},
])
for r in results["results"]:
    print(f"  {r['name']}: TCO={r['tco']}")
```

### Command line

```bash
swipl -q -g run -g halt main.pl
```

## Define your data

A single flat CSV with one row per supplier-part pair. All quantities are absolute integers. Empty cells use the default (no constraint).

| Column | Required | Description | Default |
|---|---|---|---|
| `part` | yes | Part name | — |
| `supplier` | yes | Supplier name | — |
| `demand` | yes | Total demand for this part | — |
| `unit_cost` | yes | Unit price | — |
| `capacity` | no | Max this supplier can provide of this part | unlimited |
| `moq` | no | Minimum order quantity | 0 |
| `share_min` | no | Min % of part demand this supplier must win | 0 |
| `share_max` | no | Max % of part demand this supplier may win | 100 |
| `noncost_adj` | no | Per-unit TCO adjustment (quality, logistics, risk) | 0 |
| `fixed_cost` | no | One-time charge (NRE/tooling) when awarded | 0 |
| `min_suppliers` | no | Part must have at least N suppliers | — |
| `max_suppliers` | no | Part may use at most N suppliers | — |
| `dual_source` | no | Shorthand for min_suppliers = 2 | — |
| `global_capacity` | no | Supplier's total across all parts | unlimited |
| `global_share_cap` | no | Supplier may not exceed this % of total volume | — |

**Example CSV:**

```csv
part,supplier,demand,unit_cost,capacity,moq,share_min,share_max,noncost_adj,fixed_cost,min_suppliers,max_suppliers,dual_source,global_capacity,global_share_cap
part1,supplier1,250,100,1000,,0,30,0,2000,2,,1,5000,
part1,supplier2,250,10,150,75,30,70,3,,,,,1000,
part1,supplier3,250,50,800,,0,100,-5,,,,,5000,
```

## Example output

```
Part: part1
  supplier2: 75 units  (unit: 13, subtotal: 975)
  supplier3: 175 units  (unit: 45, subtotal: 7875)

Part: part2
  supplier2: 113 units  (unit: 33, subtotal: 3729)
  supplier3: 107 units  (unit: 65, subtotal: 6955)

*** Total Cost of Ownership: 19534 ***
```

The global share cap and dual-source requirement force a more balanced award. Without these constraints, the solver would concentrate volume on the cheapest supplier — which is often not what you want in practice.

## Documentation

- [INSTALL.md](INSTALL.md) — installation guide
- [TECHNICAL.md](TECHNICAL.md) — architecture, constraint modeling, and API reference

## License

GPLv3. Copyright (c) 2023 Ahmed Khalil Hafsi.
