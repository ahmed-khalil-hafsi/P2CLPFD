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
| 2b | Hard qualification gates (OTIF, lead time, certifications) | ✓ |
| 2c | Sensitivity analysis (binding constraints + shadow prices) | ✓ |
| 3a | Multi-period allocation with inventory carryover | ✓ |
| 3b | Portfolio rebates (retrospective, cross-part) | ✓ |
| 3c | Exchange rate & logistics cost by region (landed cost) | ✓ |
| — | Route constraints (ceilings shared by a *set* of suppliers) | ✓ |
| — | Judgment layer (verdicts, risk, negotiation agenda, diagnosis) | ✓ |
| — | `p2clpfd` CLI (tables for humans, `--json` for agents) | ✓ |
| — | MCP server — 8 tools over stdio JSON-RPC | ✓ |
| — | JSON HTTP API (POST /solve, /scenarios, /validate, GET /health) | ✓ |
| — | Solver tracer (NDJSON trace + live WebSocket visualization) | ✓ |
| — | Python package (`pip install p2clpfd`) | ✓ |
| — | Problem decomposition (independent parts, rebate branch enumeration) | ✓ |
| — | Share grid (`share_increment`) — decouples solve time from quantity | ✓ |
| — | Scaling benchmark + chart (`scripts/benchmark.py`, `make_chart.py`) | ✓ |
| — | Slack-coupling shortcut — a cross-part rule that does not bite is free | ✓ |
| — | Structured validation with plain-language findings | ✓ |
| — | Test suite: 79 PlUnit + 61 Python (judgment unit + CLI/MCP integration) | ✓ |

---

## Remaining roadmap

### Split route-coupled problems when the rule actually bites

Partly addressed: a cross-part rule that does NOT constrain the answer is now
free, because the relaxed per-item solve is checked against it and accepted
when it already complies. That is what makes a 30% portfolio cap scale to
~1,550 items inside five minutes.

What remains is the case where the rule genuinely binds — a small catalogue
where one supplier would win most of it, or a route ceiling below what the
cheapest routing wants. Those still fall back to one monolithic search, and
[the benchmark](benchmarks/) shows them stalling at a handful of items.

Route ceilings are the pressing case, because the Strait of Hormuz case study
(`casestudy/`) is built on them and a chokepoint limit is binding by
construction — that is the whole point of the scenario, so the shortcut above
will never rescue it.

**Approach:** a route ceiling couples parts through a single scalar, the group
total. Enumerate or bisect on that total and, for each fixed value, the parts
separate again — the same trick that made rebates tractable. Lagrangian
relaxation on the coupling constraint is the more general version.

**Business value:** the geopolitical-risk case is the most interesting thing
this solver does, and it needs to run in seconds to be usable in a meeting.

---

### Finish the Hormuz case study

`casestudy/run_hormuz.pl` references a `casestudy/README.md` that does not
exist, and depends on the performance work above. Worth completing as the
worked example: three crude grades where the binding constraint is a shipping
chokepoint rather than any single supplier.

---

### Multi-period × the full constraint set

The multi-period model (3a) deliberately covers a v1 subset: flat costs,
capacity, MOQ, global capacity, holding cost, and the qualification gates. It
does **not** apply tiered pricing, rebates, share strategies, fixed costs, or
supplier-count rules.

Folding those in means either a much larger monolithic model or per-period
decomposition with the coupling handled explicitly — the same problem as above.

---

### Compute the per-item optimum instead of searching for it — under a guard

**Reinstated, but narrower than first written.** Dropped when `share_increment`
landed on the grounds that the grid superseded it; that was wrong, because the
grid removed *quantity* from the complexity and left the per-item constant
untouched. The first reinstatement then overstated the fix. Both corrected here.

Measured on one item — 4 suppliers, quad sourcing, 5% floor, 5% grid:

| | |
|---|---|
| candidate splits that exist | 969 |
| find a solution | 1.3 ms |
| **prove it optimal** | **104 ms** |

**Where greedy is exact.** With linear costs, share floors and ceilings, and
capacities, minimising a linear objective under one sum constraint and per-
variable bounds is solved exactly by "give everyone their floor, then give the
remainder to the cheapest supplier with room left". Property-tested against
CLP(FD) on random instances: **58 of 58 exact**.

**Where it is not — and it fails unsafely.** Supplier-count rules
(`min_suppliers`, `dual_source`, `max_suppliers`) are a subset-selection
problem, not a sorting problem, and greedy has no notion of them. On random
instances carrying `min_suppliers` it disagreed on **13 of 53**, and always in
the dangerous direction: it reported a cost BELOW the true optimum, because the
award it produced left too few suppliers active. That is a cheaper number for
an award you cannot place — the same failure class as the silent-wrong-answer
bugs fixed earlier.

**The guard that makes it safe.** Use the fast path only when the count rules
provably cannot bind:

- no `max_suppliers` (choosing which suppliers to drop is genuinely
  combinatorial), and
- no `min_suppliers`/`dual_source`, **or** enough suppliers carry a positive
  share floor that the count is already satisfied.

Plus the existing exclusions: no MOQ, no price tiers, no fixed costs — those
make the objective non-convex, which is precisely what CLP(FD) is for.

Property-tested: **52 of 52 exact among admitted instances, 31 of 83 rejected**
to the solver.

