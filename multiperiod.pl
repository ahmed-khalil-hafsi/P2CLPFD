%%% P2CLPFD — Multi-Period Allocation with Inventory Carryover
%%%
%%% Extends the solver across time: demand varies per period, capacity
%%% is enforced per period, and the solver may BUY AHEAD and carry
%%% inventory at a holding cost when that beats buying in-period
%%% (e.g. a capacity crunch in Q2 met by overbuying in Q1).
%%%
%%% This is an additive model: solve/2 (single-period) is untouched.
%%% Multi-period facts:
%%%
%%%   period_demand(Part, Period, Qty).
%%%       Demand per period. Periods are consecutive integers 1..N.
%%%       Presence of period_demand/3 facts activates this model.
%%%
%%%   period_capacity(Supplier, Part, Period, MaxQty).   % optional
%%%       Per-period pair capacity. Falls back to capacity/3 (applied
%%%       per period), then unlimited.
%%%
%%%   holding_cost(Part, PerUnitPerPeriod).              % optional
%%%       Cost of carrying one unit of Part across one period boundary.
%%%       Absent => 0 (carrying is free — rarely what you want).
%%%
%%% Reused single-period facts: cost/3 (with landed FX/logistics and
%%% noncost_adjustment folded in), moq/3 (applies per order per period),
%%% global_capacity/2 (interpreted PER PERIOD across parts), and
%%% qualification gates (otif / lead time / certifications).
%%%
%%% v1 limitations (documented, enforced by ignoring the facts):
%%% tiered pricing, rebates, share strategies, fixed costs, and
%%% supplier-count rules are not applied in the multi-period model.
%%%
%%% Usage:
%%%   ?- solve_multiperiod(Plan, TCO).
%%%   ?- print_multiperiod(Plan, TCO).
%%%
%%% Plan = list of mp(Part, Period, [q(Supplier,Qty),...], EndInventory)

:- use_module(library(clpfd)).

:- dynamic period_demand/3.
:- dynamic period_capacity/4.
:- dynamic holding_cost/2.

%% ------------------------------------------------------------------ %%
%%  PUBLIC API                                                         %%
%% ------------------------------------------------------------------ %%

%! solve_multiperiod(-Plan, -TCO) is nondet.
solve_multiperiod(Plan, TCO) :-
    mp_parts(Parts),
    Parts \= [],
    mp_periods(Periods),
    suppliers(Suppliers),
    mp_build(Parts, Periods, Suppliers, RawPlan, Vars, TCO),
    minimize_cost(TCO, Vars),
    mp_materialize(RawPlan, Plan).

mp_parts(Parts) :-
    findall(P, period_demand(P, _, _), Ps),
    sort(Ps, Parts).

mp_periods(Periods) :-
    findall(T, period_demand(_, T, _), Ts),
    sort(Ts, Periods).

mp_demand(Part, Period, D) :-
    (   period_demand(Part, Period, D0)
    ->  D = D0
    ;   D = 0
    ).

mp_capacity(Supplier, Part, Period, Cap) :-
    (   period_capacity(Supplier, Part, Period, Cap0)
    ->  Cap = Cap0
    ;   capacity(Supplier, Part, Cap0)
    ->  Cap = Cap0
    ;   Cap = sup
    ).

holding_cost_of(Part, H) :-
    (   holding_cost(Part, H0)
    ->  H = H0
    ;   H = 0
    ).

%% ------------------------------------------------------------------ %%
%%  MODEL                                                              %%
%% ------------------------------------------------------------------ %%

