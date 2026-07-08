%%% P2CLPFD — Sensitivity Analysis & Shadow Prices
%%%
%%% Answers the question that follows every optimal award:
%%% "WHERE should I negotiate?"
%%%
%%% A constraint is BINDING when the optimal allocation sits exactly at
%%% its limit — it is actively shaping (and possibly costing) money.
%%% The SHADOW PRICE of a binding constraint is the TCO saving obtained
%%% by relaxing it one step (units for capacities/MOQ, one percentage
%%% point for shares, one supplier for count rules).
%%%
%%% Usage:
%%%   ?- sensitivity(Report).            % step = 1
%%%   ?- sensitivity(10, Report).        % relax quantities by 10 units
%%%   ?- print_sensitivity(Report).
%%%
%%% Report = sensitivity(TCO, Bindings, Shadows)
%%%   Bindings = [binding(Constraint, Used, Limit), ...]
%%%   Shadows  = [shadow(Constraint, RelaxedLimit, NewTCO, Savings), ...]
%%%
%%% Re-solves are bounded by the baseline TCO: a relaxation can never
%%% be worse than the baseline, so it is a valid (and strong) pruning
%%% ceiling for the branch-and-bound search.

%% ------------------------------------------------------------------ %%
%%  PUBLIC API                                                         %%
%% ------------------------------------------------------------------ %%

%! sensitivity(-Report) is semidet.
sensitivity(Report) :-
    sensitivity(1, Report).

%! sensitivity(+Step, -Report) is semidet.
%
%  Step is the relaxation size for quantity constraints (capacity,
%  global capacity, MOQ). Percentage and supplier-count constraints
%  always relax by 1. Fails if the base model is infeasible.
%
sensitivity(Step, sensitivity(TCO, Bindings, Shadows)) :-
    solve(Allocation, TCO),
    !,
    binding_constraints(Allocation, Bindings),
    shadow_prices(Bindings, TCO, Step, Shadows).

%! binding_constraints(+Allocation, -Bindings) is det.
binding_constraints(Allocation, Bindings) :-
    findall(B, binding_constraint(Allocation, B), Bindings).

%% ------------------------------------------------------------------ %%
%%  BINDING CONSTRAINT DETECTION (slack = 0 at the optimum)            %%
%% ------------------------------------------------------------------ %%

%! binding_constraint(+Allocation, -Binding) is nondet.

% Per-pair capacity: allocation sits exactly at the limit.
binding_constraint(Allocation, binding(capacity(S, P), Q, Cap)) :-
    capacity(S, P, Cap),
    alloc_q(Allocation, P, S, Q),
    Q > 0,
    Q =:= Cap.

% Global supplier capacity.
binding_constraint(Allocation, binding(global_capacity(S), Total, Cap)) :-
    global_capacity(S, Cap),
    supplier_total_q(S, Allocation, Total),
    Total > 0,
    Total =:= Cap.

% Global share cap: one more unit would breach the percentage.
binding_constraint(Allocation, binding(max_global_share(S), Total, Pct)) :-
    max_global_share(S, Pct),
    total_demand_from_alloc(Allocation, TD),
    TD > 0,
    supplier_total_q(S, Allocation, Total),
    100 * (Total + 1) > Pct * TD.

% Per-part share maximum.
binding_constraint(Allocation, binding(share_max(P, S), Q, MaxPct)) :-
    share(P, S, _, MaxPct),
    MaxPct < 100,
    demand(P, D),
    D > 0,
    alloc_q(Allocation, P, S, Q),
    100 * (Q + 1) > MaxPct * D.

% Per-part share minimum: allocation is pinned at the floor.
binding_constraint(Allocation, binding(share_min(P, S), Q, MinPct)) :-
    share(P, S, MinPct, _),
    MinPct > 0,
    demand(P, D),
    D > 0,
    alloc_q(Allocation, P, S, Q),
    100 * (Q - 1) < MinPct * D.

