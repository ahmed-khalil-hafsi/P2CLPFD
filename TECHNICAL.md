# Technical Documentation

## Architecture

```
  facts.pl / CSV  ──>  csv_loader  ──>  solver  ──>  Allocation + TCO
  (your data)          (parse)         (optimize)     (verified)
```

P2CLPFD is built on SWI-Prolog's CLP(FD) (Constraint Logic Programming over
Finite Domains) library. The solver models procurement allocation as a
finite-domain optimization problem with guaranteed optimality.

### Files

| File | Purpose |
|---|---|
| `facts.pl` | Procurement data as Prolog facts |
| `sample.csv` | Same data in CSV format |
| `csv_loader.pl` | CSV parser → facts |
| `solver.pl` | CLP(FD) optimization engine + verifier |
| `scenarios.pl` | What-if scenario comparison |
| `json_api.pl` | JSON conversion + HTTP server |
| `tests.pl` | Test suite (20 tests) |
| `main.pl` | Entry point (loads everything) |
| `p2clpfd/` | Python package (janus-swi wrapper) |

## Constraint modeling

### Decision variables

One finite-domain variable `Q` per `(Part, Supplier)` pair, representing the
quantity allocated to that supplier for that part. Domain: `0..Demand`.

Additionally, a binary variable `B` per pair (0 or 1) represents "is this
pair active?" via reification: `B #= 1 #<==> Q #>= 1`.

### Constraints

```
  DEMAND          PRICING           SOURCING        RISK
  ┌──────┐       ┌──────────┐      ┌────────┐     ┌────────┐
  │ Q1+Q2│       │ Flat     │      │ Share  │     │ Dual   │
  │ =D   │       │ Tiered   │      │ Min/Max│     │ Min/Max│
  │      │       │ Fixed    │      │  %     │     │ Supply │
  └──┬───┘       │ Non-cost │      └───┬────┘     └───┬────┘
     │           └─────┬────┘          │              │
     └────────┬────────┴───────────────┘──────────────┘
              v
     ┌────────────────┐
     │  CLP(FD) Solver │  labeling([min(TCO)])
     └───────┬────────┘
             v
     ┌────────────────┐
     │  Optimal TCO   │
     └────────────────┘
```

| Constraint | How it's modeled |
|---|---|
| **Demand** | `sum(Qs, #=, Demand)` — exact fulfillment per part |
| **Capacity** | `Q #=< Cap` per pair |
| **MOQ** | `Q in 0 \/ Moq..sup` — gap domain: either 0 or ≥ MOQ |
| **Share** | `MinPct * Demand #=< 100 * Q` and `100 * Q #=< MaxPct * Demand` |
| **Global capacity** | `sum(SupplierQs, #=, Total)`, `Total #=< Cap` |
| **Fixed costs** | `B #= 1 #<==> Q #>= 1`, cost += `B * Amount` |
| **Min/max suppliers** | `sum(Bs, #>=, N)` / `sum(Bs, #=<, N)` per part |
| **Global share** | `100 * SupplierTotal #=< Pct * TotalDemand` |

### Tiered pricing

Uses `element/3` + reified `#==>` constraints:

```prolog
TierVar in 1..N,
element(TierVar, [Cost1, Cost2, ...], RawUnitCost),
TierVar #= i #==> Q #>= Min_i,
TierVar #= i #==> Q #=< Max_i,
CostC #= Q * (RawUnitCost + NonCostAdjustment)
```

The solver picks the optimal tier as part of the optimization — no
post-calculation or manual lookup.

### Objective

`TCO = Σ (Q * EffectiveUnitCost + B * FixedCost)` per pair, minimized via
`labeling([min(TCO)], Vars)`.

### Verification

Every solution is checked against all constraints after labeling:
- Demand sum matches
- MOQ respected (0 or ≥ MOQ)
- Capacity not exceeded
- Share within bounds
- Global capacity respected
- Risk constraints (supplier count)
- Global share cap
- TCO recomputed independently

## Python API

```python
from p2clpfd import Solver

s = Solver()
s.load_csv("quotes.csv")

# Solve
result = s.solve()
# {"tco": 19534, "status": "ok", "allocations": [...]}

# Solve with cost ceiling
result = s.solve(max_cost=15000)  # None if infeasible

# What-if scenarios
results = s.compare_scenarios([
    {"name": "baseline", "overrides": []},
    {"name": "price_up", "overrides": [
        {"cost_delta": ["supplier2", "part1", 10]}
    ]},
    {"name": "no_risk", "overrides": [
        {"remove": "dual_source(part1)"},
        {"remove": "max_global_share(supplier2,_)"}
    ]},
])
# {"results": [...], "deltas": [...]}

# Validate facts
s.validate()
# {"status": "ok"}
```

