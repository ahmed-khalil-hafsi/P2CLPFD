%%% P2CLPFD — Strait of Hormuz case study runner
%%%
%%% Reproduces every number quoted in casestudy/README.md.
%%%
%%%   swipl -q -g "run_all" -g halt main.pl casestudy/run_hormuz.pl
%%%
%%% Units throughout:
%%%   quantity  1 unit  = 30 kb/d (a ~Suezmax parcel cadence)
%%%   cost      1 point = 1 US cent per barrel, landed
%%%   so TCO x $300 = cost per DAY, TCO x $109,500 = cost per YEAR

data('casestudy/hormuz.csv').

%% ------------------------------------------------------------------ %%
%%  REPORTING HELPERS                                                  %%
%% ------------------------------------------------------------------ %%

%! usd_per_day(+TCO, -Usd) is det.
usd_per_day(TCO, Usd) :- Usd is TCO * 300.

%! usd_per_year(+TCO, -Usd) is det.
usd_per_year(TCO, Usd) :- Usd is TCO * 109500.

%! route_volume(+Alloc, +Route, -Units) is det.
route_volume(Alloc, Route, Units) :-
    findall(Q,
            ( member(alloc(_, Qs), Alloc),
              member(q(S, Q), Qs),
              supplier_route(S, Route)
            ),
            Vs),
    sum_list(Vs, Units).

%! total_units(+Alloc, -Units) is det.
total_units(Alloc, Units) :-
    findall(Q, ( member(alloc(_, Qs), Alloc), member(q(_, Q), Qs) ), Vs),
    sum_list(Vs, Units).

report(Label, Alloc, TCO) :-
    usd_per_day(TCO, Day),
    usd_per_year(TCO, Year),
    total_units(Alloc, Total),
    route_volume(Alloc, hormuz, H),
    route_volume(Alloc, bypass, B),
    route_volume(Alloc, atlantic, A),
    HPct is (H * 100) // max(1, Total),
    format('~n--- ~w ---~n', [Label]),
    format('  TCO ~w  ($~D/day, $~D/yr)~n', [TCO, Day, Year]),
    format('  hormuz ~w u (~w%%)   bypass ~w u   atlantic ~w u~n',
           [H, HPct, B, A]),
    forall(member(alloc(Part, Qs), Alloc),
           ( format('  ~w:~n', [Part]),
             forall(( member(q(S, Q), Qs), Q > 0 ),
                    format('      ~w~t~28| ~w u~n', [S, Q])) )).

%% ------------------------------------------------------------------ %%
%%  SCENARIOS                                                          %%
%% ------------------------------------------------------------------ %%

%! baseline(-Alloc, -TCO) is semidet.
%  2025 conditions: Hormuz open, peacetime freight and war-risk.
baseline(Alloc, TCO) :-
    data(F), load_csv(F),
    solve(Alloc, TCO).

%! closure(-Alloc, -TCO) is semidet.
%  Post-2 March 2026: the strait is shut and the Red Sea leg carries a
%  higher war-risk load, so the bypass is dearer than in peacetime.
closure(Alloc, TCO) :-
    data(F), load_csv(F),
    solve_scenario([ set(route_capacity(hormuz, 0)),
                     set(logistics_cost(red_sea, 690))
                   ], Alloc, TCO).

%! crisis_freight_only(-Alloc, -TCO) is semidet.
%  Strait technically open but at crisis freight + war-risk rates.
%  Isolates the PRICE of risk from the PHYSICAL loss of the route.
crisis_freight_only(Alloc, TCO) :-
    data(F), load_csv(F),
    solve_scenario([ set(logistics_cost(gulf_hormuz, 1240)),
                     set(logistics_cost(red_sea, 690))
                   ], Alloc, TCO).

%! capped(+MaxUnits, -Alloc, -TCO) is semidet.
%  A standing resilience policy: never take more than MaxUnits through
%  Hormuz, in peacetime, as a matter of board policy.
capped(MaxUnits, Alloc, TCO) :-
    data(F), load_csv(F),
    solve_scenario([set(route_capacity(hormuz, MaxUnits))], Alloc, TCO).

%% ------------------------------------------------------------------ %%
%%  THE POLICY CURVE                                                   %%
%% ------------------------------------------------------------------ %%

%! policy_curve is det.
%  TCO as a function of the Hormuz ceiling. The shape of this curve is
%  the whole finding: flat while bypass and Atlantic slack absorb the
%  displaced barrels, then steep once they cannot.
policy_curve :-
    baseline(_, Base),
    format('~n=== Cost of a standing Hormuz ceiling ===~n'),
    format('~ncap(u)   TCO      $/day        premium/yr   $/bbl~n'),
    forall(member(N, [20, 14, 12, 10, 8, 6, 4, 2, 0]),
           curve_row(N, Base)).

curve_row(N, Base) :-
    (   capped(N, _, TCO)
    ->  usd_per_day(TCO, Day),
        Delta is TCO - Base,
        usd_per_year(Delta, PremYr),
        %% 20 units x 30 kb/d = 600 kb/d; premium in cents/bbl = Delta/20
        Bbl is Delta / 20.0,
        format('~w~t~8|~w~t~17|$~D~t~30|$~D~t~43|~2f c~n',
               [N, TCO, Day, PremYr, Bbl])
    ;   format('~w~t~8|INFEASIBLE~n', [N])
    ).

%% ------------------------------------------------------------------ %%
%%  ENTRY POINT                                                        %%
%% ------------------------------------------------------------------ %%

run_all :-
    (   baseline(A1, T1) -> report('BASELINE (2025, strait open)', A1, T1)
    ;   format('baseline INFEASIBLE~n') ),
    (   crisis_freight_only(A2, T2)
    ->  report('CRISIS FREIGHT (open, war-risk priced in)', A2, T2)
    ;   format('crisis_freight INFEASIBLE~n') ),
    (   closure(A3, T3) -> report('CLOSURE (post 2 Mar 2026)', A3, T3)
    ;   format('closure INFEASIBLE~n') ),
    policy_curve.

%! levers is det.
%  Where negotiation and investment actually pay, under closure.
levers :-
    data(F), load_csv(F),
    apply_overrides([ set(route_capacity(hormuz, 0)),
                      set(logistics_cost(red_sea, 690)) ], _Undo),
    print_sensitivity(1).