% MOQ: order sits exactly at the minimum (the floor is forcing volume).
binding_constraint(Allocation, binding(moq(S, P), Q, Moq)) :-
    moq(S, P, Moq),
    Moq > 0,
    alloc_q(Allocation, P, S, Q),
    Q =:= Moq.

% Supplier-count floor (min_suppliers / dual_source).
binding_constraint(Allocation, binding(min_suppliers(P), N, MinN)) :-
    member(alloc(P, Qs), Allocation),
    min_suppliers_of(P, MinN),
    MinN > 0,
    count_active_qs(Qs, N),
    N =:= MinN.

% Supplier-count ceiling.
binding_constraint(Allocation, binding(max_suppliers(P), N, MaxN)) :-
    max_suppliers(P, MaxN),
    member(alloc(P, Qs), Allocation),
    count_active_qs(Qs, N),
    N =:= MaxN.

%% ------------------------------------------------------------------ %%
%%  SHADOW PRICES (re-solve with one constraint relaxed)               %%
%% ------------------------------------------------------------------ %%

shadow_prices([], _, _, []).
shadow_prices([binding(C, _, Limit)|Rest], BaseTCO, Step, Out) :-
    (   relaxation(C, Limit, Step, Overrides, RelaxedLimit)
    ->  (   solve_scenario(Overrides, _, NewTCO, BaseTCO)
        ->  Savings is BaseTCO - NewTCO
        ;   NewTCO = BaseTCO, Savings = 0
        ),
        Out = [shadow(C, RelaxedLimit, NewTCO, Savings)|OutRest]
    ;   Out = OutRest
    ),
    shadow_prices(Rest, BaseTCO, Step, OutRest).

%! relaxation(+Constraint, +Limit, +Step, -Overrides, -RelaxedLimit) is semidet.
%
%  How to loosen each constraint type by one step. Fails when the
%  constraint cannot be relaxed further (e.g. share floor already 0).

relaxation(capacity(S, P), Cap, Step, [set(capacity(S, P, NewCap))], NewCap) :-
    NewCap is Cap + Step.
relaxation(global_capacity(S), Cap, Step, [set(global_capacity(S, NewCap))], NewCap) :-
    NewCap is Cap + Step.
relaxation(max_global_share(S), Pct, _, [set(max_global_share(S, NewPct))], NewPct) :-
    Pct < 100,
    NewPct is Pct + 1.
relaxation(share_max(P, S), MaxPct, _, [set(share(P, S, MinPct, NewMax))], NewMax) :-
    MaxPct < 100,
    share(P, S, MinPct, MaxPct),
    NewMax is MaxPct + 1.
relaxation(share_min(P, S), MinPct, _, [set(share(P, S, NewMin, MaxPct))], NewMin) :-
    MinPct > 0,
    share(P, S, MinPct, MaxPct),
    NewMin is MinPct - 1.
relaxation(moq(S, P), Moq, Step, [set(moq(S, P, NewMoq))], NewMoq) :-
    Moq > 0,
    NewMoq is max(0, Moq - Step).
relaxation(min_suppliers(P), MinN, _,
           [remove(dual_source(P)), set(min_suppliers(P, NewN))], NewN) :-
    MinN > 1,
    NewN is MinN - 1.
relaxation(max_suppliers(P), MaxN, _, [set(max_suppliers(P, NewN))], NewN) :-
    NewN is MaxN + 1.

%% ------------------------------------------------------------------ %%
%%  ALLOCATION HELPERS                                                 %%
%% ------------------------------------------------------------------ %%

alloc_q(Allocation, Part, Supplier, Q) :-
    member(alloc(Part, Qs), Allocation),
    member(q(Supplier, Q), Qs),
    !.

count_active_qs(Qs, N) :-
    findall(1, (member(q(_, Q), Qs), Q > 0), Ones),
    length(Ones, N).

%% ------------------------------------------------------------------ %%
%%  JSON  (for janus-swi / HTTP)                                       %%
%% ------------------------------------------------------------------ %%

