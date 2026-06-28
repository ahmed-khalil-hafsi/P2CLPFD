%%% P2CLPFD — Test Suite
%%%
%%% Run with:
%%%   swipl -q -g run_tests -g halt main.pl tests.pl
%%%
%%% Or interactively:
%%%   ?- ['main.pl'], ['tests.pl'].
%%%   ?- run_tests.

:- use_module(library(clpfd)).

%% All procurement predicates must be dynamic for test isolation.
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

%% Test counter
:- dynamic test_count/1.
:- dynamic pass_count/1.
:- dynamic fail_count/1.

test_count(0).
pass_count(0).
fail_count(0).

%! run_tests is det.
run_tests :-
    retractall(test_count(_)),
    retractall(pass_count(_)),
    retractall(fail_count(_)),
    assert(test_count(0)),
    assert(pass_count(0)),
    assert(fail_count(0)),
    format('~n=== Running Tests ===~n~n'),
    findall(Name-Goal, test(Name, Goal), Tests),
    forall(member(Name-Goal, Tests), run_test(Name, Goal)),
    test_count(Total),
    pass_count(Passed),
    fail_count(Failed),
    format('~n=== Results: ~w/~w passed, ~w failed ===~n~n',
           [Passed, Total, Failed]).

run_test(Name, Goal) :-
    retract(test_count(N)),
    N1 is N + 1,
    assert(test_count(N1)),
    (   call(Goal)
    ->  format('  PASS: ~w~n', [Name]),
        retract(pass_count(P)),
        P1 is P + 1,
        assert(pass_count(P1))
    ;   format('  FAIL: ~w~n', [Name]),
        retract(fail_count(F)),
        F1 is F + 1,
        assert(fail_count(F1))
    ),
    retract_all_test_facts.

%% --- Fact save/restore for test isolation ---

save_facts(Saved) :-
    findall(demand(P,Q), demand(P,Q), D1),
    findall(cost(S,P,C), cost(S,P,C), D2),
    findall(capacity(S,P,C), capacity(S,P,C), D3),
    findall(moq(S,P,M), moq(S,P,M), D4),
    findall(share(P,S,Mn,Mx), share(P,S,Mn,Mx), D5),
    findall(global_capacity(S,C), global_capacity(S,C), D6),
    findall(noncost_adjustment(S,A), noncost_adjustment(S,A), D7),
    findall(fixed_cost(S,P,A), fixed_cost(S,P,A), D8),
    findall(min_suppliers(P,N), min_suppliers(P,N), D9),
    findall(max_suppliers(P,N), max_suppliers(P,N), D10),
    findall(dual_source(P), dual_source(P), D11),
    findall(max_global_share(S,P), max_global_share(S,P), D12),
    findall(price_tier(S,P,Mn,Mx,C), price_tier(S,P,Mn,Mx,C), D13),
    append([D1,D2,D3,D4,D5,D6,D7,D8,D9,D10,D11,D12,D13], Saved).

restore_facts(Saved) :-
    retract_all_test_facts,
    maplist(assert, Saved).

retract_all_test_facts :-
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

%% --- Helper: set up a minimal 2-supplier, 1-part scenario ---

setup_minimal :-
    assert(demand(part1, 100)),
    assert(cost(supplier1, part1, 10)),
    assert(cost(supplier2, part1, 20)).

setup_full :-
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

%% ================================================================== %%
%%  TESTS                                                              %%
%% ================================================================== %%

%% --- Basic feasibility ---

test(basic_feasible,
     (retract_all_test_facts, setup_minimal, solve(_, TCO), TCO > 0)).

test(basic_demand_met,
     (retract_all_test_facts, setup_minimal, solve(A, _),
      member(alloc(part1, Qs), A),
      sum_qs(Qs, 100))).

test(basic_optimal_tco,
     (retract_all_test_facts, setup_minimal, solve(_, TCO), TCO =:= 1000)).

%% --- Infeasibility ---

test(infeasible_no_capacity,
     (retract_all_test_facts, setup_minimal,
      assert(capacity(supplier1, part1, 30)),
      assert(capacity(supplier2, part1, 30)),
      \+ solve(_, _))).

test(infeasible_demand_exceeds_supply,
     (retract_all_test_facts,
      assert(demand(part1, 500)),
      assert(cost(supplier1, part1, 10)),
      assert(capacity(supplier1, part1, 100)),
      \+ solve(_, _))).

%% --- MOQ ---

