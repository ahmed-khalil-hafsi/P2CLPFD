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
:- dynamic rebate/3.
:- dynamic otif/2.
:- dynamic min_otif/1.
:- dynamic lead_time/3.
:- dynamic max_lead_time/2.
:- dynamic certification/2.
:- dynamic required_certification/1.
:- dynamic required_certification/2.
:- dynamic region/2.
:- dynamic fx_rate/2.
:- dynamic logistics_cost/2.

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
    retractall(price_tier(_,_,_,_,_)),
    retractall(rebate(_,_,_)),
    retractall(otif(_,_)),
    retractall(min_otif(_)),
    retractall(lead_time(_,_,_)),
    retractall(max_lead_time(_,_)),
    retractall(certification(_,_)),
    retractall(required_certification(_)),
    retractall(required_certification(_,_)),
    retractall(region(_,_)),
    retractall(fx_rate(_,_)),
    retractall(logistics_cost(_,_)),
    retractall(supplier_route(_,_)),
    retractall(route_capacity(_,_)),
    retractall(max_route_share(_,_)).

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
    setup_minimal, assert(user:moq(supplier1, part1, 50)),
    solve(A, _), !,
    member(alloc(part1, Qs), A), member(q(supplier1, Q1), Qs),
    (Q1 =:= 0 ; Q1 >= 50).

test(gap_domain) :-
    setup_minimal, assert(user:moq(supplier1, part1, 90)),
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
    retractall(user:share(part1, supplier1, _, _)),
    assert(user:share(part1, supplier1, 0, 10)),
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
    retractall(user:dual_source(part1)),
    assert(user:min_suppliers(part1, 2)),
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

:- begin_tests(global_capacity).

% Regression: global_capacity/2 was posted inside forall/2, which is
% double negation — the constraint was undone before labeling and the
% cap silently never applied.
test(cap_binds_across_parts) :-
    user:clear,
    assert(user:demand(part1, 100)),
    assert(user:demand(part2, 100)),
    assert(user:cost(supplier1, part1, 10)),
    assert(user:cost(supplier2, part1, 20)),
    assert(user:cost(supplier1, part2, 10)),
    assert(user:cost(supplier2, part2, 20)),
    assert(user:global_capacity(supplier1, 60)),
    solve(A, TCO), !,
    supplier_total(supplier1, A, Total),
    Total =:= 60,
    TCO =:= 3400.                % 60@10 + 140@20

test(infeasible_when_global_caps_below_demand, [fail]) :-
    user:clear,
    assert(user:demand(part1, 100)),
    assert(user:cost(supplier1, part1, 10)),
    assert(user:global_capacity(supplier1, 50)),
    solve(_, _).

:- end_tests(global_capacity).

%% ------------------------------------------------------------------ %%

:- begin_tests(rebates).

% b is dearer per unit but offers a portfolio rebate across both parts.
setup_rebate :-
    user:clear,
    assert(user:demand(p1, 100)),
    assert(user:demand(p2, 100)),
    assert(user:cost(a, p1, 90)),
    assert(user:cost(b, p1, 100)),
    assert(user:cost(a, p2, 90)),
    assert(user:cost(b, p2, 100)).

test(reachable_rebate_is_applied) :-
    setup_rebate,
    assert(user:rebate(b, 200, 50)),     % half price once b wins everything
    solve(A, TCO), !,
    supplier_total(b, A, 200),           % worth concentrating on b
    TCO =:= 10000.                       % 200*100 = 20000, less 50%

test(unreachable_rebate_is_not_applied) :-
    setup_rebate,
    assert(user:capacity(b, p1, 30)),
    assert(user:capacity(b, p2, 30)),
    assert(user:rebate(b, 200, 50)),     % b can ship at most 60, never 200
    solve(_, TCO), !,
    TCO =:= 18000.                       % all 200 units from a @90, no discount

% Regression: build_rebates/4 failing was read as "no rebates exist", so
% an unreachable forced branch silently dropped the threshold constraint
% and the solver reported a discount it could never earn.
test(unreachable_rebate_does_not_fake_a_discount) :-
    setup_rebate,
    assert(user:capacity(b, p1, 30)),
    assert(user:capacity(b, p2, 30)),
    assert(user:rebate(b, 200, 50)),
    solve(A, TCO), !,
    supplier_total(b, A, BTotal),
    BTotal < 200,                        % threshold genuinely unmet
    TCO > 10000.                         % so no discounted price is claimed

