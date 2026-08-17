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

## The judgment layer

The solver answers *"what is the cheapest legal award?"*. That is a mathematical
fact, and it is never wrong. But it is not the question a buyer actually has.

A bare number can't tell you whether the data was fit to decide on, whether you
are about to hand one supplier 76% of your spend, or which of a dozen constraints
is the one worth a phone call. So P2CLPFD reads its own output:

```bash
p2clpfd advise quotes.csv
```

```
Verdict
=======
The cheapest legal award costs 19,534. Before signing: spend is concentrated —
supplier3 would hold 75.9% of it (14,830), which is a lot of leverage to give
one supplier.

What to look at
===============
 ! Spend is concentrated — supplier3 would hold 75.9% of it (14,830), which is
   a lot of leverage to give one supplier.
   Loosening the share cap on supplier2 to 41 would save 128 (0.7% of total
   cost) — this is where negotiation pays.
```

Every finding carries a severity, the numbers behind it, and a sentence written
for a buyer rather than a solver. It will tell you when a constraint is *not*
worth negotiating, and when a model is infeasible it names the rule to relax
instead of just reporting failure.

## Getting started

### Command line

```bash
p2clpfd advise quotes.csv          # award + what to do about it
p2clpfd solve quotes.csv           # just the cheapest legal award
p2clpfd validate quotes.csv        # is this data fit to decide on?
p2clpfd sensitivity quotes.csv     # where should I negotiate?
p2clpfd multiperiod quotes.csv     # allocate across periods
p2clpfd scenarios quotes.csv --scenario no_cap:'[{"remove":"dual_source(part1)"}]'
```

Every command takes `--json` for scripting, and exit codes are meaningful
(`0` success, `1` no feasible award or validation error, `2` bad input):

```bash
p2clpfd solve quotes.csv --json | jq .tco
```

### MCP server (Claude Desktop, Cursor, agents)

```json
{
  "mcpServers": {
    "p2clpfd": { "command": "p2clpfd-mcp" }
  }
}
```

Eight tools, no swipl or CLI knowledge needed:

| Tool | Answers |
|---|---|
| `get_advice` | *What should I do?* — start here |
| `solve_allocation` | *What is the cheapest legal award?* |
| `validate_data` | *Is this data fit to decide on?* |
| `analyze_sensitivity` | *Where should I negotiate?* |
| `compare_scenarios` | *What if?* |
| `solve_multiperiod` | *How do I phase this across quarters?* |
| `list_disqualified` | *Why isn't supplier X in the award?* |
| `solve_trace` | *How did the solver get there?* |

### Python

```python
from p2clpfd import Solver

s = Solver()
s.load_csv("quotes.csv")

result = s.solve()
print(f"Optimal TCO: {result['tco']}")

advice = s.advise()          # verdict + ranked findings
for finding in advice["findings"]:
    print(finding["severity"], finding["say_to_user"])
```

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

### Qualification gates

These **disqualify** rather than penalise: a supplier that fails is removed
before price is considered, and no cost advantage can buy their way back in.
Missing performance data also disqualifies — an unknown record is not a passing
record.

| Column | Description |
|---|---|
| `otif` | Supplier's on-time-in-full delivery % |
| `min_otif` | Global gate: below this, disqualified everywhere |
| `lead_time` | Quoted lead time for this part+supplier (days) |
| `max_lead_time` | Per-part gate on lead time |
| `certifications` | Supplier's certs, semicolon-separated (`iso9001;iatf16949`) |
| `required_certs` | Per-part required certs, semicolon-separated |

### Landed cost, rebates, routes, periods

| Column | Description |
|---|---|
| `region` | Supplier's region (`apac`, `eu`, `local`, …) |
| `fx_rate` | FX multiplier as integer % for that region (`105` = +5%) |
| `logistics_cost` | Per-unit freight/customs for that region |
| `rebate_threshold` | Units across all parts needed to earn a rebate |
| `rebate_pct` | % off that supplier's **entire** spend once earned |
| `route` | Group name for a shared corridor (`hormuz`, `atlantic`, …) |
| `route_capacity` | Ceiling on that route's **combined** volume |
| `route_share_cap` | That route's combined volume as a max % of demand |
| `period` | Period number; `demand`/`capacity` then apply to that period |
| `holding_cost` | Per-unit-per-period cost of carrying inventory |

Landed unit cost is `invoice × fx ÷ 100 + logistics`, so the solver optimizes
cost **to your dock**, not invoice price. A route caps a *set* of suppliers at
once — the thing a shipping chokepoint or a single border crossing actually is,
which no per-supplier cap can express.

## Validation

P2CLPFD checks your data before solving, and says what it found in plain
language rather than solver jargon:

```bash
p2clpfd validate quotes.csv
```

```
Validation — Do not trust a result from this data until it is fixed.
  [error] Supplier alpha requires a minimum order of 80 on widget but can only
          make 50, so they can never be used.
  [error] Qualified suppliers for widget can supply 80 units in total but 100
          are needed.
```

Checks cover price-break gaps, MOQ above capacity, missing prices or demand,
share bounds that cannot sum to demand, capacity below demand, and suppliers
removed by qualification gates. Status is `error` (the answer would be wrong or
impossible), `warning` (looks unintended), or `ok`.

## Documentation

- [INSTALL.md](INSTALL.md) — installation (macOS, Linux, Conda, Docker)
- [TECHNICAL.md](TECHNICAL.md) — architecture, constraint modeling deep dive, full API reference

## License

GPLv3. Copyright (c) 2023 Ahmed Khalil Hafsi.
