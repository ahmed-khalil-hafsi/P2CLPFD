# P2CLPFD Roadmap

Living document of what's done and what's next.

---

## Shipped

| Phase | Feature | Status |
|---|---|---|
| Core | Multi-part × multi-supplier CLP(FD) solver, optimal TCO | ✓ |
| Core | Volume-based tiered pricing (element/3 + reified bounds) | ✓ |
| 1a | Fixed costs (NRE/tooling/setup, on/off decision variable) | ✓ |
| 1b | Risk & dual-sourcing (min/max suppliers, dual_source, global share cap) | ✓ |
| 1c | Scenario comparison (what-if with transactional save/restore) | ✓ |
| 2a | CSV / spreadsheet loader | ✓ |
| — | JSON HTTP API (POST /solve, /scenarios, /validate, GET /health) | ✓ |
| — | MCP server (stdio JSON-RPC for Claude, Cursor, any agent) | ✓ |
| — | Python package (`pip install p2clpfd`, `p2clpfd-mcp`) | ✓ |
| — | PlUnit test suite (26/26 pass) | ✓ |
| — | Validation guards (tier gaps, MOQ > capacity, missing facts) | ✓ |
| — | Documentation split (README business, INSTALL, TECHNICAL) | ✓ |

---

## Remaining roadmap

### 2b. Lead time, OTIF, and quality as hard constraints

Today, quality is a *soft* adjustment — a supplier with a -5 credit looks cheaper than
one with a +3 penalty, but neither is disqualified.

Real procurement has hard rules:

- "Supplier must have ≥ 95% OTIF to even be considered."
- "Part1 lead time must be ≤ 30 days — non-negotiable."
- "Supplier must have ISO 9001 certification."

These are *disqualification* constraints, not cost adjustments. If a supplier fails,
their Q is forced to 0 — no amount of cost advantage can override it.

**Modeling:** `B #= 0` when `otif < Threshold` — the active variable is pinned to 0,
making the pair non-allocatable regardless of price.

**Business value:** The solver doesn't just optimize for cost — it respects your
supplier qualification criteria as hard gates.

---

### 2c. Sensitivity & shadow prices

Once you have the optimal award, the next question is: *"Where should I negotiate?"*

- "Another 100 units of supplier2 capacity saves $X."
- "Relaxing the MOQ on supplier3/part1 from 75 to 50 saves $Y."
- "The global share cap on supplier2 is **binding** — it's the constraint that's
  costing you money."

This is called **sensitivity analysis** — find the binding constraints and compute
their marginal value. A shadow price tells you exactly how much a relaxed constraint
would save.

**Implementation:** Re-solve with each constraint relaxed by one unit, compute delta.
Or report which constraints have slack > 0 vs slack = 0.

**Business value:** Turns the solver from "here's the best allocation" into "here's
where you should focus your negotiation effort." This is what a chief procurement
officer actually wants to see.

---

### 3a. Multi-period allocation

Today, the solver assumes all demand is for a single period. But real sourcing spans
quarters:

- "Part1: 500 units in Q1, 800 in Q2, 300 in Q3."
- "Supplier2's capacity is 200/month, not 600/quarter."
- "We can buy ahead and carry inventory at $2/unit/month holding cost."
- "Some suppliers offer lower prices for committed volume across all periods."

The solver would allocate per-period quantities, enforce per-period capacity, and
allow inventory carryover between periods. The TCO includes holding cost.

**What changes:**
- `demand(Part, Period, Qty)` — demand varies over time
- `capacity(Supplier, Part, Period, MaxQty)` — capacity per period (optional)
- Inventory carryover variables: `inventory(Part, Period) = inventory(prev) + produced - demand`
- Holding cost in objective

**Business value:** Avoids the common mistake of optimizing per-quarter in isolation,
which often leads to stockouts or overproduction in adjacent periods.

---

### 3b. Rebate / retrospective pricing

Today's tiered pricing is per-part: "supplier1 charges $100 for 0-39 units of part1,
$40 for 40+." But real procurement has *portfolio-level* rebates:

- "If total volume across all parts exceeds 10,000 units, get 5% off everything."
- "Grow-the-business rebate: 3% if you give supplier2 > 50% of total spend."

These are **retrospective** — the discount applies to the entire award, not just the
marginal units above the threshold. And they're **cross-part** — the threshold
aggregates volume across all parts.

**Modeling:** Reified constraint: `TotalVolume >= Threshold #<==> RebateApplied = 1`.
If applied, entire supplier TCO gets discounted by Pct%. This creates a non-linear
step in the objective, which CLP(FD) handles via reification.

**Business value:** Captures the supplier's actual commercial offer. Without this,
you're leaving money on the table because the solver can't see the rebate.

---

### 3c. Exchange rate & logistics cost by region

Today's non-cost adjustments (`noncost_adjustment/2`) are flat per-supplier. But
real global sourcing has:

- "Supplier1 is in China, logistics cost is $3/unit."
- "Supplier2 is in Germany, logistics is $1/unit but FX adds 5%."
- "Supplier3 is local, no logistics, no FX."

The effective unit cost becomes: `UnitCost * FX_Rate + LogisticsCost`.

**What changes:**
- `region(Supplier, Region)` — supplier's geographic region
- `fx_rate(Region, Multiplier)` — exchange rate factor
- `logistics_cost(Region, PerUnit)` — freight/customs per unit

All folded into the effective unit cost before the objective is computed.

**Business value:** Enables landed-cost optimization — the solver compares suppliers
on *total cost to your dock*, not just invoice price.

---

## Technical debt

- Add `load.pl` single entry point (loads facts + solver + csv_loader + scenarios + json_api + tests)
- NEVER use `forall/2` to post CLP(FD) constraints — use direct recursion
