%%% P2CLPFD — Procurement Allocation Solver
%%%
%%% A generalized N-parts x M-suppliers CLP(FD) engine that minimizes the
%%% Total Cost of Ownership (TCO) subject to demand, capacity, MOQ,
%%% sourcing-strategy (share), global-capacity, volume-based (tiered)
%%% pricing, fixed costs, and risk (dual-sourcing / supplier count)
%%% constraints.
%%%
%%% Load with:  ?- ['facts.pl','solver.pl'].
%%% Query:      ?- solve(Allocation, TCO).
%%%             ?- solve(Allocation, TCO), labeling([min(TCO)], _).  % (built-in)

:- use_module(library(clpfd)).

%% ------------------------------------------------------------------ %%
%%  PUBLIC API                                                         %%
%% ------------------------------------------------------------------ %%

%! solve(-Allocation, -TCO) is nondet.
%
%  Allocation = list of alloc(Part, [q(Supplier,Qty), ...]).
%  TCO        = minimized total cost of ownership (integer).
%  Returns the optimal solution on first success (labeling with min/1).
%  Backtracking yields subsequent solutions in increasing TCO order.
%
solve(Allocation, TCO) :-
    (   rebate(_, _, _), \+ rebate_forced(_, _)
    ->  solve_rebate_enumerated(Allocation, TCO)
    ;   solve_dispatch(Allocation, TCO)
    ).

%! solve_dispatch(-Allocation, -TCO) is nondet.
%  Pick the cheapest strategy that is still exact for this model.
solve_dispatch(Allocation, TCO) :-
    (   single_part_problem
    ->  solve_monolithic(Allocation, TCO)
    ;   parts_are_coupled
    ->  solve_monolithic(Allocation, TCO)
    ;   solve_decomposed(Allocation, TCO)
    ).

single_part_problem :-
    parts(Parts),
    Parts = [_].

%! solve_monolithic(-Allocation, -TCO) is nondet.
%  One model over every part at once. Used when cross-part constraints
%  make the parts inseparable.
solve_monolithic(Allocation, TCO) :-
    parts(Parts),
    suppliers(Suppliers),
    build_model(Parts, Suppliers, RawAlloc, Vars, TCO),
    post_tco_lower_bound(TCO),
    labeling([min(TCO), ff], Vars),
    materialize(RawAlloc, Allocation).

%! solve(-Allocation, -TCO, +MaxCost) is nondet.
%
%  As solve/2 but additionally constrains TCO =< MaxCost.
%
%  The cheapest award subject to a ceiling is just the cheapest award,
%  provided it clears the ceiling — so this reuses solve/2 and inherits
%  its decomposition and rebate enumeration instead of falling back to
%  one large monolithic search.
solve(Allocation, TCO, MaxCost) :-
    solve(Allocation, TCO),
    TCO =< MaxCost.

%% ------------------------------------------------------------------ %%
%%  DATA ACCESSORS  (read from facts.pl)                                %%
%% ------------------------------------------------------------------ %%

parts(Parts) :-
    findall(P, demand(P, _), PartsU),
    sort(PartsU, Parts).

suppliers(Suppliers) :-
    findall(S, (cost(S, _, _) ; price_tier(S, _, _, _, _)), SuppliersU),
    sort(SuppliersU, Suppliers).

allocatable(Part, Supplier) :-
    (   cost(Supplier, Part, _)
    ;   has_tiers(Supplier, Part)
    ).

has_tiers(Supplier, Part) :-
    price_tier(Supplier, Part, _, _, _).

unit_cost(Supplier, Part, Cost) :-
    cost(Supplier, Part, Cost).

%! has_tiers(+Supplier, +Part) is semidet.
%! effective_unit_cost(+Supplier, +Part, +Q, -EffCost) is semidet.
%
%  Deterministic lookup of the effective unit cost for a GROUND quantity Q.
%  Resolves the active price tier when tiered pricing applies, then adds
%  the non-cost adjustment.  Used by the verifier and pretty-printer.
%
effective_unit_cost(Supplier, Part, Q, EffCost) :-
    (   has_tiers(Supplier, Part)
    ->  find_active_tier(Supplier, Part, Q, RawCost)
    ;   cost(Supplier, Part, RawCost)
    ),
    landed_unit_cost(Supplier, RawCost, Landed),
    (   noncost_adjustment(Supplier, Adj)
    ->  EffCost is Landed + Adj
    ;   EffCost = Landed
    ).

%! landed_unit_cost(+Supplier, +RawCost, -Landed) is det.
%
%  Folds region-based FX and logistics into the invoice price:
%    Landed = RawCost * FxPct // 100 + LogisticsPerUnit
%  FxPct is an integer percentage (105 = +5%). Suppliers with no
%  region/2 fact (or regions with no fx/logistics facts) are unchanged.
%
landed_unit_cost(Supplier, RawCost, Landed) :-
    supplier_fx_pct(Supplier, Fx),
    supplier_logistics(Supplier, Log),
    Landed is (RawCost * Fx) // 100 + Log.

supplier_fx_pct(Supplier, Fx) :-
    (   region(Supplier, Region), fx_rate(Region, Fx0)
    ->  Fx = Fx0
    ;   Fx = 100
    ).

supplier_logistics(Supplier, Log) :-
    (   region(Supplier, Region), logistics_cost(Region, Log0)
    ->  Log = Log0
    ;   Log = 0
    ).

find_active_tier(Supplier, Part, Q, RawCost) :-
    price_tier(Supplier, Part, Min, Max, RawCost),
    Q >= Min,
    (   Max == sup -> true ; Q =< Max ),
    !.

moq_of(Supplier, Part, Moq) :-
    moq(Supplier, Part, Moq), !.
moq_of(_, _, 0).

%% ------------------------------------------------------------------ %%
%%  QUALIFICATION GATES (hard disqualification, not cost adjustments)  %%
%% ------------------------------------------------------------------ %%
%%
%%  A disqualified (Part, Supplier) pair is treated exactly like a
%%  non-allocatable one: Q is pinned to 0 at model-build time, so no
%%  cost advantage can override the gate.
%%
%%  Conservative semantics: when a gate threshold exists but the
%%  supplier has NO data on record (no otif/2, no lead_time/3), the
%%  supplier is disqualified — unknown performance fails qualification.

%! qualified(+Part, +Supplier) is semidet.
qualified(Part, Supplier) :-
    \+ disqualified(Part, Supplier, _).

