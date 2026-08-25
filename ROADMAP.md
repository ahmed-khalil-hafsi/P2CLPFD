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