mp_build(Parts, Periods, Suppliers, RawPlan, Vars, TCO) :-
    mp_build_parts(Parts, Periods, Suppliers, RawPlan, CostTerms, Vars),
    mp_global_capacity(Suppliers, Periods, RawPlan),
    sum(CostTerms, #=, TCO).

mp_build_parts([], _, _, [], [], []).
mp_build_parts([Part|Rest], Periods, Suppliers, Plan, Costs, Vars) :-
    total_part_demand(Part, Periods, MaxQ),
    mp_build_periods(Part, Periods, Suppliers, MaxQ, 0, PartPlan, PartCosts, PartVars),
    mp_build_parts(Rest, Periods, Suppliers, RestPlan, RestCosts, RestVars),
    append(PartPlan, RestPlan, Plan),
    append(PartCosts, RestCosts, Costs),
    append(PartVars, RestVars, Vars).

total_part_demand(Part, Periods, Total) :-
    findall(D, (member(T, Periods), mp_demand(Part, T, D)), Ds),
    sum_list(Ds, Total).

%% Chain periods for one part, threading inventory.
mp_build_periods(_, [], _, _, _, [], [], []).
mp_build_periods(Part, [T|Ts], Suppliers, MaxQ, PrevInv,
                 [mp(Part, T, Qs, Inv)|RestPlan],
                 Costs, Vars) :-
    mp_demand(Part, T, D),
    mp_build_pairs(Part, T, Suppliers, MaxQ, Qs, PairCosts, QVars),
    qs_of_mp(Qs, QOnly),
    sum(QOnly, #=, Supply),
    Inv #= PrevInv + Supply - D,
    Inv #>= 0,
    Inv #=< MaxQ,
    holding_cost_of(Part, H),
    HoldCost #= Inv * H,
    mp_build_periods(Part, Ts, Suppliers, MaxQ, Inv, RestPlan, RestCosts, RestVars),
    append(PairCosts, [HoldCost|RestCosts], Costs),
    append(QVars, [Inv|RestVars], Vars).

qs_of_mp([], []).
qs_of_mp([q(_, Q)|Rest], [Q|Out]) :- qs_of_mp(Rest, Out).

%% Per (part, period, supplier): capacity, MOQ, qualification, cost.
mp_build_pairs(_, _, [], _, [], [], []).
mp_build_pairs(Part, T, [S|Ss], MaxQ, [q(S, Q)|Qs], Costs, Vars) :-
    (   cost(S, Part, _),
        qualified(Part, S)
    ->  Q in 0..MaxQ,
        mp_capacity(S, Part, T, Cap),
        (   Cap == sup -> true ; Q #=< Cap ),
        moq_of(S, Part, Moq),
        (   Moq =< 0 -> true ; Q in 0 \/ Moq..sup ),
        effective_unit_cost(S, Part, _, EffCost),
        CostC #= Q * EffCost,
        Costs = [CostC|RestCosts],
        Vars = [Q|RestVars]
    ;   Q = 0,
        Costs = RestCosts,
        Vars = RestVars
    ),
    mp_build_pairs(Part, T, Ss, MaxQ, Qs, RestCosts, RestVars).

%% Global supplier capacity, per period, across parts.
%% Direct recursion, NOT forall/2 — see build_global_capacity/2 in solver.pl.
mp_global_capacity([], _, _).
mp_global_capacity([S|Ss], Periods, RawPlan) :-
    (   global_capacity(S, Cap)
    ->  mp_global_cap_periods(S, Cap, Periods, RawPlan)
    ;   true
    ),
    mp_global_capacity(Ss, Periods, RawPlan).

mp_global_cap_periods(_, _, [], _).
mp_global_cap_periods(S, Cap, [T|Ts], RawPlan) :-
    mp_global_cap_one(S, Cap, T, RawPlan),
    mp_global_cap_periods(S, Cap, Ts, RawPlan).

mp_global_cap_one(S, Cap, T, RawPlan) :-
    mp_supplier_period_qs(S, T, RawPlan, Qs),
    (   Qs == []
    ->  true
    ;   sum(Qs, #=<, Cap)
    ).

mp_supplier_period_qs(_, _, [], []).
mp_supplier_period_qs(S, T, [mp(_, T0, Qs, _)|Rest], Out) :-
    (   T0 == T,
        mp_q_of_supplier(S, Qs, Q)
    ->  Out = [Q|RestOut]
    ;   Out = RestOut
    ),
    mp_supplier_period_qs(S, T, Rest, RestOut).

mp_q_of_supplier(S, [q(S, Q)|_], Q) :- !.
mp_q_of_supplier(S, [_|Rest], Q) :- mp_q_of_supplier(S, Rest, Q).

%% ------------------------------------------------------------------ %%
%%  MATERIALIZE                                                        %%
%% ------------------------------------------------------------------ %%

mp_materialize([], []).
mp_materialize([mp(P, T, Qs, Inv)|Rest], [mp(P, T, Qs, Inv)|Out]) :-
    % After labeling everything is ground; keep the same shape.
    mp_materialize(Rest, Out).

%% ------------------------------------------------------------------ %%
%%  JSON                                                               %%
%% ------------------------------------------------------------------ %%

%! solve_multiperiod_to_json(-JSON) is det.
solve_multiperiod_to_json(JSON) :-
    (   solve_multiperiod(Plan, TCO)
    ->  findall(Row,
                ( member(mp(P, T, Qs, Inv), Plan),
                  findall(_{supplier:S, qty:Q},
                          ( member(q(S, Q), Qs), Q > 0 ),
                          Sup),
                  Row = _{part:P, period:T, suppliers:Sup,
                          end_inventory:Inv}
                ),
                Rows),
        JSON = _{status:ok, tco:TCO, plan:Rows}
    ;   JSON = _{status:infeasible, tco:null, plan:[]}
    ).

%% ------------------------------------------------------------------ %%
%%  PRETTY PRINTING                                                    %%
%% ------------------------------------------------------------------ %%

print_multiperiod(Plan, TCO) :-
    format('~n=== Multi-Period Plan ===~n'),
    mp_periods(Periods),
    forall(member(T, Periods),
           ( format('~nPeriod ~w:~n', [T]),
             forall(member(mp(P, T, Qs, Inv), Plan),
                    ( mp_demand(P, T, D),
                      format('  ~w (demand ~w):', [P, D]),
                      forall(( member(q(S, Q), Qs), Q > 0 ),
                             format(' ~w=~w', [S, Q])),
                      format('  [carry ~w]~n', [Inv])
                    ))
           )),
    format('~n*** Multi-period TCO (incl. holding): ~w ***~n~n', [TCO]).

%% ------------------------------------------------------------------ %%
%%  EXAMPLE                                                            %%
%% ------------------------------------------------------------------ %%

%% ?- assert(period_demand(part1, 1, 100)),
%%    assert(period_demand(part1, 2, 300)),
%%    assert(cost(s1, part1, 10)),
%%    assert(period_capacity(s1, part1, 1, 200)),
%%    assert(period_capacity(s1, part1, 2, 200)),
%%    assert(holding_cost(part1, 2)),
%%    solve_multiperiod(Plan, TCO), print_multiperiod(Plan, TCO).