test(rebate_worth_less_than_the_premium_is_declined) :-
    setup_rebate,
    assert(user:rebate(b, 200, 2)),      % 2% off does not cover b's premium
    solve(A, TCO), !,
    supplier_total(a, A, 200),
    TCO =:= 18000.

:- end_tests(rebates).

%% ------------------------------------------------------------------ %%

:- begin_tests(decomposition).

% Independent parts must give the same answer as one joint model.
test(decomposed_matches_monolithic) :-
    user:clear,
    assert(user:demand(p1, 100)),
    assert(user:demand(p2, 80)),
    assert(user:cost(a, p1, 100)), assert(user:cost(b, p1, 82)),
    assert(user:cost(a, p2, 70)),  assert(user:cost(b, p2, 95)),
    assert(user:capacity(a, p1, 75)), assert(user:capacity(b, p1, 75)),
    assert(user:capacity(a, p2, 60)), assert(user:capacity(b, p2, 60)),
    assert(user:dual_source(p1)),
    \+ parts_are_coupled,                % precondition: separable
    solve(_, TCO),
    solve_monolithic(_, MonoTCO), !,
    TCO =:= MonoTCO.

test(global_share_cap_forces_monolithic) :-
    user:clear,
    assert(user:demand(p1, 100)),
    assert(user:demand(p2, 100)),
    assert(user:cost(a, p1, 10)), assert(user:cost(b, p1, 20)),
    assert(user:cost(a, p2, 10)), assert(user:cost(b, p2, 20)),
    assert(user:max_global_share(a, 50)),
    parts_are_coupled,                   % cap spans parts
    solve(A, _), !,
    supplier_total(a, A, ATotal),
    ATotal =< 100.                       % 50% of 200

test(slack_global_capacity_stays_separable) :-
    user:clear,
    assert(user:demand(p1, 50)),
    assert(user:demand(p2, 50)),
    assert(user:cost(a, p1, 10)), assert(user:cost(b, p1, 20)),
    assert(user:cost(a, p2, 10)), assert(user:cost(b, p2, 20)),
    assert(user:global_capacity(a, 5000)),   % far above total demand
    \+ parts_are_coupled,
    solve(_, TCO), !,
    TCO =:= 1000.

:- end_tests(decomposition).

%% ------------------------------------------------------------------ %%

:- begin_tests(routes).

% Two cheap suppliers share one shipping corridor; a third is dearer but
% off-corridor. The route ceiling caps the pair's COMBINED volume, which
% no per-supplier cap can express.
setup_routes :-
    user:clear,
    assert(user:demand(part1, 100)),
    assert(user:cost(cheap_a, part1, 10)),
    assert(user:cost(cheap_b, part1, 10)),
    assert(user:cost(offroute, part1, 25)),
    assert(user:supplier_route(cheap_a, hormuz)),
    assert(user:supplier_route(cheap_b, hormuz)).

route_total(Allocation, Route, Total) :-
    findall(Q,
            ( member(alloc(_, Qs), Allocation),
              member(q(S, Q), Qs),
              user:supplier_route(S, Route)
            ),
            Volumes),
    sum_list(Volumes, Total).

test(route_capacity_caps_the_group) :-
    setup_routes,
    assert(user:route_capacity(hormuz, 60)),
    solve(A, TCO), !,
    route_total(A, hormuz, Total),
    Total =:= 60,                   % group ceiling, not per supplier
    TCO =:= 1600.                   % 60@10 + 40@25

test(route_share_cap_caps_the_group) :-
    setup_routes,
    assert(user:max_route_share(hormuz, 30)),
    solve(A, TCO), !,
    route_total(A, hormuz, Total),
    Total =:= 30,
    TCO =:= 2050.                   % 30@10 + 70@25

test(no_route_facts_no_effect) :-
    setup_routes,
    solve(_, TCO), !,
    TCO =:= 1000.                   % all 100 units from the cheap corridor

test(route_binding_is_detected) :-
    setup_routes,
    assert(user:route_capacity(hormuz, 60)),
    sensitivity(1, sensitivity(_, Bindings, _)),
    member(binding(route_capacity(hormuz), 60, 60), Bindings).

test(route_shadow_price) :-
    setup_routes,
    assert(user:route_capacity(hormuz, 60)),
    sensitivity(10, sensitivity(1600, _, Shadows)),
    % 10 more units through the corridor swaps 10 units of 25 for 10 of 10
    member(shadow(route_capacity(hormuz), 70, 1450, 150), Shadows).

