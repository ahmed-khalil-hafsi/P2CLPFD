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
    parts(Parts),
    suppliers(Suppliers),
    build_model(Parts, Suppliers, RawAlloc, Vars, TCO),
    labeling([min(TCO)], Vars),
    materialize(RawAlloc, Allocation).

%! solve(-Allocation, -TCO, +MaxCost) is nondet.
%
%  As solve/2 but additionally constrains TCO =< MaxCost.
%
solve(Allocation, TCO, MaxCost) :-
    parts(Parts),
    suppliers(Suppliers),
    build_model(Parts, Suppliers, RawAlloc, Vars, TCO),
    TCO #=< MaxCost,
    labeling([min(TCO)], Vars),
    materialize(RawAlloc, Allocation).

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
    (   noncost_adjustment(Supplier, Adj)
    ->  EffCost is RawCost + Adj
    ;   EffCost = RawCost
    ).

find_active_tier(Supplier, Part, Q, RawCost) :-
    price_tier(Supplier, Part, Min, Max, RawCost),
    Q >= Min,
    (   Max == sup -> true ; Q =< Max ),
    !.

moq_of(Supplier, Part, Moq) :-
    moq(Supplier, Part, Moq), !.
moq_of(_, _, 0).

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
    sum(PartCosts, #=, TCO),
    append(VarsParts, Vars).

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
                     [q(Supplier,Q)|Qs], [CostC|Cs], [Q,B|Vs], [B|Bs]) :-
    (   allocatable(Part, Supplier)
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
%% and would detach constraints from the original q/2 terms).
qs_of([], []).
qs_of([q(_,Q)|Rest], [Q|Out]) :- qs_of(Rest, Out).

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

    % --- cost contribution (tiered or flat) ----------------------------
    (   has_tiers(Supplier, Part)
    ->  tiered_pricing(Supplier, Part, Q, CostC, TierVar),
        AuxVars = [TierVar]
    ;   effective_unit_cost(Supplier, Part, _, EffCost),
        CostC #= Q * EffCost,
        AuxVars = []
    ).

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
    (   noncost_adjustment(Supplier, Adj)
    ->  EffUnitCost #= RawUnitCost + Adj
    ;   EffUnitCost = RawUnitCost
    ),
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

build_global_capacity(Suppliers, RawAlloc) :-
    forall(member(Supplier, Suppliers),
           global_capacity_constraint(Supplier, RawAlloc)).

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
supplier_q_in_part(Supplier, [q(Supplier,Q)|Rest], [Q|Out]) :-
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
%%  MATERIALIZE  (turn raw structure into ground output)               %%
%% ------------------------------------------------------------------ %%

materialize([], []).
materialize([alloc(Part, RawQs)|Rest], [alloc(Part, Qs)|Out]) :-
    materialize_qs(RawQs, Qs),
    materialize(Rest, Out).

materialize_qs([], []).
materialize_qs([q(S,Q)|Rest], [q(S,Q)|Out]) :-
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
    verify_tco(Allocation, TCO).

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
    sum_list(CostCs, Computed),
    (   Computed =:= TCO
    ->  true
    ;   format('  !! TCO MISMATCH: computed=~w reported=~w~n',
               [Computed, TCO])
    ).

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
%%  EXAMPLE QUERIES                                                    %%
%% ------------------------------------------------------------------ %%

%% ?- solve(A, TCO), print_allocation(A, TCO).
%%
%% ?- solve(A, TCO, 20000), print_allocation(A, TCO).