test(moq_respected,
     (retract_all_test_facts, setup_minimal,
      assert(moq(supplier1, part1, 50)),
      solve(A, _),
      member(alloc(part1, Qs), A),
      member(q(supplier1, Q1), Qs),
      (Q1 =:= 0 ; Q1 >= 50))).

test(moq_gap_works,
     (retract_all_test_facts, setup_minimal,
      assert(moq(supplier1, part1, 90)),
      solve(A, _),
      member(alloc(part1, Qs), A),
      member(q(supplier1, Q1), Qs),
      (Q1 =:= 0 ; Q1 >= 90))).

%% --- Share bounds ---

test(share_bounds_respected,
     (retract_all_test_facts, setup_full, solve(A, _),
      member(alloc(part1, Qs), A),
      member(q(supplier1, Q1), Qs),
      Pct is Q1 * 100 // 250,
      Pct =< 30)).

test(share_min_enforced,
     (retract_all_test_facts, setup_full, solve(A, _),
      member(alloc(part1, Qs), A),
      member(q(supplier2, Q2), Qs),
      Pct is Q2 * 100 // 250,
      Pct >= 30)).

%% --- Risk constraints ---

test(dual_source_enforced,
     (retract_all_test_facts, setup_full, solve(A, _),
      member(alloc(part1, Qs), A),
      count_active(Qs, N),
      N >= 2)).

test(max_suppliers_enforced,
     (retract_all_test_facts, setup_full, solve(A, _),
      member(alloc(part2, Qs), A),
      count_active(Qs, N),
      N =< 2)).

%% --- Global share ---

test(global_share_enforced,
     (retract_all_test_facts, setup_full, solve(A, _),
      total_supplier_volume(supplier2, A, Total),
      findall(D, demand(_, D), Demands),
      sum_list(Demands, TotalDemand),
      Pct is Total * 100 // TotalDemand,
      Pct =< 40)).

%% --- Fixed costs ---

test(fixed_cost_not_charged_at_zero,
     (retract_all_test_facts, setup_full, solve(A, TCO),
      member(alloc(part1, Qs), A),
      member(q(supplier1, Q1), Qs),
      Q1 =:= 0,
      verify_tco(A, TCO))).

%% --- Tiered pricing ---

test(tier_picks_volume_discount,
     (retract_all_test_facts, setup_full, solve(A, _),
      member(alloc(part1, Qs), A),
      member(q(supplier1, Q1), Qs),
      (Q1 =:= 0 ; Q1 >= 40))).

%% --- Scenario comparison ---

test(scenario_restore_facts,
     (retract_all_test_facts, setup_full,
      compare_scenarios([baseline-[], no_cap-[remove(max_global_share(supplier2, _))]], _),
      max_global_share(supplier2, 40))).

test(scenario_cost_delta,
     (retract_all_test_facts, setup_full,
      compare_scenarios([base-[], up-[cost_delta(supplier2, part1, 10)]], Results),
      member(result(base, _, BaseTCO, _), Results),
      member(result(up, _, UpTCO, _), Results),
      UpTCO >= BaseTCO)).

%% --- Validation ---

test(validation_passes_on_good_facts,
     (retract_all_test_facts, setup_full, validate_facts)).

test(validation_detects_tier_gap,
     (retract_all_test_facts, setup_full,
      retractall(price_tier(supplier1, part1, _, _, _)),
      assert(price_tier(supplier1, part1, 0, 39, 100)),
      assert(price_tier(supplier1, part1, 50, sup, 40)),
      validate_facts)).

%% --- CSV loader ---

test(csv_loads_correctly,
     (retract_all_test_facts, load_csv('sample.csv'),
      demand(part1, 250),
      demand(part2, 220),
      cost(supplier1, part1, 100))).

test(csv_then_solve,
     (retract_all_test_facts, load_csv('sample.csv'),
      solve(_, TCO), TCO > 0)).

%% ================================================================== %%
%%  HELPERS                                                            %%
%% ================================================================== %%

sum_qs(Qs, Sum) :-
    findall(Q, member(q(_, Q), Qs), Qs2),
    sum_list(Qs2, Sum).

count_active(Qs, N) :-
    findall(Q, (member(q(_, Q), Qs), Q > 0), Active),
    length(Active, N).

total_supplier_volume(Supplier, Allocation, Total) :-
    findall(Q,
            ( member(alloc(_, Qs), Allocation),
              member(q(Supplier, Q), Qs)
            ),
            Volumes),
    sum_list(Volumes, Total).