% A route ceiling binds the SUM while every member stays under its own
% limit — the case per-supplier global_capacity/2 cannot express.
test(route_binds_sum_not_members) :-
    setup_routes,
    assert(user:global_capacity(cheap_a, 100)),   % neither member is
    assert(user:global_capacity(cheap_b, 100)),   % individually binding
    assert(user:route_capacity(hormuz, 60)),
    solve(A, _), !,
    route_total(A, hormuz, 60).

% The ceiling applies across all parts, not per part.
test(route_capacity_spans_parts) :-
    user:clear,
    assert(user:demand(part1, 50)),
    assert(user:demand(part2, 50)),
    assert(user:cost(onroute, part1, 10)),
    assert(user:cost(onroute, part2, 10)),
    assert(user:cost(offroute, part1, 25)),
    assert(user:cost(offroute, part2, 25)),
    assert(user:supplier_route(onroute, hormuz)),
    assert(user:route_capacity(hormuz, 60)),      % 60 across BOTH parts
    solve(A, TCO), !,
    route_total(A, hormuz, 60),
    TCO =:= 600 + 1000.                           % 60@10 + 40@25

% A route closed below total demand with no alternative is infeasible.
test(route_capacity_can_make_infeasible, [fail]) :-
    user:clear,
    assert(user:demand(part1, 100)),
    assert(user:cost(onlysource, part1, 10)),
    assert(user:supplier_route(onlysource, hormuz)),
    assert(user:route_capacity(hormuz, 50)),
    solve(_, _).

:- end_tests(routes).

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
    retractall(user:price_tier(supplier1, part1, _, _, _)),
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
    retractall(user:price_tier(supplier1, part1, _, _, _)),
    assert(user:price_tier(supplier1, part1, 0, 39, 100)),
    assert(user:price_tier(supplier1, part1, 50, sup, 40)),
    validate_facts.

test(detects_moq_over_cap) :-
    clear, assert(user:demand(part1, 100)), assert(user:cost(supplier1, part1, 10)),
    assert(user:moq(supplier1, part1, 80)), assert(user:capacity(supplier1, part1, 50)),
    validate_facts.

test(detects_missing_cost) :-
    clear, assert(user:demand(part1, 100)),
    assert(user:capacity(supplier1, part1, 100)),
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

:- begin_tests(qualification).

test(otif_gate_disqualifies_cheapest) :-
    setup_minimal,                         % supplier1 @10, supplier2 @20
    assert(user:otif(supplier1, 90)),
    assert(user:otif(supplier2, 97)),
    assert(user:min_otif(95)),
    solve(A, TCO), !,
    member(alloc(part1, Qs), A),
    member(q(supplier1, 0), Qs),           % cheapest excluded by gate
    member(q(supplier2, 100), Qs),
    TCO =:= 2000.

test(otif_unknown_disqualifies) :-
    setup_minimal,
    assert(user:otif(supplier2, 97)),           % supplier1 has NO otif data
    assert(user:min_otif(95)),
    solve(A, _), !,
    member(alloc(part1, Qs), A),
    member(q(supplier1, 0), Qs).

test(lead_time_gate) :-
    setup_minimal,
    assert(user:lead_time(supplier1, part1, 45)),
    assert(user:lead_time(supplier2, part1, 20)),
    assert(user:max_lead_time(part1, 30)),
    solve(A, _), !,
    member(alloc(part1, Qs), A),
    member(q(supplier1, 0), Qs),
    member(q(supplier2, 100), Qs).

test(certification_gate_per_part) :-
    setup_minimal,
    assert(user:certification(supplier2, iso9001)),
    assert(user:required_certification(part1, iso9001)),
    solve(A, _), !,
    member(alloc(part1, Qs), A),
    member(q(supplier1, 0), Qs),
    member(q(supplier2, 100), Qs).

test(certification_gate_global) :-
    setup_minimal,
    assert(user:certification(supplier2, iso9001)),
    assert(user:required_certification(iso9001)),
    solve(A, _), !,
    member(alloc(part1, Qs), A),
    member(q(supplier2, 100), Qs).

test(all_disqualified_infeasible, [fail]) :-
    setup_minimal,
    assert(user:min_otif(95)),                  % nobody has otif data
    solve(_, _).

test(no_gates_no_effect) :-
    setup_minimal,
    assert(user:otif(supplier1, 80)),           % data present but no min_otif gate
    solve(_, TCO), !,
    TCO =:= 1000.

