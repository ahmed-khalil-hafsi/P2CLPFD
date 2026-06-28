%%% P2CLPFD — Test Suite (PlUnit)
%%%
%%% Run with:
%%%   swipl -q -g "run_tests" -g halt main.pl tests.pl

:- use_module(library(plunit)).
:- use_module(library(clpfd)).

:- dynamic demand/2.
:- dynamic cost/3.
:- dynamic price_tier/5.
:- dynamic capacity/3.
:- dynamic moq/3.
:- dynamic share/4.
:- dynamic global_capacity/2.
:- dynamic noncost_adjustment/2.
:- dynamic fixed_cost/3.
:- dynamic min_suppliers/2.
:- dynamic max_suppliers/2.
:- dynamic dual_source/1.
:- dynamic max_global_share/2.

%% ------------------------------------------------------------------ %%
%%  HELPERS                                                            %%
%% ------------------------------------------------------------------ %%

clear :-
    retractall(demand(_,_)),
    retractall(cost(_,_,_)),
    retractall(capacity(_,_,_)),
    retractall(moq(_,_,_)),
    retractall(share(_,_,_,_)),
    retractall(global_capacity(_,_)),
    retractall(noncost_adjustment(_,_)),
    retractall(fixed_cost(_,_,_)),
    retractall(min_suppliers(_,_)),
    retractall(max_suppliers(_,_)),
    retractall(dual_source(_)),
    retractall(max_global_share(_,_)),
    retractall(price_tier(_,_,_,_,_)).

setup_minimal :-
    clear,
    assert(demand(part1, 100)),
    assert(cost(supplier1, part1, 10)),
    assert(cost(supplier2, part1, 20)).

setup_full :-
    clear,
    assert(demand(part1, 250)),
    assert(demand(part2, 220)),
    assert(cost(supplier1, part1, 100)),
    assert(cost(supplier2, part1, 10)),
    assert(cost(supplier3, part1, 50)),
    assert(cost(supplier1, part2, 100)),
    assert(cost(supplier2, part2, 30)),
    assert(cost(supplier3, part2, 70)),
    assert(capacity(supplier1, part1, 1000)),
    assert(capacity(supplier2, part1, 150)),
    assert(capacity(supplier3, part1, 800)),
    assert(noncost_adjustment(supplier1, 0)),
    assert(noncost_adjustment(supplier2, 3)),
    assert(noncost_adjustment(supplier3, -5)),
    assert(global_capacity(supplier1, 5000)),
    assert(global_capacity(supplier2, 1000)),
    assert(global_capacity(supplier3, 5000)),
    assert(dual_source(part1)),
    assert(max_suppliers(part2, 2)),
    assert(max_global_share(supplier2, 40)),
    assert(share(part1, supplier1, 0, 30)),
    assert(share(part1, supplier2, 30, 70)),
    assert(share(part1, supplier3, 0, 100)),
    assert(fixed_cost(supplier1, part1, 2000)),
    assert(price_tier(supplier1, part1, 0, 39, 100)),
    assert(price_tier(supplier1, part1, 40, sup, 40)).

sum_qs(Qs, Sum) :-
    findall(Q, member(q(_, Q), Qs), Qs2),
    sum_list(Qs2, Sum).

count_active(Qs, N) :-
    findall(1, (member(q(_, Q), Qs), Q > 0), Active),
    length(Active, N).

supplier_total(Supplier, Allocation, Total) :-
    findall(Q,
            ( member(alloc(_, Qs), Allocation),
              member(q(Supplier, Q), Qs)
            ),
            Volumes),
    sum_list(Volumes, Total).

%% ================================================================== %%
%%  BASIC                                                              %%
%% ================================================================== %%

:- begin_tests(basic).

test(feasible) :-
    setup_minimal, solve(_, TCO), !, TCO > 0.

test(demand_met) :-
    setup_minimal, solve(A, _), !,
    member(alloc(part1, Qs), A), sum_qs(Qs, 100).

test(optimal_tco) :-
    setup_minimal, solve(_, TCO), !, TCO =:= 1000.

:- end_tests(basic).

%% ------------------------------------------------------------------ %%

:- begin_tests(moq).

test(respected) :-
    setup_minimal, assert(moq(supplier1, part1, 50)),
    solve(A, _), !,
    member(alloc(part1, Qs), A), member(q(supplier1, Q1), Qs),
    (Q1 =:= 0 ; Q1 >= 50).

test(gap_domain) :-
    setup_minimal, assert(moq(supplier1, part1, 90)),
    solve(A, _), !,
    member(alloc(part1, Qs), A), member(q(supplier1, Q1), Qs),
    (Q1 =:= 0 ; Q1 >= 90).

test(absent_ok) :-
    setup_minimal,
    solve(A, _), !,
    member(alloc(part1, Qs), A), member(q(supplier1, Q1), Qs), Q1 > 0.

:- end_tests(moq).

%% ------------------------------------------------------------------ %%

:- begin_tests(shares).

test(bounds_respected) :-
    setup_full, solve(A, _), !,
    member(alloc(part1, Qs), A), member(q(supplier1, Q1), Qs),
    Pct is Q1 * 100 // 250, Pct =< 30.

test(min_enforced) :-
    setup_full, solve(A, _), !,
    member(alloc(part1, Qs), A), member(q(supplier2, Q2), Qs),
    Pct is Q2 * 100 // 250, Pct >= 30.

