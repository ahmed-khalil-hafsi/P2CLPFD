# P2CLPFD Roadmap

Living document of what's done and what's next. Updated as features ship.

## Current capabilities (as of step 2 — tiered pricing)

### Allocation engine
- Multi-part × multi-supplier optimization in a single solve
- Continuous integer quantities (no fixed percentage grid)
- Provably optimal TCO via `labeling([min(TCO)], Vars)` — first solution is the optimum
- Cost ceiling via `solve/3` (MaxCost bound)
- Generalized N×M via `findall`-free unification-based variable extraction

### Constraints enforced
- Demand fulfillment (exact, per part)
- Per-pair capacity (`capacity/3`)
- Minimum order quantity — gap domain `Q in 0 \/ Moq..sup` (`moq/2`)
- Sourcing strategy — share bounds as % of demand (`share/4`)
- Global supplier capacity across all parts (`global_capacity/2`)

### Pricing models
- Flat unit pricing (`cost/3`)
- Volume-based tiered pricing (`price_tier/5`) — `element/3` + reified `#==>` bounds; solver picks optimal tier
- Non-cost TCO adjustments (`noncost_adjustment/2`) — quality, logistics, risk premium

### Output & trust
- Pretty-printed allocation with raw + effective unit costs and subtotals
- Built-in verification: demand, MOQ, capacity, share, global cap, TCO recomputation, tier membership

---

## Prioritized roadmap

### Phase 1 — Decision-support essentials

**1a. Fixed costs (NRE / tooling / setup)** — DONE

- New fact: `fixed_cost(Supplier, Part, Amount)` — one-time charge if awarded > 0
- Modeling: on/off decision variable `B in 0..1` per pair, reified `Q #>= 1 #<==> B #= 1`, contribution `B * Amount` added to TCO
- Effect: lets solver decide whether an award is worth the setup cost (e.g. $5k tooling to unlock a cheaper unit price)
- Pairs without `fixed_cost/3` have B forced to 0 (no fixed cost)

**1b. Risk & dual-sourcing rules** — DONE

- New facts:
  - `min_suppliers(Part, N)` — part must be split across ≥ N suppliers
  - `max_suppliers(Part, N)` — part may use at most N suppliers
  - `max_global_share(Supplier, Pct)` — no supplier above Pct of total volume across all parts
  - `dual_source(Part)` — shorthand for `min_suppliers(Part, 2)`
- Modeling: per-pair on/off `B` vars (shared with 1a), `sum(Bs, #>=, N)` / `#=< N`
- Effect: captures real sourcing-policy rules ("no single-source risk", "diversify top 3 suppliers")
- Note: `forall/2` must NOT be used for CLP(FD) constraint posting — its negation-as-failure swallows constraints. Use direct recursion instead.

**1c. Scenario comparison** — DONE

- `solve_scenario(+Overrides, -Allocation, -TCO)` — applies overrides temporarily via `setup_call_cleanup/3`, solves, restores
- `compare_scenarios(+Scenarios, -Results)` — batch comparison with delta output
- `print_comparison(+Results)` — formatted table with TCO, status, and delta vs baseline
- Overrides: `set(Fact)`, `remove(Template)`, `cost_delta(Supplier, Part, Pct)`, `demand_delta(Part, Pct)`
- Effect: category manager asks "what if supplier2 +10%?" and gets a clean diff

### Phase 2 — Realism & integrations

**2a. CSV / spreadsheet loader** — DONE

- `load_csv(+Path)` — reads a flat CSV into facts
- Single CSV with all columns: part, supplier, demand, unit_cost, capacity, moq, share_min, share_max, noncost_adj, fixed_cost, min_suppliers, max_suppliers, dual_source, global_capacity, global_share_cap
- `load_and_run(+Path)` convenience predicate in main.pl
- Per-part and per-supplier attributes deduplicated across rows
- Effect: a category manager (or AI agent) drops a spreadsheet; no Prolog editing

**2b. Lead time / OTIF / quality as hard constraints** — NEXT

- New facts: `leadtime(Supplier, Part, Days)`, `otif(Supplier, Pct)`, `quality(Supplier, Score)`
- New constraints: `otif(Supplier, Pct), Pct >= Threshold` (disqualify), or `leadtime #=< MaxDays`
- Effect: "disqualify suppliers below 95% OTIF" or "part1 lead time ≤ 30 days"

**2c. Sensitivity / shadow prices** — MEDIUM

- Report the binding constraints and their marginal value ("another 100 units of supplier2 capacity saves $X")
- Implementation: re-solve with relaxed constraint, compute delta; or extract from CLP(FD) propagator state
- Effect: answers "where should I negotiate more capacity?"

### Phase 3 — Advanced modeling

**3a. Multi-period allocation** — LOW

- `demand(Part, Period, Qty)` — demand varies over time
- Inventory carryover variables, holding cost in objective
- Effect: smooths awards across quarters with seasonal demand

**3b. Rebate / retrospective pricing** — LOW

- `rebate(Supplier, Threshold, Pct)` — if total volume across all parts exceeds Threshold, get Pct rebate on everything
- Modeling: global supplier total vs threshold, reified rebate application
- Effect: captures "grow-the-business" rebate tiers that span parts

**3c. Exchange rate & logistics cost by region** — LOW

- `region(Supplier, Region)`, `fx_rate(Region, Rate)`, `logistics_cost(Region, PerUnit)`
- Folded into effective unit cost
- Effect: landed-cost optimization across geographies

---

## Technical debt (to clean up along the way)

- Delete `volume_based_pricing.pl` (superseded by `price_tier/5`)
- Delete `CLPFD-general.pl` (superseded by `solver.pl`)
- Add `tests.pl` regression suite: known-feasible, infeasible, unbounded, tier-boundary, MOQ-gap, share-binding cases
- Add `load.pl` single entry point
- Guard against incomplete tier coverage (validation predicate: `validate_tiers/0`)
- Guard against MOQ > capacity (immediate infeasibility detection)
- NEVER use `forall/2` to post CLP(FD) constraints — use direct recursion or `maplist` instead