%! disqualified(?Part, ?Supplier, -Reason) is nondet.
%
%  Reasons:
%    otif_below_threshold(Actual, Threshold)   Actual may be 'unknown'
%    lead_time_exceeded(Actual, MaxDays)       Actual may be 'unknown'
%    missing_certification(Cert)
%
disqualified(_Part, Supplier, otif_below_threshold(Actual, Threshold)) :-
    min_otif(Threshold),
    (   otif(Supplier, Actual)
    ->  Actual < Threshold
    ;   Actual = unknown
    ).
disqualified(Part, Supplier, lead_time_exceeded(Actual, MaxDays)) :-
    max_lead_time(Part, MaxDays),
    (   lead_time(Supplier, Part, Actual)
    ->  Actual > MaxDays
    ;   Actual = unknown
    ).
disqualified(_Part, Supplier, missing_certification(Cert)) :-
    required_certification(Cert),
    \+ certification(Supplier, Cert).
disqualified(Part, Supplier, missing_certification(Cert)) :-
    required_certification(Part, Cert),
    \+ certification(Supplier, Cert).

%! disqualified_pairs(-Exclusions) is det.
%
%  All excluded (Part, Supplier) pairs among otherwise-allocatable
%  combinations, with human-readable reasons. Used by the JSON API
%  and the judgment layer to explain WHY a supplier is absent.
%
disqualified_pairs(Exclusions) :-
    parts(Parts),
    findall(excluded(Part, Supplier, Reasons),
            ( member(Part, Parts),
              allocatable_supplier(Part, Supplier),
              findall(R, disqualified(Part, Supplier, R), Reasons),
              Reasons \= []
            ),
            Exclusions).

allocatable_supplier(Part, Supplier) :-
    suppliers(Suppliers),
    member(Supplier, Suppliers),
    allocatable(Part, Supplier).

capacity_of(Supplier, Part, Cap) :-
    capacity(Supplier, Part, Cap), !.
capacity_of(_, _, sup).

global_capacity_of(Supplier, Cap) :-
    global_capacity(Supplier, Cap), !.
global_capacity_of(_, sup).

share_of(Part, Supplier, MinPct, MaxPct) :-
    share(Part, Supplier, MinPct, MaxPct), !.
share_of(_, _, 0, 100).

%% ------------------------------------------------------------------ %%
%%  MODEL BUILDING                                                     %%
%% ------------------------------------------------------------------ %%

