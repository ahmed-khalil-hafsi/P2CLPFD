# P2CLPFD — Procurement Allocation Optimizer

A constraint-based allocation engine for procurement professionals. It
answers the question: **given N parts, M suppliers, and a set of business
rules, what is the cost-optimal award?**

The solver minimizes Total Cost of Ownership (TCO) while respecting every
constraint you define — capacity, sourcing strategy, risk policy, and
pricing structure. Every solution is verified against all constraints before
it is returned.

---

## What you can model

### Demand & supply

- **Multi-part, multi-supplier allocation.** Split demand for any number of
  parts across any number of suppliers in a single optimization run.
- **Continuous quantities.** The solver awards any integer quantity — not
  locked to fixed percentage steps. "Give supplier2 exactly 73 units" is a
  valid output.
- **Per-pair capacity.** Cap how much a specific supplier can provide of a
  specific part (e.g. "supplier3 can only make 800 of part1").
- **Global supplier capacity.** Cap a supplier's total volume across all
  parts (e.g. "supplier2 cannot exceed 1000 units total").

### Minimum order quantities

- **MOQ per supplier-part pair.** "Supplier2 won't take less than 75 units
  of part1." The solver either awards 0 or at least the MOQ — never an
  embarrassing 10-unit order that triggers a surcharge.

### Pricing

- **Flat unit pricing.** A single price per supplier-part pair.
- **Volume-based tiered pricing.** "Supplier1 charges $100 for 0–39 units,
  $40 for 40+." The solver picks the optimal tier as part of the
  optimization — no post-calculation or manual lookup.
- **Non-cost adjustments.** Fold quality, logistics, or risk premiums into
  the objective. "Supplier3 has a −5 quality credit, supplier2 a +3
  logistics penalty." The award reflects total cost of ownership, not just
  invoice price.
- **Fixed costs (NRE / tooling / setup).** "Supplier1 needs a $2000 tooling
  charge if we award them anything." The solver decides whether the unit
  price advantage justifies the setup cost.

### Sourcing strategy

- **Per-part share bounds.** "Supplier2 must hold 30–70% of part1" or
  "supplier1 may not exceed 30% of part1." Expressed as min/max percentages
  of a part's demand.
- **Dual-sourcing.** "Part1 must have at least 2 suppliers" — enforced as a
  hard constraint, not a soft preference.
- **Minimum / maximum supplier count.** "Part2 may use at most 2 suppliers"
  or "part3 must come from at least 3 suppliers."
- **Global share cap.** "No supplier may exceed 40% of total volume across
  all parts." Prevents over-reliance on a single source.

### Objective

- **TCO minimization.** The solver returns the provably optimal award — not
  a heuristic guess. First solution from `labeling([min(TCO)])` is the best.
- **Cost ceiling.** "Find the best award under $15,000" — the solver
  respects the budget or reports infeasibility.

### Output & verification

- **Pretty-printed allocation** with per-supplier quantities, unit costs
  (raw + effective), fixed costs, and subtotals.
- **Built-in verification.** Every solution is checked against all
  constraints — demand, MOQ, capacity, share, global capacity, risk rules,
  global share, and TCO recomputation — so you can hand the number to a
  stakeholder with confidence.

---

## Quick start

### Prerequisites

- [SWI-Prolog](http://www.swi-prolog.org/Download.html) (v9.x)

### Run

```bash
swipl -q -g run -g halt main.pl               % use built-in facts.pl
swipl -q -g "load_and_run('data.csv')" -g halt main.pl  % load from CSV
```

Or interactively:

```prolog
?- ['main.pl'].
?- run.                       % solve + pretty-print + verify
?- run(15000).                % solve with cost ceiling
?- load_and_run('data.csv').  % load CSV then solve
?- solve(A, TCO).             % raw solve
```

### Define your data

Two ways to provide data:

**Option A: Edit `facts.pl`** (for Prolog users)

**Option B: Prepare a CSV file** (for everyone else)

A single flat CSV with one row per supplier-part pair. All quantities are
absolute integers. Empty cells use the default (no constraint).

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

**Notes:**
- Each row must have exactly 15 fields (including empty ones).
- Per-part attributes (`min_suppliers`, `max_suppliers`, `dual_source`) may
  appear in any row of that part — the last non-empty value wins.
- Per-supplier attributes (`global_capacity`, `global_share_cap`) may appear
  in any row of that supplier.
- Tiered pricing (`price_tier`) is not yet supported via CSV — use `facts.pl`
  for that.

| What | Format | Example |
|---|---|---|
| Demand | `demand(Part, Qty).` | `demand(valve_bracket, 500).` |
| Unit cost | `cost(Supplier, Part, Price).` | `cost(acme, valve_bracket, 12).` |
| Tiered pricing | `price_tier(Supplier, Part, Min, Max, Price).` | `price_tier(acme, valve_bracket, 0, 99, 15).` |
| Per-pair capacity | `capacity(Supplier, Part, Max).` | `capacity(acme, valve_bracket, 300).` |
| MOQ | `moq(Supplier, Part, Min).` | `moq(acme, valve_bracket, 100).` |
| Share bounds | `share(Part, Supplier, MinPct, MaxPct).` | `share(valve_bracket, acme, 20, 60).` |
| Global capacity | `global_capacity(Supplier, Max).` | `global_capacity(acme, 2000).` |
| Non-cost adjustment | `noncost_adjustment(Supplier, Adj).` | `noncost_adjustment(acme, 3).` |
| Fixed cost | `fixed_cost(Supplier, Part, Amount).` | `fixed_cost(acme, valve_bracket, 2000).` |
| Min suppliers | `min_suppliers(Part, N).` | `min_suppliers(valve_bracket, 2).` |
| Max suppliers | `max_suppliers(Part, N).` | `max_suppliers(valve_bracket, 3).` |
| Dual-source | `dual_source(Part).` | `dual_source(valve_bracket).` |
| Global share cap | `max_global_share(Supplier, Pct).` | `max_global_share(acme, 40).` |

Suppliers are discovered automatically from the cost/price facts — no need
to declare them separately.

---

## Example

Three suppliers, two parts, tiered pricing on one pair, dual-sourcing
enforced on part1, and supplier2 capped at 40% of total volume:

```
Part: part1
  supplier2: 75 units  (unit: 13, subtotal: 975)
  supplier3: 175 units  (unit: 45, subtotal: 7875)

Part: part2
  supplier2: 113 units  (unit: 33, subtotal: 3729)
  supplier3: 107 units  (unit: 65, subtotal: 6955)

*** Total Cost of Ownership: 19534 ***
```

The global share cap and dual-source requirement force a more balanced
award. Without these constraints, the solver would concentrate volume on the
cheapest supplier — which is often not what you want in practice.

---

## Project layout

```
facts.pl       Your data — demand, prices, capacities, strategy rules
sample.csv     Example CSV (same data as facts.pl)
csv_loader.pl  CSV parser and fact loader
solver.pl      The optimization engine
main.pl        Entry point
```

## License

GPLv3. Copyright (c) 2023 Ahmed Khalil Hafsi.