%! sensitivity_to_json(+Step, -JSON) is det.
%
%  JSON = _{status, tco, binding_constraints:[...], negotiation_levers:[...]}
%  Levers are sorted by savings, largest first — the negotiation agenda.
%
sensitivity_to_json(Step, JSON) :-
    (   sensitivity(Step, sensitivity(TCO, Bindings, Shadows))
    ->  findall(BJ, ( member(binding(C, Used, Limit), Bindings),
                      constraint_json(C, CJ),
                      BJ = CJ.put(_{used:Used, limit:Limit}) ),
                BindingsJSON),
        findall(Savings-SJ,
                ( member(shadow(C, RelaxedLimit, NewTCO, Savings), Shadows),
                  constraint_json(C, CJ),
                  SJ = CJ.put(_{relaxed_limit:RelaxedLimit,
                                new_tco:NewTCO,
                                savings:Savings}) ),
                Pairs),
        sort(1, @>=, Pairs, Sorted),
        pairs_values(Sorted, ShadowsJSON),
        JSON = _{status:ok, tco:TCO, step:Step,
                 binding_constraints:BindingsJSON,
                 negotiation_levers:ShadowsJSON}
    ;   JSON = _{status:infeasible, tco:null,
                 binding_constraints:[], negotiation_levers:[]}
    ).

constraint_json(capacity(S, P),        _{constraint:capacity,         supplier:S,    part:P}).
constraint_json(global_capacity(S),    _{constraint:global_capacity,  supplier:S,    part:null}).
constraint_json(max_global_share(S),   _{constraint:max_global_share, supplier:S,    part:null}).
constraint_json(share_max(P, S),       _{constraint:share_max,        supplier:S,    part:P}).
constraint_json(share_min(P, S),       _{constraint:share_min,        supplier:S,    part:P}).
constraint_json(moq(S, P),             _{constraint:moq,              supplier:S,    part:P}).
constraint_json(min_suppliers(P),      _{constraint:min_suppliers,    supplier:null, part:P}).
constraint_json(max_suppliers(P),      _{constraint:max_suppliers,    supplier:null, part:P}).

%% ------------------------------------------------------------------ %%
%%  PRETTY PRINTING                                                    %%
%% ------------------------------------------------------------------ %%

print_sensitivity(sensitivity(TCO, Bindings, Shadows)) :-
    format('~n=== Sensitivity Analysis (baseline TCO: ~w) ===~n', [TCO]),
    (   Bindings = []
    ->  format('~nNo binding constraints — the optimum is interior;~n'),
        format('negotiating limits will not reduce cost.~n')
    ;   format('~nBinding constraints (allocation sits at the limit):~n'),
        forall(member(binding(C, Used, Limit), Bindings),
               format('  ~w  used=~w limit=~w~n', [C, Used, Limit])),
        format('~nNegotiation levers (savings from one relaxation step):~n'),
        msort_shadows(Shadows, Sorted),
        forall(member(shadow(C, RelaxedLimit, NewTCO, Savings), Sorted),
               (   Savings > 0
               ->  format('  ~w -> ~w  saves ~w (new TCO ~w)~n',
                          [C, RelaxedLimit, Savings, NewTCO])
               ;   format('  ~w -> ~w  no saving at this step size~n',
                          [C, RelaxedLimit])
               ))
    ),
    format('~n').

msort_shadows(Shadows, Sorted) :-
    map_list_to_pairs(shadow_savings, Shadows, Pairs),
    sort(1, @>=, Pairs, SortedPairs),
    pairs_values(SortedPairs, Sorted).

shadow_savings(shadow(_, _, _, Savings), Savings).

%% ------------------------------------------------------------------ %%
%%  EXAMPLE QUERIES                                                    %%
%% ------------------------------------------------------------------ %%

%% ?- sensitivity(R), print_sensitivity(R).
%% ?- sensitivity(10, R), print_sensitivity(R).
%% ?- sensitivity_to_json(1, JSON).
