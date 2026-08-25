# Benchmarks

Where P2CLPFD's time actually goes.

```bash
python scripts/benchmark.py     # sweeps -> benchmarks/scaling.json
python scripts/make_chart.py    # chart  -> benchmarks/scaling.html
```

The constraint set is deliberately ordinary — the kind most category
managers run:

- 4 suppliers
- quad sourcing (every item must use all four)
- each supplier guaranteed at least a 5% share of the item

Everything else is held fixed while one variable moves.

## The finding

**Catalogue size is not the problem. Order quantity is — and a share grid
removes it entirely.**

| Variable | Growth | Measured |
|---|---|---|
| **Items sourced** | linear, x<sup>0.99</sup> | 115 ms/item at 100 items, 105 ms/item at 3,000 |
| **Units per item** | near-quadratic, x<sup>1.90</sup> | 0.03s at 10 units → 37.3s at 400 |
| **Units per item, 5% grid** | flat, x<sup>0.16</sup> | 0.05s at 10 units → **0.32s at 20,000** |

Sourcing ten times as many items costs ten times the time — that scales
fine, because nothing in this constraint set ties one item to another and
`decompose.pl` proves each item optimal on its own.

Quantity is the expensive axis. CLP(FD) searches over integer quantities,
so units-per-item sets how big a space branch-and-bound must cover to
*prove* optimality.

## The share grid

`share_increment(Pct)` restricts awards to whole multiples of Pct% of
demand — the way awards are actually written ("60/30/10", never "37.13%").

The point is not the restriction, it is **what gets searched**. Without a
grid, each quantity ranges over `0..Demand`. On a 5% grid there are only
21 possible levels no matter how large Demand is, and it is the *level*
that carries the search — the quantity follows by arithmetic
(`100·Q = Level · Pct · Demand`). Solve time stops depending on quantity
altogether: 0.32s at 20,000 units, where the free model could not finish
400 units inside 40s.

It is not free, and it is not the same problem:

- **When the true optimum is off-grid, you pay.** Forcing that case (a
  supplier capped at 37 units): free optimum 1126 with a 37/63 split, grid
  optimum 1130 with 35/65 — **0.36% worse**. Small, real, quantifiable.
- **Non-divisible demand silently narrows the options.** At demand 30, 5%
  is 1.5 units, so only *even* levels are reachable. The linear relation
  excludes the unreachable ones on its own, so the model never invents a
  fractional split — but there are fewer choices than 21.
- **MOQs and price breaks do not respect the grid**, and can push a
  supplier off it or make the model infeasible.

Use it when round-number awards are acceptable, which is most of the time.

## What we ruled out

Three plausible explanations the measurements do **not** support:

- **Process startup.** Booting SWI-Prolog through janus and consulting all
  nine `.pl` files costs ~0.8s, once. Irrelevant at these timescales.
- **The search strategy.** Comparing `ff`, `ffc`, `bisect`, `enum`, `down`,
  `min`, `max` and plain leftmost on one instance spread the result over
  about 30% — the best is not a different order of magnitude from what we
  ship. This is not a tuning problem.
- **Loose constraints leaving too much freedom.** Tightening per-supplier
  capacity from 100% of demand to 50% took a single item from ~12s to over
  45s. More constraints did not prune the search; they made proving
  optimality harder.

## The realistic setup: portfolio cap + award grid

The configuration most buyers actually run — 4 suppliers, quad sourcing, 5%
minimum share, **no supplier above 30% of total volume**, awards on a 5%
grid, 1,000 units per item:

| items | solve time | per item |
|---|---|---|
| 1 | 0.2s | 243 ms |
| 2, 3 | **stalls** | cap binds |
| 4 | 0.4s | 105 ms |
| 5, 6 | **stalls** | cap binds |
| 8 | 1.2s | 153 ms |
| 100 | 15.9s | 159 ms |
| 1,000 | 160.6s | 161 ms |
| 1,500 | 289.2s | 193 ms |
| 2,000 | 417.2s | 209 ms |

**Roughly 1,550 items is as far as a five-minute wait stretches.**

The shape is counter-intuitive: it is fast at 1 item, stalls at 2-6, then is
fast and near-linear from 8 upward. A portfolio cap ties every item together
*on paper*, but whether it actually bites depends on how concentrated the
award would otherwise be. With a handful of items one supplier wins most of
them and blows through 30%; across a large catalogue the cheapest supplier
varies item to item and the total lands near 25% on its own — under the cap,
so it constrains nothing.

`decompose.pl` exploits exactly that. It solves without the cross-part rules
(fast, because the items separate), then checks whether the answer happens to
satisfy them. Dropping a constraint can only lower the optimum, so if the
relaxed answer obeys the cap it is optimal for the capped problem too. When
the cap really does bite the check fails and it falls back to one big search
— which is what the 2-6 item stalls are.

Per-item cost drifts up gently at the top end (153 ms at 8 items, 209 ms at
2,000), so the crossover is interpolated between the bracketing measurements
rather than extrapolated from an average.

## The coupled case

One portfolio-wide rule — a cap on any supplier's share of *total* volume —
welds every item into a single search, because minimizing a sum couples
everything the sum touches. At just **100 items it exceeded a 550s budget**,
against 11s for the same items without it.

This is what `decompose.pl` still cannot split, and it is the next thing
worth fixing (see [ROADMAP.md](../ROADMAP.md)). Rebates were the same shape
and are already handled, by enumerating their earned/not-earned branches.

## Reading the numbers

`scaling.json` holds the raw records; `scaling.html` renders them with a
table view. Each point is one `solve()` on generated data, timed in its own
process so an overrun can be killed — CLP(FD) labeling does not reliably
yield to Prolog's `call_with_time_limit/2`, so an in-process timeout would
simply hang.

Prices rotate per item so the optimum is a genuine choice rather than a tie;
a model where every supplier costs the same would flatter the solver by
making the search trivial.