### Override types

| Type | Format | Effect |
|---|---|---|
| `set` | `{"set": "cost(supplier1,part1,50)"}` | Replace a fact |
| `remove` | `{"remove": "dual_source(part1)"}` | Remove all matching facts |
| `cost_delta` | `{"cost_delta": ["supplier2", "part1", 10]}` | Adjust price by +10% |
| `demand_delta` | `{"demand_delta": ["part1", 10]}` | Adjust demand by +10% |

## HTTP API

Start the server:

```bash
swipl -g "['main.pl','json_api.pl'], server(8080), thread_get_message(_)" &
```

### POST /solve

```bash
curl -s -X POST localhost:8080/solve \
  -H "Content-Type: application/json" \
  -d '{"csv_path":"sample.csv","max_cost":20000}'
```

Response:
```json
{
  "tco": 19534,
  "status": "ok",
  "allocations": [
    {"part":"part1","suppliers":[
      {"supplier":"supplier2","qty":75,"unit_cost":13,"subtotal":975},
      {"supplier":"supplier3","qty":175,"unit_cost":45,"subtotal":7875}
    ]}
  ]
}
```

### POST /scenarios

```bash
curl -s -X POST localhost:8080/scenarios \
  -H "Content-Type: application/json" \
  -d '{"csv_path":"sample.csv","scenarios":[
    {"name":"baseline","overrides":[]},
    {"name":"no_cap","overrides":[{"remove":"max_global_share(supplier2,_)"}]}
  ]}'
```

Response:
```json
{
  "results": [
    {"name":"baseline","status":"ok","tco":19534},
    {"name":"no_cap","status":"ok","tco":13742}
  ],
  "deltas": [
    {"name":"no_cap","delta":-5792,"pct":-30}
  ]
}
```

### POST /validate

```bash
curl -s -X POST localhost:8080/validate \
  -H "Content-Type: application/json" \
  -d '{"csv_path":"sample.csv"}'
```

### GET /health

```bash
curl -s localhost:8080/health
```

## Prolog API

```prolog
?- ['main.pl'].

?- solve(A, TCO).                      % optimal allocation
?- solve(A, TCO, 15000).               % with cost ceiling
?- solve(A, TCO), print_allocation(A, TCO).  % pretty-print + verify
?- validate_facts.                     % validate loaded facts

?- compare_scenarios([
|    baseline-[],
|    price_up-[cost_delta(supplier2, part1, 10)],
|    no_risk-[remove(dual_source(part1)), remove(max_global_share(supplier2, _))]
|  ], Results), print_comparison(Results).

?- load_csv('data.csv'), run.          % load CSV then solve
```

## Fact schema

All quantities are absolute integers.

| Fact | Meaning |
|---|---|
| `demand(Part, Qty)` | Total quantity of Part to source. |
| `cost(Supplier, Part, UnitCost)` | Flat unit price. |
| `price_tier(Supplier, Part, MinQty, MaxQty, UnitCost)` | Volume-based tiered pricing. Use `sup` for unbounded `MaxQty`. |
| `capacity(Supplier, Part, MaxQty)` | Per-pair maximum. Absent = unlimited. |
| `moq(Supplier, Part, MinQty)` | Minimum order quantity. Absent = 0. |
| `share(Part, Supplier, MinPct, MaxPct)` | Strategy bounds as % of demand. |
| `global_capacity(Supplier, MaxQty)` | Total across all parts. |
| `noncost_adjustment(Supplier, Adj)` | Per-unit TCO adjustment. |
| `fixed_cost(Supplier, Part, Amount)` | One-time charge when Q > 0. |
| `min_suppliers(Part, N)` | Minimum supplier count. |
| `max_suppliers(Part, N)` | Maximum supplier count. |
| `dual_source(Part)` | Shorthand for min_suppliers = 2. |
| `max_global_share(Supplier, Pct)` | Cap on % of total volume. |

## Testing

```bash
swipl -q -g run_tests -g halt main.pl tests.pl
```

```
=== Running Tests ===

  PASS: basic_feasible
  PASS: basic_demand_met
  PASS: basic_optimal_tco
  PASS: infeasible_no_capacity
  ...
=== Results: 20/20 passed, 0 failed ===
```

## Known limitations

- `forall/2` must NOT be used to post CLP(FD) constraints — its negation-as-failure swallows them. Use direct recursion instead.
- Full solution enumeration (`findall(TCO, solve(_,TCO), L)`) without `MaxCost` can be slow on large search spaces. Use `solve/2` for the optimum or `solve/3` with a ceiling.
- Tiered pricing is not yet supported via CSV — use `facts.pl` for that.
