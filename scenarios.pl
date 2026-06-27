%%% P2CLPFD — Scenario Comparison
%%%
%%% Lets a category manager (or AI agent) ask "what if?" without mutating
%%% base facts. Overrides are applied temporarily, the solver runs, and the
%%% original facts are restored automatically — even on failure.
%%%
%%% Usage:
%%%   ?- solve_scenario([
%%%        set(cost(supplier2, part1, 15)),     % change price
%%%        remove(dual_source(part1)),           % remove constraint
%%%        cost_delta(supplier2, part2, 10)      % +10% to cost
%%%      ], Allocation, TCO).
%%%
%%%   ?- compare_scenarios([
%%%        baseline-[],
%%%        price_up-[cost_delta(supplier2, part1, 10)],
%%%        no_risk-[remove(dual_source(part1)), remove(max_global_share(supplier2))]
%%%      ], Results).

%% ------------------------------------------------------------------ %%
%%  PUBLIC API                                                         %%
%% ------------------------------------------------------------------ %%

%! solve_scenario(+Overrides, -Allocation, -TCO) is nondet.
%
%  Applies Overrides temporarily, solves, and restores the original facts.
%  Overrides is a list of:
%    set(Fact)              — replace matching facts with Fact
%    remove(Template)       — retract all matching facts
%    cost_delta(S, P, Pct)  — change cost by Pct% (e.g. 10 = +10%, -5 = -5%)
%    demand_delta(P, Pct)   — change demand by Pct%
%
solve_scenario(Overrides, Allocation, TCO) :-
    setup_call_cleanup(
        apply_overrides(Overrides, Undo),
        solve(Allocation, TCO),
        restore_overrides(Undo)
    ).

%! solve_scenario(+Overrides, -Allocation, -TCO, +MaxCost) is nondet.
%
%  As solve_scenario/3 but with a cost ceiling.
%
solve_scenario(Overrides, Allocation, TCO, MaxCost) :-
    setup_call_cleanup(
        apply_overrides(Overrides, Undo),
        solve(Allocation, TCO, MaxCost),
        restore_overrides(Undo)
    ).

%! compare_scenarios(+Scenarios, -Results) is det.
%
%  Solves the baseline and each scenario, returns a list of results.
%  Scenarios = [Name-Overrides, ...]
%  Results   = [result(Name, TCO, Allocation), ...]
%
compare_scenarios(Scenarios, Results) :-
    compare_scenarios(Scenarios, [], Results).

%! compare_scenarios(+Scenarios, +Options, -Results) is det.
%
%  Options:
%    max_cost(N) — apply cost ceiling to all scenarios
%
compare_scenarios(Scenarios, Options, Results) :-
    (   memberchk(max_cost(MaxCost), Options)
    ->  MaxCostOpt = MaxCost
    ;   MaxCostOpt = _
    ),
    maplist(solve_one_scenario(MaxCostOpt, Options), Scenarios, Results).

solve_one_scenario(MaxCostOpt, _Options, Name-Overrides, result(Name, Status, TCO, Allocation)) :-
    (   var(MaxCostOpt)
    ->  Goal = solve_scenario(Overrides, Alloc, T)
    ;   Goal = solve_scenario(Overrides, Alloc, T, MaxCostOpt)
    ),
    (   call(Goal)
    ->  TCO = T, Allocation = Alloc, Status = ok
    ;   TCO = -, Allocation = [], Status = infeasible
    ).

%% ------------------------------------------------------------------ %%
%%  OVERRIDE APPLICATION & RESTORE                                     %%
%% ------------------------------------------------------------------ %%

%! apply_overrides(+Overrides, -Undo).
%  Applies each override, collecting undo operations.
%  Undo is a list of restore(Fact) and reassert(Fact) terms.
%
apply_overrides([], []).
apply_overrides([O|Rest], [Undo|UndoRest]) :-
    apply_one_override(O, Undo),
    apply_overrides(Rest, UndoRest).

apply_one_override(set(Fact), Undo) :-
    !,
    functor(Fact, Name, Arity),
    functor(Template, Name, Arity),
    findall(Template, call(Template), Saved),
    retractall(Template),
    assert(Fact),
    Undo = restored(Template, Saved).

apply_one_override(remove(Template), Undo) :-
    !,
    findall(Template, call(Template), Saved),
    retractall(Template),
    Undo = restored(Template, Saved).

apply_one_override(cost_delta(Supplier, Part, Pct), Undo) :-
    !,
    (   cost(Supplier, Part, Old)
    ->  New is round(Old * (100 + Pct) / 100),
        retractall(cost(Supplier, Part, _)),
        assert(cost(Supplier, Part, New)),
        Undo = restored(cost(Supplier, Part, _), [cost(Supplier, Part, Old)])
    ;   Undo = restored(cost(Supplier, Part, _), [])
    ).

apply_one_override(demand_delta(Part, Pct), Undo) :-
    !,
    (   demand(Part, Old)
    ->  New is round(Old * (100 + Pct) / 100),
        retractall(demand(Part, _)),
        assert(demand(Part, New)),
        Undo = restored(demand(Part, _), [demand(Part, Old)])
    ;   Undo = restored(demand(Part, _), [])
    ).

%! restore_overrides(+UndoList).
%  Reverts all overrides using the saved state.
%
restore_overrides([]).
restore_overrides([restored(Template, Saved)|Rest]) :-
    retractall(Template),
    maplist(assert, Saved),
    restore_overrides(Rest).

%% ------------------------------------------------------------------ %%
%%  PRETTY PRINTING                                                    %%
%% ------------------------------------------------------------------ %%

%! print_comparison(+Results) is det.
%
%  Pretty-prints scenario comparison results.
%
print_comparison(Results) :-
    format('~n=== Scenario Comparison ===~n~n'),
    format('~w~` t~22|~w~` t~35|~w~n', ['Scenario', 'TCO', 'Status']),
    format('~`-t~45|~n'),
    maplist(print_scenario_row, Results),
    format('~`-t~45|~n~n'),
    print_deltas(Results).

print_scenario_row(result(Name, Status, TCO, _Allocation)) :-
    (   Status = ok
    ->  format('~w~` t~22|~w~` t~35|~w~n', [Name, TCO, ok])
    ;   format('~w~` t~22|~w~` t~35|~w~n', [Name, '-', infeasible])
    ).

print_deltas([result(baseline, _, BaseTCO, _) | Rest]) :-
    !,
    format('Delta vs baseline:~n'),
    forall(member(result(Name, _, TCO, _), Rest),
           (   TCO = -
           ->  format('  ~w: infeasible~n', [Name])
           ;   Delta is TCO - BaseTCO,
               Pct is round(Delta * 100 / BaseTCO),
               (   Delta >= 0
               ->  format('  ~w: +~w (+~w%)~n', [Name, Delta, Pct])
               ;   format('  ~w: ~w (~w%)~n', [Name, Delta, Pct])
               )
           )).
print_deltas(_).

%% ------------------------------------------------------------------ %%
%%  EXAMPLE QUERIES                                                    %%
%% ------------------------------------------------------------------ %%

%% ?- compare_scenarios([
%%      baseline-[],
%%      price_up_10pct-[cost_delta(supplier2, part1, 10)],
%%      no_dual_source-[remove(dual_source(part1))],
%%      no_share_cap-[remove(max_global_share(supplier2))],
%%      remove_both-[remove(dual_source(part1)), remove(max_global_share(supplier2))]
%%    ], Results), print_comparison(Results).
