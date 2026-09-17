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
| — | MCP server — 10 tools over stdio JSON-RPC | ✓ |
| — | JSON HTTP API (POST /solve, /scenarios, /validate, GET /health) | ✓ |
| — | Solver tracer (NDJSON trace + live WebSocket visualization) | ✓ |
| — | HTML report (`p2clpfd report`) — the whole decision as one self-contained, checksummed file | ✓ |
| — | Python package (`pip install p2clpfd`) | ✓ |
| — | Problem decomposition (independent parts, rebate branch enumeration) | ✓ |
| — | Share grid (`share_increment`) — rounds to whole units; on by default in the CLI (`--increment`) | ✓ |
| — | Cost floor + greedy bound per part, and a halving cost search (quantity no longer drives solve time) | ✓ |
| — | `p2clpfd rules` / MCP `read_rules` — the model read back before sign-off | ✓ |
| — | Scenarios passed as data — capitalised part and supplier names work, bad overrides are rejected | ✓ |
| — | Scaling benchmark + chart (`scripts/benchmark.py`, `make_chart.py`) | ✓ |
| — | Slack-coupling shortcut — a cross-part rule that does not bite is free | ✓ |
| — | Structured validation with plain-language findings | ✓ |
| — | Test suite: 83 PlUnit + 151 Python (judgment and report units + CLI/MCP integration + realistic events) | ✓ |

---

## Remaining roadmap

### Split route-coupled problems when the rule actually bites

Partly addressed: a cross-part rule that does NOT constrain the answer is now
free, because the relaxed per-item solve is checked against it and accepted
when it already complies. With the cost floors and halving search, a 30%
portfolio cap now runs 3,000 items in under five seconds.

What remains is the case where the rule genuinely binds — a small catalogue
where one supplier would win most of it, or a route ceiling below what the
cheapest routing wants. Those still fall back to one monolithic search. The
per-part floors do not help there, because the cap is what couples the parts:
[the benchmark](benchmarks/)'s binding 40% cap solves 4 items in 2.8 s and
does not finish 8 in a minute.

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

**Superseded by bounds, which need no guard.** The idea was to hand the
per-item answer straight from a greedy fill, and it was unsafe: supplier-count
rules made greedy report costs *below* the true optimum (13 of 53 random
instances). What shipped instead uses the greedy fill as a **lower bound**
posted into the search (`post_part_cost_floor/5`, `post_greedy_bound/3` in
`solver.pl`), alongside a floor that charges every unit at least the cheapest
effective price plus each dearer supplier's premium. A bound that holds for
every legal award can only prune; it can never report an award that does not
exist, so it applies to every model — count rules, MOQs, tiers and fixed costs
included.

The other half was the search itself. `labeling([min(Cost)])` improves the
incumbent one solution at a time, which on a million units meant hundreds of
thousands of steps, and whether a model finished depended on supplier name
order. `minimize_cost/2` finds any award, asks "is there one at the floor?",
then halves the gap — about 30 questions instead.

On the benchmark's shape this took items from 105 ms to 1.07 ms each, and
units per item stopped mattering (3 ms at 20,000, where 400 used to take 37 s).

---

### Make the share grid discoverable

**Done, and the grid changed shape on the way.** It was worse than
undiscoverable: MCP and the Python API had it but the CLI had no flag, so a
buyer with three suppliers and no capacities got an indefinite hang. The CLI
now applies a 5% grid by default (`--increment`, `0` turns it off), and three
problems found while doing that are fixed and pinned by tests:

- **The grid used to delete splits.** `100*Q #= Level*Pct*Demand` has no
  integer solution when the step does not divide demand, so 333 units on a 5%
  grid reported "no award" and 999,999 units had no usable step at all. Each
  award is now the step rounded to a whole unit, with the part still totalling
  exactly.
- **The default grid must not cause "no award".** A 12–13% share band has no
  5% level. When the default grid alone rules everything out, `Solver.solve`
  and `compare_scenarios` drop it and search every quantity, and the CLI says
  so. A `share_increment` in the CSV is the buyer's rule and is never dropped.
- **Never claim more than was proved.** Runs note the grid on stderr, and the
  HTML report's subtitle names the step instead of "not an estimate".

**Still open:** the judgment layer could suggest a grid to library and MCP
callers when a model is slow; with the new search that matters much less.

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

**Update, 17 September 2026:** the cost floors and halving search added
since are a hand-built version of the bound described under *Why* below, and
on the benchmark's item sweep they cut 105 ms to 1.07 ms per item — about
100x. HiGHS has not been re-run against them, so the gap in the table above is
out of date; it is certainly smaller, and a binding portfolio cap is still
where CLP(FD) falls furthest behind.

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
a codebase that is already correct and covered by 79 + 121 tests.

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
- `p2clpfd/pl/*.pl` are symlinks to the root `*.pl` files, so editing the root
  file is enough. `scripts/sync_pl.sh` predates the links; it now only replaces
  a copy that is not already a link (it used to abort on the first file).
- **Never paste names into Prolog query text — pass them as data.** Scenario
  overrides were interpolated into the query, so a capitalised part number
  (`share(ABC,ti,70,70)`) parsed as a Prolog *variable* and the solve died with
  `Arguments are not sufficiently instantiated`. Real part numbers are
  capitalised, so the feature was broken for the names users have. Scenarios
  now travel through janus as dicts; `override_term/2` in `json_api.pl` parses
  the fact text and binds every named variable to the atom it spells, leaving
  `_` and `_Name` as the wildcards `remove` relies on. The same path fixed an
  override with an unknown key being silently skipped.
- **janus returns every variable in the query, so template variables must be
  underscore-prefixed.** `janus.query_once('findall(P-D, demand(P,D), Rows)')`
  fails with `Arguments are not sufficiently instantiated` — not because the
  Prolog is wrong, but because janus tries to convert `P` and `D`, which are
  still unbound after the findall. Write `findall([_P,_D], demand(_P,_D), Rows)`
  instead. The error names nothing useful, so this costs a debugging cycle
  every time a new query is added.
