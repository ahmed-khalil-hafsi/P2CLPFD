%%% P2CLPFD — Problem Decomposition
%%%
%%% Minimizing a SUM couples everything the sum touches. Branch-and-bound
%%% on `TCO = cost(partA) + cost(partB)` must search the product of both
%%% parts' spaces to prove the total is minimal, even when the two parts
%%% share nothing at all: knowing `costA + costB < Best` says very little
%%% about either one alone. Two independent parts that each solve in a
%%% second can together run for hours.
%%%
%%% Two remedies, both exact — neither ever changes the optimum:
%%%
%%%   1. INDEPENDENT PARTS -> solve separately, concatenate.
%%%      When no constraint spans parts, the optimal award for each part
%%%      is optimal for the whole. N small searches beat one big product.
%%%
%%%   2. COUPLED PARTS -> post a lower bound before searching.
%%%      Solving each part with the cross-part rules DROPPED can only
%%%      make it cheaper, so the sum of those relaxed optima is a valid
%%%      floor for the true TCO. Handing that floor to branch-and-bound
%%%      lets it stop as soon as it reaches the bound instead of
%%%      exhaustively proving no better solution exists.
%%%
%%% What couples parts (everything else is per-part):
%%%   rebate/3               discount depends on volume across all parts
%%%   max_global_share/2     supplier's share of TOTAL demand
%%%   global_capacity/2      supplier's total across all parts (if it can bind)
%%%   route_capacity/2       group ceiling across all parts
%%%   max_route_share/2      group share of TOTAL demand

:- use_module(library(clpfd)).

%% ------------------------------------------------------------------ %%
%%  COUPLING DETECTION                                                 %%
%% ------------------------------------------------------------------ %%

%! parts_are_coupled is semidet.
%  True when any constraint spans more than one part. A global capacity
%  at least as large as total demand can never bind, so it does not count.
parts_are_coupled :-
    rebate_coupling, !.
parts_are_coupled :-
    max_global_share(_, Pct), Pct < 100, !.
parts_are_coupled :-
    supplier_route(_, Route),
    (   route_capacity(Route, _) ; max_route_share(Route, _) ), !.
parts_are_coupled :-
    parts(Parts),
    total_demand(Parts, TotalDemand),
    global_capacity(_, Cap),
    Cap < TotalDemand, !.

%! rebate_coupling is semidet.
%
%  Whether any rebate still ties the parts together.
%
%  Undecided (no forced branch)  -> coupled; the discount depends on the
%                                   combined volume.
%  Forced earned                 -> coupled; the threshold is a hard
%                                   floor spanning every part.
%  Forced not-earned             -> coupled only if the supplier could
%                                   actually reach the threshold. When
%                                   their capacity cannot get there, the
%                                   ceiling is slack and constrains
%                                   nothing, so the parts separate.
%
rebate_coupling :-
    rebate(Supplier, Threshold, _),
    (   rebate_forced(Supplier, 1)
    ->  true
    ;   rebate_forced(Supplier, 0)
    ->  supplier_max_volume(Supplier, Max),
        Max >= Threshold
    ;   true
    ),
    !.