%! build_model(+Parts, +Suppliers, -RawAlloc, -Vars, -TCO).
%
%  Posts all constraints; RawAlloc carries the unbound FD variables in a
%  structured form so materialize/2 can read them after labeling.
%
build_model(Parts, Suppliers, RawAlloc, Vars, TCO) :-
    build_parts(Parts, Suppliers, RawAlloc, PartCosts, VarsParts, AllBs),
    build_global_capacity(Suppliers, RawAlloc),
    post_risk_constraints(Parts, AllBs),
    post_global_share(RawAlloc, Parts),
    post_route_constraints(RawAlloc, Parts),
    append(VarsParts, BaseVars),
    %% Test for rebates BEFORE calling build_rebates/4, never on whether
    %% it succeeded. build_rebates/4 also fails when the rebate model is
    %% genuinely infeasible (a forced branch that cannot be reached), and
    %% treating that as "no rebates here" would silently drop the
    %% threshold constraint and report a solution that never earns it.
    (   rebate(_, _, _)
    ->  %% Rebate control variables MUST join the labeling set. Left out,
        %% TCO never grounds and min(TCO) cannot close its bound.
        build_rebates(Suppliers, RawAlloc, TCO, RebateVars),
        append(BaseVars, RebateVars, Vars)
    ;   sum(PartCosts, #=, TCO),
        Vars = BaseVars
    ).

build_parts([], _, [], [], [], []).
build_parts([Part|Rest], Suppliers,
            [alloc(Part, Qs)|RestAlloc],
            [PartCost|RestCosts],
            [PartVars|RestVars],
            [PartBs|RestBs]) :-
    build_part_suppliers(Part, Suppliers, Qs, PartCost, PartVars, PartBs),
    build_parts(Rest, Suppliers, RestAlloc, RestCosts, RestVars, RestBs).

build_part_suppliers(Part, Suppliers, Qs, PartCost, Vars, Bs) :-
    demand(Part, Demand),
    build_part_suppliers_(Part, Suppliers, Demand, Qs, Costs, Vars, Bs),
    qs_of(Qs, QOnly),
    sum(QOnly, #=, Demand),
    sum(Costs, #=, PartCost).

build_part_suppliers_(_, [], _, [], [], [], []).
build_part_suppliers_(Part, [Supplier|Rest], Demand,
                     [q(Supplier,Q,CostC)|Qs], [CostC|Cs], [Q,B|Vs], [B|Bs]) :-
    (   allocatable(Part, Supplier),
        qualified(Part, Supplier)
    ->  Q in 0..Demand,
        B in 0..1,
        B #= 1 #<==> Q #>= 1,
        supplier_part_constraints(Part, Supplier, Demand, Q, C, AuxVars),
        (   fixed_cost(Supplier, Part, FixedAmount)
        ->  FixedCostC #= B * FixedAmount,
            CostC #= C + FixedCostC
        ;   CostC = C
        ),
        append(AuxVars, RestVs, Vs)
    ;   Q = 0,
        B = 0,
        CostC = 0,
        Vs = RestVs
    ),
    build_part_suppliers_(Part, Rest, Demand, Qs, Cs, RestVs, Bs).

%% Extract the quantity variables by unification (NOT findall, which copies
%% and would detach constraints from the original q/3 terms).
qs_of([], []).
qs_of([q(_,Q,_)|Rest], [Q|Out]) :- qs_of(Rest, Out).

%! supplier_part_constraints(+Part, +Supplier, +Demand, +Q, -CostC, -AuxVars).
%
%  Posts per-pair constraints and the cost contribution.
%  AuxVars receives auxiliary FD variables (e.g. TierVar) that must be
%  included in the labeling set so propagation is complete.
%
supplier_part_constraints(Part, Supplier, Demand, Q, CostC, AuxVars) :-
    % --- capacity -------------------------------------------------------
    capacity_of(Supplier, Part, Cap),
    (   Cap == sup
    ->  true
    ;   Q #=< Cap
    ),

    % --- minimum order quantity (Q is 0 OR >= Moq) ---------------------
    moq_of(Supplier, Part, Moq),
    (   Moq =< 0
    ->  true
    ;   Q in 0 \/ Moq..sup
    ),

    % --- sourcing-strategy share bounds (percentage of demand) ---------
    share_of(Part, Supplier, MinPct, MaxPct),
    (   MinPct =< 0
    ->  true
    ;   MinPct * Demand #=< 100 * Q
    ),
    (   MaxPct >= 100
    ->  true
    ;   100 * Q #=< MaxPct * Demand
    ),

    % --- share granularity (award on a percentage grid) ----------------
    share_grid(Part, Demand, Q, GridVars),

    % --- cost contribution (tiered or flat) ----------------------------
    (   has_tiers(Supplier, Part)
    ->  tiered_pricing(Supplier, Part, Q, CostC, TierVar),
        append(GridVars, [TierVar], AuxVars)
    ;   effective_unit_cost(Supplier, Part, _, EffCost),
        CostC #= Q * EffCost,
        AuxVars = GridVars
    ).

%! share_grid(+Part, +Demand, +Q, -GridVars) is det.
%
%  Restricts an award to whole increments of the part's demand — the way
%  awards are actually written ("60/30/10", never "37.13%").
%
%  The point is not the restriction, it is WHAT GETS SEARCHED. Without a
%  grid, Q ranges over 0..Demand, so the space branch-and-bound must cover
%  to prove optimality grows with the order quantity. On a 5% grid there
%  are only 21 possible levels no matter how large Demand is, and it is
%  the LEVEL that carries the search: Q is then fixed by arithmetic.
%  Solve time stops depending on quantity altogether.
%
%  Levels whose quantity is not a whole number are simply absent from
%  Level's domain, which the linear relation below enforces on its own —
%  100 * Q #= Level * Pct * Demand has no solution for a Level that would
%  need a fractional Q. So the model never invents an unachievable split.
%
share_grid(Part, Demand, Q, GridVars) :-
    (   share_increment_of(Part, Pct),
        Pct > 0,
        Demand > 0
    ->  Levels is 100 // Pct,
        Level in 0..Levels,
        100 * Q #= Level * Pct * Demand,
        GridVars = [Level]
    ;   GridVars = []
    ).

%! share_increment_of(+Part, -Pct) is semidet.
%  Per-part increment wins over the global one; absent means no grid.
share_increment_of(Part, Pct) :-
    share_increment(Part, Pct), !.
share_increment_of(_, Pct) :-
    share_increment(Pct).

%! tiered_pricing(+Supplier, +Part, +Q, -CostC, -TierVar).
%
%  Posts volume-based tiered pricing constraints:
%    - TierVar selects which price tier is active (1..N).
%    - element/3 links TierVar to the raw unit cost.
%    - Reified #==> constraints enforce Q within the selected tier's bounds.
%    - Non-cost adjustment is added to the raw cost.
%    - CostC = Q * EffectiveUnitCost.
%
tiered_pricing(Supplier, Part, Q, CostC, TierVar) :-
    findall(tier(Min, Max, Cost),
            price_tier(Supplier, Part, Min, Max, Cost),
            Tiers),
    length(Tiers, N),
    TierVar in 1..N,
    tiers_raw_costs(Tiers, RawCosts),
    element(TierVar, RawCosts, RawUnitCost),
    supplier_fx_pct(Supplier, Fx),
    supplier_logistics(Supplier, Log),
    (   noncost_adjustment(Supplier, Adj0)
    ->  Adj = Adj0
    ;   Adj = 0
    ),
    EffUnitCost #= (RawUnitCost * Fx) // 100 + Log + Adj,
    CostC #= Q * EffUnitCost,
    post_tier_bounds(Tiers, TierVar, Q, 1).

tiers_raw_costs([], []).
tiers_raw_costs([tier(_, _, Cost)|Rest], [Cost|Out]) :-
    tiers_raw_costs(Rest, Out).

post_tier_bounds([], _, _, _).
post_tier_bounds([tier(Min, Max, _)|Rest], TierVar, Q, I) :-
    TierVar #= I #==> Q #>= Min,
    (   Max == sup
    ->  true
    ;   TierVar #= I #==> Q #=< Max
    ),
    NextI is I + 1,
    post_tier_bounds(Rest, TierVar, Q, NextI).

%% ------------------------------------------------------------------ %%
%%  GLOBAL CAPACITY CONSTRAINTS                                        %%
%% ------------------------------------------------------------------ %%

%% Direct recursion, NOT forall/2: forall/2 is double negation, so any
%% CLP(FD) constraint posted inside it is undone on the way out.
build_global_capacity([], _).
build_global_capacity([Supplier|Rest], RawAlloc) :-
    global_capacity_constraint(Supplier, RawAlloc),
    build_global_capacity(Rest, RawAlloc).

global_capacity_constraint(Supplier, RawAlloc) :-
    global_capacity_of(Supplier, Cap),
    (   Cap == sup
    ->  true
    ;   supplier_qs_across_parts(Supplier, RawAlloc, SupplierQs),
        sum(SupplierQs, #=, Total),
        Total #=< Cap
    ).

%% Collect Q vars for Supplier across all parts, by unification.
supplier_qs_across_parts(_, [], []).
supplier_qs_across_parts(Supplier, [alloc(_, Qs)|Rest], Out) :-
    supplier_q_in_part(Supplier, Qs, QInPart),
    append(QInPart, RestOut, Out),
    supplier_qs_across_parts(Supplier, Rest, RestOut).

supplier_q_in_part(_, [], []).
supplier_q_in_part(Supplier, [q(Supplier,Q,_)|Rest], [Q|Out]) :-
    !, supplier_q_in_part(Supplier, Rest, Out).
supplier_q_in_part(Supplier, [_|Rest], Out) :-
    supplier_q_in_part(Supplier, Rest, Out).

%% ------------------------------------------------------------------ %%
%%  RISK / DUAL-SOURCING CONSTRAINTS                                   %%
%% ------------------------------------------------------------------ %%

%! post_risk_constraints(+Parts, +AllBs).
%  For each part, post min/max supplier-count constraints on the B vars.
post_risk_constraints([], []).
post_risk_constraints([Part|Rest], [PartBs|RestBs]) :-
    post_part_risk(Part, PartBs),
    post_risk_constraints(Rest, RestBs).

post_part_risk(Part, Bs) :-
    min_suppliers_of(Part, MinN),
    (   MinN > 0
    ->  sum(Bs, #>=, MinN)
    ;   true
    ),
    (   max_suppliers(Part, MaxN)
    ->  sum(Bs, #=<, MaxN)
    ;   true
    ).

%! min_suppliers_of(+Part, -N) is det.
%  Returns the effective minimum supplier count for a part, considering
%  both min_suppliers/2 and dual_source/1 (takes the larger).
min_suppliers_of(Part, N) :-
    (   catch(min_suppliers(Part, N0), _, fail), dual_source(Part)
    ->  N is max(N0, 2)
    ;   catch(min_suppliers(Part, N), _, fail)
    ->  true
    ;   catch(dual_source(Part), _, fail)
    ->  N = 2
    ;   N = 0
    ).

%% ------------------------------------------------------------------ %%
%%  GLOBAL SHARE CONSTRAINTS                                           %%
%% ------------------------------------------------------------------ %%

%! post_global_share(+RawAlloc, +Parts).
%  For each max_global_share(Supplier, Pct) fact, constrain Supplier's
%  total Q across all parts to Pct% of total demand.
post_global_share(RawAlloc, Parts) :-
    total_demand(Parts, TotalDemand),
    findall(S-P, max_global_share(S, P), Pairs),
    post_global_share_pairs(Pairs, RawAlloc, TotalDemand).

post_global_share_pairs([], _, _).
post_global_share_pairs([Supplier-Pct|Rest], RawAlloc, TotalDemand) :-
    global_share_constraint(Supplier, RawAlloc, TotalDemand, Pct),
    post_global_share_pairs(Rest, RawAlloc, TotalDemand).

total_demand([], 0).
total_demand([Part|Rest], Total) :-
    demand(Part, D),
    total_demand(Rest, RestTotal),
    Total is D + RestTotal.

global_share_constraint(Supplier, RawAlloc, TotalDemand, Pct) :-
    supplier_qs_across_parts(Supplier, RawAlloc, SupplierQs),
    post_weighted_sum(SupplierQs, 100, Total),
    Total #=< Pct * TotalDemand.

%! post_weighted_sum(+Vars, +Coeff, -WeightedTotal).
%  Posts WeightedTotal #= Coeff * V1 + Coeff * V2 + ... without introducing
%  an intermediate sum variable.  This ensures propagation reaches the
%  original FD vars directly.
post_weighted_sum([], _, 0).
post_weighted_sum([V|Vs], Coeff, Total) :-
    Total #= Coeff * V + Rest,
    post_weighted_sum(Vs, Coeff, Rest).

%% ------------------------------------------------------------------ %%
%%  ROUTE (GROUP) CONSTRAINTS                                          %%
%% ------------------------------------------------------------------ %%
%
%  A route is a named group of suppliers that share a physical or policy
%  ceiling.  global_capacity/2 caps ONE supplier across all parts; a route
%  caps a SET of suppliers across all parts.  This is what a shipping
%  chokepoint, a shared port, a single border crossing, or a country-level
%  policy limit actually is: no individual supplier is capped, but their
%  sum is.
%
%    supplier_route(Supplier, Route).   % membership; a supplier has one route
%    route_capacity(Route, MaxQty).     % absolute ceiling on the group total
%    max_route_share(Route, Pct).       % group total =< Pct% of total demand
%
%  Both ceilings are optional and independent.

%! routes(-Routes) is det.
routes(Routes) :-
    findall(R, supplier_route(_, R), Rs),
    sort(Rs, Routes).

%! route_members(+Route, -Members) is det.
route_members(Route, Members) :-
    findall(S, supplier_route(S, Route), Ss),
    sort(Ss, Members).

%! post_route_constraints(+RawAlloc, +Parts) is det.
post_route_constraints(RawAlloc, Parts) :-
    routes(Routes),
    (   Routes == []
    ->  true
    ;   total_demand(Parts, TotalDemand),
        post_route_list(Routes, RawAlloc, TotalDemand)
    ).

%% Direct recursion, NOT forall/2: forall/2 is double negation, so any
%% CLP(FD) constraint posted inside it is undone on the way out.
post_route_list([], _, _).
post_route_list([Route|Rest], RawAlloc, TotalDemand) :-
    route_qs(Route, RawAlloc, Qs),
    (   Qs == []
    ->  true
    ;   route_capacity_constraint(Route, Qs),
        route_share_constraint(Route, Qs, TotalDemand)
    ),
    post_route_list(Rest, RawAlloc, TotalDemand).

route_capacity_constraint(Route, Qs) :-
    (   route_capacity(Route, Cap)
    ->  sum(Qs, #=<, Cap)
    ;   true
    ).

route_share_constraint(Route, Qs, TotalDemand) :-
    (   max_route_share(Route, Pct)
    ->  post_weighted_sum(Qs, 100, Total),
        Total #=< Pct * TotalDemand
    ;   true
    ).

%! route_qs(+Route, +RawAlloc, -Qs) is det.
%  Every Q variable belonging to any supplier in Route, across all parts.
%  Collected by unification so the constraints reach the original vars.
route_qs(Route, RawAlloc, Qs) :-
    route_members(Route, Members),
    member_qs(Members, RawAlloc, Qs).

member_qs([], _, []).
member_qs([S|Rest], RawAlloc, Out) :-
    supplier_qs_across_parts(S, RawAlloc, SQs),
    append(SQs, RestOut, Out),
    member_qs(Rest, RawAlloc, RestOut).

%% ------------------------------------------------------------------ %%
%%  REBATES (portfolio-level volume discounts)                         %%
%% ------------------------------------------------------------------ %%

%! build_rebates(+Suppliers, +RawAlloc, -TCO, -RebateVars) is semidet.
%  Aggregates TCO per supplier (so a cross-part rebate can apply to the
%  whole spend) instead of per part. Only called when a rebate exists.
%  Fails only when the rebate model is infeasible — which means the whole
%  model is infeasible, so the caller must NOT treat failure as "skip".
%  RebateVars are the control variables the caller must label.
build_rebates(Suppliers, RawAlloc, TCO, RebateVars) :-
    supplier_costs_across_all(Suppliers, RawAlloc, SupplierCosts, RebateVars),
    sum(SupplierCosts, #=, TCO).

%! supplier_costs_across_all(+Suppliers, +RawAlloc, -Costs, -RebateVars).
%  For each supplier, compute the cost (with rebate applied if applicable).
supplier_costs_across_all([], _, [], []).
supplier_costs_across_all([S|Ss], RawAlloc, [Cost|Costs], Vars) :-
    supplier_final_cost(S, RawAlloc, Cost, VarsHead),
    supplier_costs_across_all(Ss, RawAlloc, Costs, VarsTail),
    append(VarsHead, VarsTail, Vars).

%! supplier_final_cost(+Supplier, +RawAlloc, -Cost, -RebateVars).
%  Compute the supplier's total cost, with rebate applied if applicable.
supplier_final_cost(Supplier, RawAlloc, FinalCost, RebateVars) :-
    supplier_costs_across_parts(Supplier, RawAlloc, CostCs),
    sum(CostCs, #=, TotalCost),
    (   rebate(Supplier, Threshold, Pct)
    ->  supplier_qs_across_parts(Supplier, RawAlloc, Qs),
        sum(Qs, #=, TotalQ),
        rebate_branch(Supplier, Threshold, Pct, TotalQ, TotalCost,
                      FinalCost, RebateVars)
    ;   FinalCost = TotalCost,
        RebateVars = []
    ).

%! rebate_branch(+Supplier, +Threshold, +Pct, +TotalQ, +TotalCost,
%!               -FinalCost, -RebateVars) is det.
%
%  A rebate is a step in the objective: below the threshold you pay list,
%  at or above it the supplier's WHOLE spend is discounted. Expressing
%  that with reification makes the cost non-linear, and branch-and-bound
%  then struggles to prove optimality — the integer division propagates
%  weakly over five-digit cost domains.
%
%  So the caller may instead fix the branch up front via rebate_forced/2
%  and solve each side separately (see solve_rebate_enumerated/2). With
%  the branch fixed the objective is linear again and the search is fast.
%  The reified form is kept as the fallback for direct callers.
%
rebate_branch(Supplier, Threshold, Pct, TotalQ, TotalCost, FinalCost, []) :-
    rebate_forced(Supplier, 1),
    !,
    TotalQ #>= Threshold,
    FinalCost #= (TotalCost * (100 - Pct)) // 100.
rebate_branch(Supplier, Threshold, _Pct, TotalQ, TotalCost, FinalCost, []) :-
    rebate_forced(Supplier, 0),
    !,
    TotalQ #=< Threshold - 1,
    FinalCost = TotalCost.
rebate_branch(_Supplier, Threshold, Pct, TotalQ, TotalCost, FinalCost,
              [RebateActive]) :-
    RebateActive in 0..1,
    TotalQ #>= Threshold #<==> RebateActive #= 1,
    CostDiscounted #= (TotalCost * (100 - Pct)) // 100,
    %% Reified selection rather than element/3: element/3 wants a list of
    %% integers, and passing FD variables in it propagates poorly.
    RebateActive #= 1 #==> FinalCost #= CostDiscounted,
    RebateActive #= 0 #==> FinalCost #= TotalCost.

%! supplier_costs_across_parts(+Supplier, +RawAlloc, -CostCs).
%  Collects CostC variables for Supplier across all parts.
supplier_costs_across_parts(_, [], []).
supplier_costs_across_parts(Supplier, [alloc(_, Qs)|Rest], Out) :-
    supplier_cost_in_part(Supplier, Qs, CostInPart),
    append(CostInPart, RestOut, Out),
    supplier_costs_across_parts(Supplier, Rest, RestOut).

supplier_cost_in_part(_, [], []).
supplier_cost_in_part(Supplier, [q(Supplier,_,C)|Rest], [C|Out]) :-
    !, supplier_cost_in_part(Supplier, Rest, Out).
supplier_cost_in_part(Supplier, [_|Rest], Out) :-
    supplier_cost_in_part(Supplier, Rest, Out).

%% ------------------------------------------------------------------ %%
%%  MATERIALIZE  (turn raw structure into ground output)               %%
%% ------------------------------------------------------------------ %%

materialize([], []).
materialize([alloc(Part, RawQs)|Rest], [alloc(Part, Qs)|Out]) :-
    materialize_qs(RawQs, Qs),
    materialize(Rest, Out).

materialize_qs([], []).
materialize_qs([q(S,Q,_C)|Rest], [q(S,Q)|Out]) :-
    materialize_qs(Rest, Out).

%% ------------------------------------------------------------------ %%
%%  PRETTY PRINTING                                                    %%
%% ------------------------------------------------------------------ %%

%! print_allocation(+Allocation, +TCO) is det.
%
%  Pretty-prints a solution and verifies all constraints hold.
%
print_allocation(Allocation, TCO) :-
    format('~n=== Optimal Allocation ===~n'),
    forall(member(alloc(Part, Qs), Allocation),
           ( format('~nPart: ~w~n', [Part]),
             forall(member(q(Supplier, Q), Qs),
                    ( Q > 0 ->
                      format('  ~w: ~w units', [Supplier, Q]),
                      print_unit_cost(Supplier, Part, Q)
                    ; true )
                   )
           )),
    format('~n~n*** Total Cost of Ownership: ~w ***~n~n', [TCO]),
    verify_allocation(Allocation, TCO).

print_unit_cost(Supplier, Part, Q) :-
    effective_unit_cost(Supplier, Part, Q, EffCost),
    PartCost is Q * EffCost,
    (   has_tiers(Supplier, Part)
    ->  find_active_tier(Supplier, Part, Q, RawCost),
        (   Q > 0, fixed_cost(Supplier, Part, Fixed)
        ->  format('  (tier unit: ~w, eff unit: ~w, subtotal: ~w, fixed: ~w)~n',
                   [RawCost, EffCost, PartCost, Fixed])
        ;   format('  (tier unit: ~w, eff unit: ~w, subtotal: ~w)~n',
                   [RawCost, EffCost, PartCost])
        )
    ;   (   Q > 0, fixed_cost(Supplier, Part, Fixed)
        ->  format('  (unit: ~w, subtotal: ~w, fixed: ~w)~n',
                   [EffCost, PartCost, Fixed])
        ;   format('  (unit: ~w, subtotal: ~w)~n', [EffCost, PartCost])
        )
    ).

%% ------------------------------------------------------------------ %%
%%  VERIFICATION  (defensive: checks the solution satisfies facts)     %%
%% ------------------------------------------------------------------ %%

verify_allocation(Allocation, TCO) :-
    forall(member(alloc(Part, Qs), Allocation), verify_part(Part, Qs)),
    verify_global_capacity(Allocation),
    verify_risk(Allocation),
    verify_global_share(Allocation),
    verify_routes(Allocation),
    verify_qualification(Allocation),
    verify_tco(Allocation, TCO).

%! verify_routes(+Allocation) is det.
%  Checks route_capacity/2 and max_route_share/2 on the materialized award.
verify_routes(Allocation) :-
    total_demand_from_alloc(Allocation, TotalDemand),
    forall(( routes(Rs), member(Route, Rs) ),
           verify_route(Route, Allocation, TotalDemand)).

verify_route(Route, Allocation, TotalDemand) :-
    route_total_alloc(Route, Allocation, Total),
    (   route_capacity(Route, Cap)
    ->  (   Total =< Cap
        ->  true
        ;   format('  !! ROUTE CAP VIOLATION: ~w total=~w > ~w~n',
                   [Route, Total, Cap])
        )
    ;   true
    ),
    (   max_route_share(Route, Pct)
    ->  (   Total * 100 =< Pct * TotalDemand
        ->  true
        ;   ActualPct is Total * 100 / TotalDemand,
            format('  !! ROUTE SHARE VIOLATION: ~w at ~2f% > ~w%~n',
                   [Route, ActualPct, Pct])
        )
    ;   true
    ).

route_total_alloc(Route, Allocation, Total) :-
    findall(Q,
            ( member(alloc(_, Qs), Allocation),
              member(q(Supplier, Q), Qs),
              supplier_route(Supplier, Route)
            ),
            RouteQs),
    sum_list(RouteQs, Total).

%! verify_qualification(+Allocation) is det.
%  No disqualified supplier may hold a positive allocation.
verify_qualification(Allocation) :-
    forall(( member(alloc(Part, Qs), Allocation),
             member(q(Supplier, Q), Qs),
             Q > 0
           ),
           (   qualified(Part, Supplier)
           ->  true
           ;   disqualified(Part, Supplier, Reason),
               format('  !! QUALIFICATION VIOLATION: ~w/~w allocated ~w but disqualified: ~w~n',
                      [Supplier, Part, Q, Reason])
           )).

verify_part(Part, Qs) :-
    demand(Part, Demand),
    findall(Q, member(q(_, Q), Qs), Quantities),
    sum_list(Quantities, Sum),
    (   Sum =:= Demand
    ->  true
    ;   format('  !! DEMAND VIOLATION: part ~w sum=~w demand=~w~n',
               [Part, Sum, Demand])
    ),
    forall(member(q(Supplier, Q), Qs),
           verify_pair(Part, Supplier, Q, Demand)).

verify_pair(Part, Supplier, Q, Demand) :-
    (   Q =:= 0
    ->  true
    ;   moq_of(Supplier, Part, Moq),
        (   Q >= Moq -> true
        ;   format('  !! MOQ VIOLATION: ~w/~w Q=~w < MOQ=~w~n',
                   [Supplier, Part, Q, Moq])
        ),
        capacity_of(Supplier, Part, Cap),
        (   Cap == sup -> true
        ;   Q =< Cap -> true
        ;   format('  !! CAPACITY VIOLATION: ~w/~w Q=~w > Cap=~w~n',
                   [Supplier, Part, Q, Cap])
        ),
        share_of(Part, Supplier, MinPct, MaxPct),
        Pct is Q * 100 / Demand,
        (   Pct >= MinPct, Pct =< MaxPct -> true
        ;   format('  !! SHARE VIOLATION: ~w/~w ~w% not in [~w,~w]~n',
                   [Supplier, Part, Pct, MinPct, MaxPct])
        ),
        (   has_tiers(Supplier, Part)
        ->  (   find_active_tier(Supplier, Part, Q, _)
            ->  true
            ;   format('  !! TIER VIOLATION: ~w/~w Q=~w not in any tier~n',
                       [Supplier, Part, Q])
            )
        ;   true
        )
    ).

verify_global_capacity(Allocation) :-
    forall(global_capacity(Supplier, Cap),
           ( findall(Q,
                     ( member(alloc(_, Qs), Allocation),
                       member(q(Supplier, Q), Qs)
                     ),
                     SupplierQs),
             sum_list(SupplierQs, Total),
             (   Total =< Cap -> true
             ;   format('  !! GLOBAL CAP VIOLATION: ~w total=~w > ~w~n',
                        [Supplier, Total, Cap])
             )
           )).

verify_tco(Allocation, TCO) :-
    findall(CostC,
            ( member(alloc(Part, Qs), Allocation),
              member(q(Supplier, Q), Qs),
              verify_pair_cost(Part, Supplier, Q, CostC)
            ),
            CostCs),
    sum_list(CostCs, BaseComputed),
    % Apply rebates: for each supplier with a rebate, compute discount
    findall(Supplier, rebate(Supplier, _, _), RebateSuppliers),
    sort(RebateSuppliers, RebateSuppliers),
    verify_rebate_savings(RebateSuppliers, Allocation, CostCs, RebateSavingsTotal),
    Computed is BaseComputed - RebateSavingsTotal,
    (   Computed =:= TCO
    ->  true
    ;   format('  !! TCO MISMATCH: computed=~w reported=~w~n',
               [Computed, TCO])
    ).

verify_rebate_savings([], _, _, 0).
verify_rebate_savings([S|Rest], Allocation, AllCostCs, Total) :-
    rebate(S, Threshold, Pct),
    supplier_total_q(S, Allocation, TotalQ),
    (   TotalQ >= Threshold
    ->  supplier_total_cost(S, Allocation, AllCostCs, SuppCost),
        % Use the same formula as the solver: SuppCost * (100 - Pct) // 100
        DiscountedCost is SuppCost * (100 - Pct) // 100,
        Saving is SuppCost - DiscountedCost
    ;   Saving = 0
    ),
    verify_rebate_savings(Rest, Allocation, AllCostCs, RestTotal),
    Total is Saving + RestTotal.

supplier_total_q(Supplier, Allocation, TotalQ) :-
    findall(Q, (member(alloc(_, Qs), Allocation), member(q(Supplier, Q), Qs)), Qs),
    sum_list(Qs, TotalQ).

supplier_total_cost(Supplier, Allocation, _AllCostCs, TotalCost) :-
    findall(CostC,
            ( member(alloc(Part, Qs), Allocation),
              member(q(Supplier, Q), Qs),
              verify_pair_cost(Part, Supplier, Q, CostC)
            ),
            SupplierCostCs),
    sum_list(SupplierCostCs, TotalCost).

%! verify_pair_cost(+Part, +Supplier, +Q, -CostC) is det.
%  Deterministic cost recomputation for a single pair (ground Q).
%  Includes fixed cost when Q > 0.
verify_pair_cost(Part, Supplier, Q, CostC) :-
    effective_unit_cost(Supplier, Part, Q, EffCost),
    VarCost is Q * EffCost,
    (   Q > 0, fixed_cost(Supplier, Part, Fixed)
    ->  CostC is VarCost + Fixed
    ;   CostC = VarCost
    ).

%% ------------------------------------------------------------------ %%
%%  RISK & GLOBAL SHARE VERIFICATION                                   %%
%% ------------------------------------------------------------------ %%

%! verify_risk(+Allocation) is det.
%  Checks min/max supplier count constraints per part.
verify_risk(Allocation) :-
    forall(member(alloc(Part, Qs), Allocation),
           verify_part_risk(Part, Qs)).

verify_part_risk(Part, Qs) :-
    findall(B, (member(q(_, Q), Qs), (Q > 0 -> B = 1 ; B = 0)), Bs),
    sum_list(Bs, ActiveCount),
    min_suppliers_of(Part, MinN),
    (   ActiveCount >= MinN -> true
    ;   format('  !! RISK VIOLATION: part ~w has ~w active suppliers, need >= ~w~n',
               [Part, ActiveCount, MinN])
    ),
    (   max_suppliers(Part, MaxN)
    ->  (   ActiveCount =< MaxN -> true
        ;   format('  !! RISK VIOLATION: part ~w has ~w active suppliers, need =< ~w~n',
                   [Part, ActiveCount, MaxN])
        )
    ;   true
    ).

%! verify_global_share(+Allocation) is det.
%  Checks max_global_share constraints per supplier.
verify_global_share(Allocation) :-
    total_demand_from_alloc(Allocation, TotalDemand),
    forall(max_global_share(Supplier, Pct),
           verify_global_share_pair(Supplier, Pct, Allocation, TotalDemand)).

%! total_demand_from_alloc(+Allocation, -TotalDemand) is det.
total_demand_from_alloc(Allocation, TotalDemand) :-
    findall(D,
            ( member(alloc(Part, _), Allocation),
              demand(Part, D)
            ),
            Demands),
    sum_list(Demands, TotalDemand).

verify_global_share_pair(Supplier, Pct, Allocation, TotalDemand) :-
    supplier_qs_across_parts_alloc(Supplier, Allocation, SupplierQs),
    sum_list(SupplierQs, SupplierTotal),
    PctActual is SupplierTotal * 100 // TotalDemand,
    (   PctActual =< Pct -> true
    ;   format('  !! GLOBAL SHARE VIOLATION: ~w has ~w% of total (max ~w%)~n',
               [Supplier, PctActual, Pct])
    ).

%! supplier_qs_across_parts_alloc(+Supplier, +Allocation, -Qs).
%  Same as supplier_qs_across_parts but works on materialized Allocation.
supplier_qs_across_parts_alloc(_, [], []).
supplier_qs_across_parts_alloc(Supplier, [alloc(_, Qs)|Rest], Out) :-
    supplier_q_in_part(Supplier, Qs, QInPart),
    append(QInPart, RestOut, Out),
    supplier_qs_across_parts_alloc(Supplier, Rest, RestOut).

%% ------------------------------------------------------------------ %%
%%  VALIDATION GUARDS                                                  %%
%% ------------------------------------------------------------------ %%

%! validate_facts is det.
%
%  Prints all validation issues. Never fails — use the output (or
%  validation_issues/1 for structured access) to diagnose.
%
validate_facts :-
    format('~n=== Fact Validation ===~n'),
    validation_issues(Issues),
    (   Issues == []
    ->  format('  No issues found.~n')
    ;   forall(member(Issue, Issues),
               ( issue_message(Issue, Msg),
                 format('  !! ~w~n', [Msg]) ))
    ),
    format('=== Validation Complete ===~n~n').

%! validation_issues(-Issues) is det.
%  All data-quality issues in the currently loaded facts.
validation_issues(Issues) :-
    findall(I, validation_issue(I), Issues).

%! validation_issue(-Issue) is nondet.
%
%  One clause per check. Each Issue is a term whose functor names the
%  problem; issue_message/2 and issue_severity/2 interpret it. Keeping
%  detection separate from reporting lets the CLI print it, the JSON API
%  serialize it, and the judgment layer reason about it.

% --- tiered pricing coverage ---
validation_issue(tier_gap(S, P, ActualMin, ExpectedMin)) :-
    tier_pair(S, P, Sorted),
    tier_gap_in(Sorted, 0, ActualMin, ExpectedMin).
validation_issue(tier_inverted(S, P, Min, Max)) :-
    price_tier(S, P, Min, Max, _),
    Max \== sup,
    Max < Min.

% --- MOQ vs capacity ---
validation_issue(moq_over_capacity(S, P, Moq, Cap)) :-
    moq(S, P, Moq),
    capacity(S, P, Cap),
    Moq > Cap.

% --- missing facts ---
validation_issue(missing_demand(P)) :-
    costed_part(P),
    \+ demand(P, _).
validation_issue(missing_cost(S, P)) :-
    constrained_pair(S, P),
    \+ allocatable(P, S).

% --- share ranges ---
validation_issue(share_out_of_range(P, S, min, MinPct)) :-
    share(P, S, MinPct, _),
    ( MinPct < 0 ; MinPct > 100 ).
validation_issue(share_out_of_range(P, S, max, MaxPct)) :-
    share(P, S, _, MaxPct),
    ( MaxPct < 0 ; MaxPct > 100 ).
validation_issue(share_min_over_max(P, S, MinPct, MaxPct)) :-
    share(P, S, MinPct, MaxPct),
    MinPct > MaxPct.

% --- share bounds that cannot sum to demand ---
validation_issue(share_minimums_exceed_demand(P, TotalMinPct)) :-
    demand(P, _),
    findall(Min, ( share(P, S, Min, _), allocatable(P, S) ), Mins),
    Mins \== [],
    sum_list(Mins, TotalMinPct),
    TotalMinPct > 100.
validation_issue(share_maximums_below_demand(P, TotalMaxPct)) :-
    demand(P, D),
    D > 0,
    findall(Max, ( allocatable(P, S), share_of(P, S, _, Max) ), Maxes),
    Maxes \== [],
    sum_list(Maxes, TotalMaxPct),
    TotalMaxPct < 100.

% --- capacity that cannot meet demand ---
validation_issue(capacity_below_demand(P, TotalCap, Demand)) :-
    demand(P, Demand),
    Demand > 0,
    findall(S, ( allocatable(P, S), qualified(P, S) ), Suppliers),
    Suppliers \== [],
    all_capped(Suppliers, P),
    findall(C, ( member(S, Suppliers), capacity_of(S, P, C) ), Caps),
    sum_list(Caps, TotalCap),
    TotalCap < Demand.

% --- qualification gates ---
validation_issue(all_suppliers_disqualified(P)) :-
    parts(Parts),
    member(P, Parts),
    findall(S, allocatable_supplier(P, S), All),
    All \== [],
    \+ ( member(S, All), qualified(P, S) ).
validation_issue(supplier_disqualified(P, S, Reasons)) :-
    parts(Parts),
    member(P, Parts),
    allocatable_supplier(P, S),
    findall(R, disqualified(P, S, R), Reasons),
    Reasons \== [].

%% --- helpers for the checks above ---

tier_pair(S, P, Sorted) :-
    findall(S0-P0, price_tier(S0, P0, _, _, _), Pairs0),
    sort(Pairs0, Pairs),
    member(S-P, Pairs),
    findall(tier(Min, Max), price_tier(S, P, Min, Max, _), Tiers),
    sort(0, @=<, Tiers, Sorted).

tier_gap_in([tier(Min, Max)|Rest], Expected, ActualMin, ExpectedMin) :-
    (   Min =\= Expected
    ->  ActualMin = Min, ExpectedMin = Expected
    ;   Max \== sup,
        Next is Max + 1,
        tier_gap_in(Rest, Next, ActualMin, ExpectedMin)
    ).

costed_part(P) :-
    findall(P0, ( cost(_, P0, _) ; price_tier(_, P0, _, _, _) ), Ps0),
    sort(Ps0, Ps),
    member(P, Ps).

constrained_pair(S, P) :-
    findall(S0-P0,
            ( capacity(S0, P0, _) ; moq(S0, P0, _) ; share(P0, S0, _, _) ),
            Pairs0),
    sort(Pairs0, Pairs),
    member(S-P, Pairs).

all_capped([], _).
all_capped([S|Ss], P) :-
    capacity(S, P, _),
    all_capped(Ss, P).

%! issue_severity(+Issue, -Severity) is det.
%  error   — the model is unsolvable or will produce a wrong answer
%  warning — suspicious data that may not be what was intended
%  info    — expected consequence of a rule, surfaced for transparency
issue_severity(missing_demand(_),                  error).
issue_severity(missing_cost(_, _),                 warning).
issue_severity(tier_gap(_, _, _, _),               error).
issue_severity(tier_inverted(_, _, _, _),          error).
issue_severity(moq_over_capacity(_, _, _, _),      error).
issue_severity(share_out_of_range(_, _, _, _),     error).
issue_severity(share_min_over_max(_, _, _, _),     error).
issue_severity(share_minimums_exceed_demand(_, _), error).
issue_severity(share_maximums_below_demand(_, _),  error).
issue_severity(capacity_below_demand(_, _, _),     error).
issue_severity(all_suppliers_disqualified(_),      error).
issue_severity(supplier_disqualified(_, _, _),     info).

%! issue_message(+Issue, -Message) is det.
%  Plain-language description — no Prolog jargon, safe to show a buyer.
issue_message(missing_demand(P), Msg) :-
    format(atom(Msg),
           'Part ~w has prices but no demand quantity, so it will be ignored.',
           [P]).
issue_message(missing_cost(S, P), Msg) :-
    format(atom(Msg),
           'Supplier ~w has rules (capacity/MOQ/share) for ~w but no price, so it cannot be awarded any volume.',
           [S, P]).
issue_message(tier_gap(S, P, Actual, Expected), Msg) :-
    format(atom(Msg),
           'Price breaks for ~w on ~w have a gap: the next tier starts at ~w but ~w is uncovered.',
           [S, P, Actual, Expected]).
issue_message(tier_inverted(S, P, Min, Max), Msg) :-
    format(atom(Msg),
           'Price break for ~w on ~w runs from ~w to ~w, which is backwards.',
           [S, P, Min, Max]).
issue_message(moq_over_capacity(S, P, Moq, Cap), Msg) :-
    format(atom(Msg),
           'Supplier ~w requires a minimum order of ~w on ~w but can only make ~w, so they can never be used.',
           [S, Moq, P, Cap]).
issue_message(share_out_of_range(P, S, Which, Value), Msg) :-
    format(atom(Msg),
           'The ~w share for ~w on ~w is ~w%, which is outside 0-100%.',
           [Which, S, P, Value]).
issue_message(share_min_over_max(P, S, Min, Max), Msg) :-
    format(atom(Msg),
           'Supplier ~w on ~w must win at least ~w% but at most ~w% — those cannot both hold.',
           [S, P, Min, Max]).
issue_message(share_minimums_exceed_demand(P, Total), Msg) :-
    format(atom(Msg),
           'Minimum shares on ~w add up to ~w% of demand, which is more than 100% — no award can satisfy them all.',
           [P, Total]).
issue_message(share_maximums_below_demand(P, Total), Msg) :-
    format(atom(Msg),
           'Maximum shares on ~w add up to only ~w% of demand, so the full quantity cannot be placed.',
           [P, Total]).
issue_message(capacity_below_demand(P, TotalCap, Demand), Msg) :-
    format(atom(Msg),
           'Qualified suppliers for ~w can supply ~w units in total but ~w are needed.',
           [P, TotalCap, Demand]).
issue_message(all_suppliers_disqualified(P), Msg) :-
    format(atom(Msg),
           'Every supplier for ~w fails your qualification rules, so ~w cannot be sourced at all.',
           [P, P]).
issue_message(supplier_disqualified(P, S, Reasons), Msg) :-
    reasons_phrase(Reasons, Phrase),
    format(atom(Msg),
           'Supplier ~w is excluded from ~w: ~w.',
           [S, P, Phrase]).

%! reasons_phrase(+Reasons, -Phrase) is det.
reasons_phrase([R], Phrase) :- !, reason_phrase(R, Phrase).
reasons_phrase([R|Rest], Phrase) :-
    reason_phrase(R, Head),
    reasons_phrase(Rest, Tail),
    format(atom(Phrase), '~w; ~w', [Head, Tail]).

reason_phrase(otif_below_threshold(unknown, Threshold), Phrase) :- !,
    format(atom(Phrase),
           'no on-time delivery record, and ~w% is required', [Threshold]).
reason_phrase(otif_below_threshold(Actual, Threshold), Phrase) :- !,
    format(atom(Phrase),
           'on-time delivery is ~w%, below the required ~w%', [Actual, Threshold]).
reason_phrase(lead_time_exceeded(unknown, MaxDays), Phrase) :- !,
    format(atom(Phrase),
           'no quoted lead time, and the limit is ~w days', [MaxDays]).
reason_phrase(lead_time_exceeded(Actual, MaxDays), Phrase) :- !,
    format(atom(Phrase),
           'lead time is ~w days, over the ~w day limit', [Actual, MaxDays]).
reason_phrase(missing_certification(Cert), Phrase) :- !,
    format(atom(Phrase), 'missing the ~w certification', [Cert]).
reason_phrase(Other, Phrase) :-
    format(atom(Phrase), '~w', [Other]).

%% ------------------------------------------------------------------ %%
%%  EXAMPLE QUERIES                                                    %%
%% ------------------------------------------------------------------ %%

%% ?- solve(A, TCO), print_allocation(A, TCO).
%%
%% ?- solve(A, TCO, 20000), print_allocation(A, TCO).
%%
%% ?- validate_facts.