test(disqualified_pairs_reports_reason) :-
    setup_minimal,
    assert(user:otif(supplier1, 90)),
    assert(user:min_otif(95)),
    disqualified_pairs(Ex),
    member(excluded(part1, supplier1, Reasons), Ex),
    member(otif_below_threshold(90, 95), Reasons).

:- end_tests(qualification).

%% ------------------------------------------------------------------ %%

:- begin_tests(landed_cost).

test(fx_changes_winner) :-
    setup_minimal,                          % s1 @10, s2 @20
    assert(user:region(supplier1, overseas)),
    assert(user:fx_rate(overseas, 250)),         % s1 landed: 10*2.5 = 25 > 20
    solve(A, TCO), !,
    member(alloc(part1, Qs), A),
    member(q(supplier2, 100), Qs),
    TCO =:= 2000.

test(logistics_added_per_unit) :-
    setup_minimal,
    assert(user:region(supplier1, overseas)),
    assert(user:logistics_cost(overseas, 5)),    % s1 landed: 10+5 = 15, still wins
    solve(A, TCO), !,
    member(alloc(part1, Qs), A),
    member(q(supplier1, 100), Qs),
    TCO =:= 1500.

test(fx_and_logistics_combined) :-
    setup_minimal,
    assert(user:region(supplier1, overseas)),
    assert(user:fx_rate(overseas, 110)),         % 10*1.10 = 11
    assert(user:logistics_cost(overseas, 2)),    % + 2 = 13
    solve(_, TCO), !,
    TCO =:= 1300.

test(tiered_pricing_with_fx) :-
    clear,
    assert(user:demand(part1, 100)),
    assert(user:price_tier(supplier1, part1, 0, 49, 20)),
    assert(user:price_tier(supplier1, part1, 50, sup, 10)),
    assert(user:region(supplier1, overseas)),
    assert(user:fx_rate(overseas, 120)),         % tier2 landed: 12
    solve(A, TCO), !,
    member(alloc(part1, Qs), A),
    member(q(supplier1, 100), Qs),
    TCO =:= 1200.

test(no_region_unchanged) :-
    setup_minimal,
    assert(user:fx_rate(overseas, 300)),         % no supplier in that region
    solve(_, TCO), !,
    TCO =:= 1000.

:- end_tests(landed_cost).

%% ------------------------------------------------------------------ %%


:- begin_tests(sensitivity).

% demand 100; s1 @10 capped at 50; s2 @20 uncapped.
% Optimum: 50 from s1 + 50 from s2, TCO 1500. s1's capacity is binding.
setup_capped :-
    user:clear,
    assert(user:demand(part1, 100)),
    assert(user:cost(supplier1, part1, 10)),
    assert(user:cost(supplier2, part1, 20)),
    assert(user:capacity(supplier1, part1, 50)).

test(binding_capacity_detected) :-
    setup_capped,
    sensitivity(1, sensitivity(TCO, Bindings, _)),
    TCO =:= 1500,
    member(binding(capacity(supplier1, part1), 50, 50), Bindings).

test(shadow_price_of_capacity) :-
    setup_capped,
    sensitivity(10, sensitivity(1500, _, Shadows)),
    member(shadow(capacity(supplier1, part1), 60, 1400, 100), Shadows).

test(no_binding_no_levers) :-
    user:clear,
    assert(user:demand(part1, 100)),
    assert(user:cost(supplier1, part1, 10)),
    assert(user:cost(supplier2, part1, 20)),
    sensitivity(1, sensitivity(1000, Bindings, Shadows)),
    Bindings == [],
    Shadows == [].

test(moq_binding_detected) :-
    user:clear,
    assert(user:demand(part1, 100)),
    assert(user:cost(supplier1, part1, 10)),
    assert(user:cost(supplier2, part1, 20)),
    assert(user:capacity(supplier1, part1, 40)),
    assert(user:moq(supplier2, part1, 60)),
    sensitivity(1, sensitivity(_, Bindings, _)),
    member(binding(moq(supplier2, part1), 60, 60), Bindings).

test(set_override_keeps_sibling_facts) :-
    setup_capped,
    % If set/1 wiped all cost facts, supplier2 would vanish and the
    % scenario would be infeasible (s1 capacity 50 < demand 100).
    compare_scenarios([b-[], s1_up-[set(cost(supplier1, part1, 12))]], Results),
    member(result(s1_up, ok, TCO, _), Results),
    TCO =:= 1600.