%! supplier_max_volume(+Supplier, -Max) is det.
%  The most this supplier could ever ship across all parts, from their
%  per-part capacity (or the part's whole demand where uncapped).
supplier_max_volume(Supplier, Max) :-
    parts(Parts),
    findall(V,
            ( member(Part, Parts),
              allocatable(Part, Supplier),
              demand(Part, D),
              (   capacity(Supplier, Part, Cap)
              ->  V is min(Cap, D)
              ;   V = D
              )
            ),
            Vs),
    sum_list(Vs, Max).

%% ------------------------------------------------------------------ %%
%%  1. INDEPENDENT DECOMPOSITION                                       %%
%% ------------------------------------------------------------------ %%

%! solve_decomposed(-Allocation, -TCO) is semidet.
%
%  Solve each part on its own and concatenate. Only valid when
%  parts_are_coupled/0 is false — the caller must check.
%  Deterministic: yields the optimum once, no alternative solutions.
%
solve_decomposed(Allocation, TCO) :-
    parts(Parts),
    suppliers(Suppliers),
    solve_each_part(Parts, Suppliers, Allocation, Costs),
    sum_list(Costs, TCO).

solve_each_part([], _, [], []).
solve_each_part([Part|Rest], Suppliers, [PartAlloc|Allocs], [Cost|Costs]) :-
    part_optimum(Part, Suppliers, PartAlloc, Cost),
    solve_each_part(Rest, Suppliers, Allocs, Costs).

%! part_optimum(+Part, +Suppliers, -PartAlloc, -Cost) is semidet.
%
%  The cheapest award for ONE part under its own rules only (capacity,
%  MOQ, shares, supplier counts, tiers, fixed costs, qualification).
%  Cross-part rules are not posted here.
%
%  findall/3 extracts ground integers, so the constraint store this
%  builds is discarded rather than leaking into the caller's model.
%
%  once/1 is essential: labeling/2 with min/1 yields the optimum first
%  and then EVERY remaining solution in increasing cost order, so a bare
%  findall/3 would enumerate the entire feasible space.
part_optimum(Part, Suppliers, alloc(Part, Qs), Cost) :-
    findall(GroundQs-C,
            once(part_optimum_(Part, Suppliers, GroundQs, C)),
            [Qs-Cost]).

part_optimum_(Part, Suppliers, Qs, Cost) :-
    build_parts([Part], Suppliers, RawAlloc, [PartCost], VarsNested, AllBs),
    post_risk_constraints([Part], AllBs),
    append(VarsNested, Vars),
    labeling([min(PartCost), ff], Vars),
    Cost = PartCost,
    materialize(RawAlloc, [alloc(Part, Qs)]).

%% ------------------------------------------------------------------ %%
%%  1b. REBATE STATE ENUMERATION                                       %%
%% ------------------------------------------------------------------ %%
%
%  A rebate makes the objective step: cross the volume threshold and the
%  supplier's entire spend is discounted. Modelled with reification that
%  step is expensive to optimize over — branch-and-bound cannot bound the
%  discounted cost tightly until the threshold variable is decided.
%
%  But there are only two possibilities per rebate: earned, or not. Fix
%  the choice up front and each branch becomes an ordinary linear problem
%  with one extra volume constraint. Solving all 2^N branches and keeping
%  the cheapest is exact — the branches are exhaustive and disjoint — and
%  in practice far faster than one reified search.
%
%  N is the number of suppliers with a rebate, normally one or two.

%! solve_rebate_enumerated(-Allocation, -TCO) is semidet.
solve_rebate_enumerated(Allocation, TCO) :-
    rebate_suppliers(Suppliers),
    findall(Cost-Alloc,
            ( rebate_assignment(Suppliers, Assignment),
              once(solve_under_assignment(Assignment, Alloc, Cost))
            ),
            Results),
    Results \== [],
    keysort(Results, [TCO-Allocation|_]).

rebate_suppliers(Suppliers) :-
    findall(S, rebate(S, _, _), Ss),
    sort(Ss, Suppliers).

%! rebate_assignment(+Suppliers, -Assignment) is multi.
%  Every combination of earned/not-earned across the rebate suppliers.
rebate_assignment([], []).
rebate_assignment([S|Ss], [S-State|Rest]) :-
    member(State, [1, 0]),          % try "earned" first: usually cheaper
    rebate_assignment(Ss, Rest).

%! solve_under_assignment(+Assignment, -Allocation, -TCO) is semidet.
%  Solve with each rebate's branch pinned. Fails when the assignment is
%  unreachable (e.g. the threshold exceeds what the supplier can make),
%  which simply removes that branch from consideration.
solve_under_assignment(Assignment, Allocation, TCO) :-
    setup_call_cleanup(
        force_rebates(Assignment),
        solve_dispatch(Allocation, TCO),
        retractall(rebate_forced(_, _))
    ).

force_rebates([]).
force_rebates([S-State|Rest]) :-
    assertz(rebate_forced(S, State)),
    force_rebates(Rest).

%% ------------------------------------------------------------------ %%
%%  2. LOWER BOUND FOR COUPLED PROBLEMS                                %%
%% ------------------------------------------------------------------ %%

%! tco_lower_bound(-LowerBound) is semidet.
%
%  Sum of each part's relaxed optimum, then reduced by the largest
%  rebate on offer. Dropping cross-part rules can only lower cost, and
%  a rebate can only lower it further, so the result never exceeds the
%  true optimum — which is exactly what makes it a safe bound to post.
%
%  Fails when any part is infeasible on its own rules, which means the
%  whole model is infeasible too.
%
tco_lower_bound(LowerBound) :-
    parts(Parts),
    suppliers(Suppliers),
    part_lower_bounds(Parts, Suppliers, Costs),
    sum_list(Costs, Raw),
    max_rebate_pct(MaxPct),
    LowerBound is (Raw * (100 - MaxPct)) // 100.

part_lower_bounds([], _, []).
part_lower_bounds([Part|Rest], Suppliers, [Cost|Costs]) :-
    part_optimum(Part, Suppliers, _, Cost),
    part_lower_bounds(Rest, Suppliers, Costs).

%! max_rebate_pct(-Pct) is det.
max_rebate_pct(Pct) :-
    findall(P, rebate(_, _, P), Pcts),
    (   Pcts == []
    ->  Pct = 0
    ;   max_list(Pcts, Pct)
    ).

%! post_tco_lower_bound(+TCO) is det.
%
%  Best-effort: if the bound cannot be computed (a part is infeasible in
%  isolation) the model is left untouched and the main search decides.
%
post_tco_lower_bound(TCO) :-
    (   tco_lower_bound(LB)
    ->  TCO #>= LB
    ;   true
    ).