**What that leaves.** The guard admits the benchmark configuration (quad
sourcing where every supplier has a 5% floor, so the count is automatic) and
plain cheapest-wins models. It rejects `dual_source` with no share floors,
which is a common way to write a real model. So this is an optimisation for a
large subset, not a general answer — worth building, but it will not make every
model fast, and the guard must be checked before the fast path is entered,
never after.

**Open question worth testing before building:** greedy may be extendable to
`min_suppliers` by activating the cheapest inactive suppliers at the minimum
quantity and taking those units from the most expensive active one. That is an
exchange argument and looks right, but it is untested — do not ship it on the
strength of the argument alone.

---

### Make the share grid discoverable

`share_increment` is the single biggest performance lever — it takes a solve
from "cannot finish 400 units" to 0.32s at 20,000 — but a user only benefits
if they know to set it. The [benchmark](benchmarks/) quantifies both the win
and its cost (0.36% when the true optimum is off-grid).

**Approach:** have the judgment layer notice when a model is slow *and* has no
increment set, and say so — "awards here are unrestricted; if round-number
splits are acceptable, a 5% grid would make this instant." Validation could
also flag a per-item demand large enough that a solve will crawl.

---

### Sensitivity for multi-period and route constraints

`sensitivity.pl` detects binding constraints and prices them for the
single-period model. Multi-period plans have their own interesting shadow
prices (what is one more unit of Q2 capacity worth?), and route ceilings are
exactly the constraint a buyer most wants priced.

---

### The engine itself is the ceiling

Benchmarked against HiGHS (a purpose-built mixed-integer solver) on the
*identical* model, requiring the same proven optimum. Both engines returned
the same answer every time:

| model | items | CLP(FD) | HiGHS | gap |
|---|---|---|---|---|
| linear costs + share floors + grid | 100 | 13.4s | 0.004s | 3,384x |
| linear costs + share floors + grid | 500 | 76.0s | 0.017s | **4,539x** |
| + per-supplier fixed costs (binary activation) | 50 | 7.2s | 0.013s | 550x |
| + per-supplier fixed costs (binary activation) | 200 | 32.4s | 0.052s | 627x |

So the honest position: this is **not** a tool that is 90% optimised with a
little tuning left. Remaining CLP(FD)-side tuning is worth maybe 2-5x in total,
and the guarded greedy above ~100x on a subset. The engine gap is three orders
of magnitude, and it widens with problem size.

**Why.** A MIP solver evaluates an LP relaxation at every node, which yields a
tight global lower bound. That is exactly the expensive half here: on one item,
*finding* the answer takes 1.3ms and *proving* it optimal takes 104ms. LP
relaxation makes the proof nearly free. CLP(FD)'s interval propagation cannot
bound `sum(Q_i * c_i)` tightly, so branch-and-bound re-searches instead.

**Every feature in this tool is a textbook MIP construct**: MOQ is a
semi-continuous variable, price tiers are piecewise-linear (SOS2 or binaries),
fixed costs and rebates are binary plus big-M, min/max suppliers is a
cardinality constraint, route and global caps are plain linear rows, and
multi-period with inventory is classic lot-sizing. Supplier allocation *is* a
MIP problem; CLP(FD) is an unusual engine choice for it.

**What CLP(FD) is genuinely buying**, and would have to be paid for elsewhere:
no external solver dependency, the domain-narrowing tracer and its
explainability story, arbitrary logical constraints with no reformulation, and
a codebase that is already correct and covered by 79 + 61 tests.

**Suggested shape, not a rewrite.** Add a MIP backend for the mainstream case
and keep CLP(FD) as the reference implementation and cross-check — two
independent engines agreeing is a stronger correctness story than either alone.
Everything above the math layer (judgment, MCP, CLI, validation) is
engine-agnostic and would not change.

The second-order effect matters more than the raw speed: `sensitivity` re-solves
once per binding constraint, so at these ratios the whole judgment layer moves
from "expensive, run it deliberately" to "always on", and an agent can explore
twenty scenarios in the time one costs today.

**Caveats before committing to this.** The benchmark above covers two shapes,
not the full feature set — tiers and rebates need careful formulation, and MOQ
needs semi-continuous support. It adds a solver dependency (scipy/HiGHS is
permissively licensed; `highspy` or OR-Tools are lighter options). And numeric
tolerance replaces exact integer reasoning, which needs care where the current
code relies on integer arithmetic.

---

## Technical debt

- `main.pl` is the single entry point (loads facts, solver, decompose,
  csv_loader, scenarios, sensitivity, multiperiod). Still no `load.pl` that
  also pulls in `json_api.pl` and `tests.pl`.
- **NEVER use `forall/2` to post CLP(FD) constraints** — use direct recursion.
  `forall/2` is `\+ (Cond, \+ Action)`, so every constraint posted inside is
  undone on the way out. This silently disabled `global_capacity/2` for
  several releases; the verifier reported the violation but the solver never
  enforced it.
- **Test bodies must assert with `user:` qualification.** PlUnit runs each test
  body in its own module, so an unqualified `assert(fact(...))` lands there
  instead of `user` where the solver reads facts — and the test passes
  vacuously. Several did.
- `p2clpfd/pl/*.pl` is a copy of the root `*.pl` files; run `scripts/sync_pl.sh`
  after editing. A real packaging fix would remove the duplication.