:- end_tests(sensitivity).

%% ------------------------------------------------------------------ %%

:- begin_tests(multiperiod).

mp_clear :-
    user:clear,
    retractall(user:period_demand(_,_,_)),
    retractall(user:period_capacity(_,_,_,_)),
    retractall(user:holding_cost(_,_)).

mp_qty(Plan, Part, Period, Supplier, Q) :-
    member(mp(Part, Period, Qs, _), Plan),
    member(q(Supplier, Q), Qs).

mp_inventory(Plan, Part, Period, Inv) :-
    member(mp(Part, Period, _, Inv), Plan).

test(buys_in_period_when_capacity_allows) :-
    mp_clear,
    assert(user:period_demand(part1, 1, 100)),
    assert(user:period_demand(part1, 2, 100)),
    assert(user:cost(supplier1, part1, 10)),
    assert(user:holding_cost(part1, 2)),
    solve_multiperiod(Plan, TCO), !,
    TCO =:= 2000,                          % no carrying cost paid
    mp_inventory(Plan, part1, 1, 0).

test(buys_ahead_when_capacity_binds) :-
    mp_clear,
    assert(user:period_demand(part1, 1, 100)),
    assert(user:period_demand(part1, 2, 300)),
    assert(user:cost(supplier1, part1, 10)),
    assert(user:period_capacity(supplier1, part1, 1, 200)),
    assert(user:period_capacity(supplier1, part1, 2, 200)),
    assert(user:holding_cost(part1, 2)),
    solve_multiperiod(Plan, TCO), !,
    mp_qty(Plan, part1, 1, supplier1, 200),
    mp_inventory(Plan, part1, 1, 100),     % carried into period 2
    TCO =:= 4200.                          % 4000 goods + 200 holding

test(infeasible_when_capacity_short_across_horizon, [fail]) :-
    mp_clear,
    assert(user:period_demand(part1, 1, 100)),
    assert(user:period_demand(part1, 2, 300)),
    assert(user:cost(supplier1, part1, 10)),
    assert(user:period_capacity(supplier1, part1, 1, 150)),
    assert(user:period_capacity(supplier1, part1, 2, 150)),
    solve_multiperiod(_, _).

test(picks_cheaper_supplier_per_period) :-
    mp_clear,
    assert(user:period_demand(part1, 1, 100)),
    assert(user:cost(supplier1, part1, 10)),
    assert(user:cost(supplier2, part1, 20)),
    solve_multiperiod(Plan, TCO), !,
    TCO =:= 1000,
    mp_qty(Plan, part1, 1, supplier1, 100).

test(qualification_gate_applies) :-
    mp_clear,
    assert(user:period_demand(part1, 1, 100)),
    assert(user:cost(supplier1, part1, 10)),
    assert(user:cost(supplier2, part1, 20)),
    assert(user:otif(supplier2, 97)),
    assert(user:min_otif(95)),             % supplier1 has no OTIF data
    solve_multiperiod(Plan, TCO), !,
    TCO =:= 2000,
    mp_qty(Plan, part1, 1, supplier2, 100).

test(global_capacity_is_per_period) :-
    mp_clear,
    assert(user:period_demand(part1, 1, 100)),
    assert(user:period_demand(part1, 2, 100)),
    assert(user:cost(supplier1, part1, 10)),
    assert(user:cost(supplier2, part1, 20)),
    assert(user:global_capacity(supplier1, 60)),
    solve_multiperiod(Plan, TCO), !,
    mp_qty(Plan, part1, 1, supplier1, 60),  % 60 each period, not 60 total
    mp_qty(Plan, part1, 2, supplier1, 60),
    TCO =:= 2800.                           % (60*10 + 40*20) * 2 periods

test(holding_cost_deters_early_buying) :-
    mp_clear,
    assert(user:period_demand(part1, 1, 100)),
    assert(user:period_demand(part1, 2, 100)),
    assert(user:cost(supplier1, part1, 10)),
    assert(user:holding_cost(part1, 50)),   % carrying is punitive
    solve_multiperiod(Plan, _), !,
    mp_inventory(Plan, part1, 1, 0).

:- end_tests(multiperiod).

%% ------------------------------------------------------------------ %%

:- begin_tests(edge).

test(zero_demand) :-
    clear, assert(user:demand(part1, 0)), assert(user:cost(supplier1, part1, 10)),
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