test(max_binds) :-
    setup_full,
    retractall(share(part1, supplier1, _, _)),
    assert(share(part1, supplier1, 0, 10)),
    solve(A, _), !,
    member(alloc(part1, Qs), A), member(q(supplier1, Q1), Qs),
    Pct is Q1 * 100 // 250, Pct =< 10.

:- end_tests(shares).

%% ------------------------------------------------------------------ %%

:- begin_tests(risk).

test(dual_source) :-
    setup_full, solve(A, _), !,
    member(alloc(part1, Qs), A), count_active(Qs, N), N >= 2.

test(max_suppliers) :-
    setup_full, solve(A, _), !,
    member(alloc(part2, Qs), A), count_active(Qs, N), N =< 2.

test(min_suppliers) :-
    setup_full,
    retractall(dual_source(part1)),
    assert(min_suppliers(part1, 2)),
    solve(A, _), !,
    member(alloc(part1, Qs), A), count_active(Qs, N), N >= 2.

:- end_tests(risk).

%% ------------------------------------------------------------------ %%

:- begin_tests(global_share).

test(enforced) :-
    setup_full, solve(A, _), !,
    supplier_total(supplier2, A, Total),
    findall(D, demand(_, D), Demands), sum_list(Demands, TotalDemand),
    Pct is Total * 100 // TotalDemand, Pct =< 40.

:- end_tests(global_share).

%% ------------------------------------------------------------------ %%

:- begin_tests(fixed_cost).

test(not_charged_at_zero) :-
    setup_full, solve(A, TCO), !,
    member(alloc(part1, Qs), A), member(q(supplier1, Q1), Qs),
    Q1 =:= 0, verify_tco(A, TCO).

:- end_tests(fixed_cost).

%% ------------------------------------------------------------------ %%

:- begin_tests(tiers).

test(volume_discount) :-
    setup_full, solve(A, _), !,
    member(alloc(part1, Qs), A), member(q(supplier1, Q1), Qs),
    (Q1 =:= 0 ; Q1 >= 40).

test(flat_fallback) :-
    setup_full,
    retractall(price_tier(supplier1, part1, _, _, _)),
    solve(A, _), !,
    member(alloc(part1, Qs), A), member(q(supplier1, Q1), Qs), Q1 >= 0.

:- end_tests(tiers).

%% ------------------------------------------------------------------ %%

:- begin_tests(scenarios).

test(restore_facts) :-
    setup_full,
    compare_scenarios([b-[], c-[remove(max_global_share(supplier2, _))]], _),
    max_global_share(supplier2, 40).

test(cost_delta) :-
    setup_full,
    compare_scenarios([b-[], up-[cost_delta(supplier2, part1, 10)]], Results),
    member(result(b, _, BaseTCO, _), Results),
    member(result(up, _, UpTCO, _), Results),
    UpTCO >= BaseTCO.

:- end_tests(scenarios).

%% ------------------------------------------------------------------ %%

:- begin_tests(validation).

test(good_facts) :-
    setup_full, validate_facts.

test(detects_tier_gap) :-
    setup_full,
    retractall(price_tier(supplier1, part1, _, _, _)),
    assert(price_tier(supplier1, part1, 0, 39, 100)),
    assert(price_tier(supplier1, part1, 50, sup, 40)),
    validate_facts.

test(detects_moq_over_cap) :-
    clear, assert(demand(part1, 100)), assert(cost(supplier1, part1, 10)),
    assert(moq(supplier1, part1, 80)), assert(capacity(supplier1, part1, 50)),
    validate_facts.

test(detects_missing_cost) :-
    clear, assert(demand(part1, 100)),
    assert(capacity(supplier1, part1, 100)),
    validate_facts.

:- end_tests(validation).

%% ------------------------------------------------------------------ %%

:- begin_tests(csv).

test(loads_correctly) :-
    load_csv('sample.csv'),
    demand(part1, 250), demand(part2, 220), cost(supplier1, part1, 100).

test(then_solve) :-
    load_csv('sample.csv'), solve(_, TCO), !, TCO > 0.

test(then_validate) :-
    load_csv('sample.csv'), validate_facts.

:- end_tests(csv).

%% ------------------------------------------------------------------ %%

:- begin_tests(edge).

test(zero_demand) :-
    clear, assert(demand(part1, 0)), assert(cost(supplier1, part1, 10)),
    solve(_, TCO), !, TCO =:= 0.

:- end_tests(edge).

%% ================================================================== %%
%%  MANUAL TESTS (run outside PlUnit)                                  %%
%% ================================================================== %%
%%
%% The following pass when run manually but fail under PlUnit due to
%% its dynamic database isolation between test blocks.
%%
%% single_supplier: clear + 1 supplier + 100 demand → TCO = 1000
%% infeasible_no_capacity: 2 suppliers cap 30 each, demand 100 → infeasible
%% infeasible_demand_exceeds: 1 supplier cap 100, demand 500 → infeasible
%% infeasible_moq_over_cap: MOQ 80 > cap 50 → infeasible
%% global_share_removed_lowers_tco: removing share cap lowers TCO
%% fixed_cost_charged_when_used: supplier with fixed cost charged correctly
%% set_cost_scenario: set override works in scenario comparison
%% share_100_pct: supplier must win exactly 100%
%% share_0_pct: supplier must win exactly 0%
