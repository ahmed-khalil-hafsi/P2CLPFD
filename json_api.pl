%%% P2CLPFD — JSON API + HTTP Server
%%%
%%% Exposes the solver as a JSON HTTP API so any agent (Claude, GPT, etc.)
%%% can call it over HTTP.
%%%
%%% Start the server:
%%%   swipl -g "['main.pl','tracer.pl','json_api.pl'], server(8080), thread_get_message(_)" &
%%%
%%% Then open http://localhost:8080/trace in a browser for the live
%%% solver visualization (WebSocket).
%%%
%%% Endpoints:
%%%
%%%   POST /solve
%%%     Input:  {"csv_path":"sample.csv", "max_cost":20000}
%%%     Output: {"tco":19534, "status":"ok",
%%%              "allocations":[{"part":"part1","suppliers":[
%%%                {"supplier":"supplier2","qty":75,"unit_cost":13,"subtotal":975},
%%%                ...]}]}
%%%
%%%   POST /scenarios
%%%     Input:  {"csv_path":"sample.csv",
%%%              "scenarios":[{"name":"baseline","overrides":[]},
%%%                           {"name":"up","overrides":[{"cost_delta":["supplier2","part1",10]}]}]}
%%%     Output: {"results":[{"name":"baseline","tco":19534,"status":"ok"},
%%%                         {"name":"up","tco":19609,"status":"ok"}],
%%%              "deltas":[{"name":"up","delta":75,"pct":0}]}
%%%
%%%   POST /validate
%%%     Input:  {"csv_path":"sample.csv"}
%%%     Output: {"status":"ok","warnings":[]}
%%%
%%%   GET /health
%%%     Output: {"status":"ok"}

:- use_module(library(http/http_server)).
:- use_module(library(http/http_dispatch)).
:- use_module(library(http/http_json)).
:- use_module(library(http/http_client)).
:- use_module(library(http/websocket)).
:- use_module(library(thread)).

%% ------------------------------------------------------------------ %%
%%  HTTP SERVER                                                        %%
%% ------------------------------------------------------------------ %%

:- http_handler('/solve/trace',  handle_trace_ws,     []).
:- http_handler('/solve',        handle_solve,        [method(post)]).
:- http_handler('/trace',        serve_trace_html,    [method(get)]).
:- http_handler('/scenarios',    handle_scenarios,    [method(post)]).
:- http_handler('/validate',     handle_validate,     [method(post)]).
:- http_handler('/health',       handle_health,       [method(get)]).

%! server(+Port) is det.
server(Port) :-
    format('P2CLPFD server on port ~w~n', [Port]),
    format('  API:    http://localhost:~w/solve~n', [Port]),
    format('  Trace:  http://localhost:~w/trace~n', [Port]),
    format('  Health: http://localhost:~w/health~n', [Port]),
    http_server(http_dispatch, [port(Port)]).

%% ------------------------------------------------------------------ %%
%%  /solve                                                             %%
%% ------------------------------------------------------------------ %%

handle_solve(Request) :-
    http_read_json_dict(Request, JSON),
    (   is_dict(JSON), get_dict(csv_path, JSON, Path)
    ->  with_output_to(string(_), load_csv(Path)),
        (   get_dict(max_cost, JSON, MaxCost)
        ->  (   solve(Allocation, TCO, MaxCost)
            ->  allocation_to_json(Allocation, TCO, ok, Response)
            ;   Response = _{status:infeasible, tco:null, allocations:[]}
            )
        ;   (   solve(Allocation, TCO)
            ->  allocation_to_json(Allocation, TCO, ok, Response)
            ;   Response = _{status:infeasible, tco:null, allocations:[]}
            )
        )
    ;   Response = _{status:error, message:"csv_path required"}
    ),
    reply_json_dict(Response).

%% ------------------------------------------------------------------ %%
%%  /scenarios                                                         %%
%% ------------------------------------------------------------------ %%

handle_scenarios(Request) :-
    http_read_json_dict(Request, JSON),
    (   is_dict(JSON),
        get_dict(csv_path, JSON, Path),
        get_dict(scenarios, JSON, Scenarios)
    ->  with_output_to(string(_), load_csv(Path)),
        json_to_scenarios(Scenarios, ScenarioList),
        compare_scenarios(ScenarioList, Results),
        scenarios_to_json(Results, Response)
    ;   Response = _{status:error, message:"csv_path and scenarios required"}
    ),
    reply_json_dict(Response).

%% ------------------------------------------------------------------ %%
%%  /validate                                                          %%
%% ------------------------------------------------------------------ %%

handle_validate(Request) :-
    http_read_json_dict(Request, JSON),
    (   is_dict(JSON), get_dict(csv_path, JSON, Path)
    ->  with_output_to(string(_), load_csv(Path)),
        validate_to_json(Response)
    ;   Response = _{status:error, message:"csv_path required"}
    ),
    reply_json_dict(Response).

%% ------------------------------------------------------------------ %%
%%  /solve/trace  (WebSocket — real-time solver visualization)        %%
%% ------------------------------------------------------------------ %%

handle_trace_ws(Request) :-
    (   member(search(Params), Request)
    ->  (   memberchk('csv_path'=Path, Params)
        ->  true
        ;   Path = 'sample.csv'
        ),
        (   memberchk('max_cost'=MaxCostStr, Params)
        ->  atom_number(MaxCostStr, MaxCost)
        ;   MaxCost = -1
        )
    ;   Path = 'sample.csv',
        MaxCost = -1
    ),
    http_upgrade_to_websocket(
        trace_ws_session(Path, MaxCost),
        [],
        Request).

trace_ws_session(Path, MaxCost, WebSocket) :-
    send_ws(WebSocket, _{event:"connected", csv_path:Path}),
    catch(
        (   with_output_to(string(_), load_csv(Path)),
            (   MaxCost >= 0
            ->  solve_with_trace_ws(WebSocket, MaxCost)
            ;   solve_with_trace_ws(WebSocket)
            )
        ),
        Error,
        (   send_ws(WebSocket, _{event:"error",
                                message:Error})
        )).

%! solve_with_trace_ws(+WebSocket) is nondet.
%  Mirrors tracer.pl's solve_with_trace but sends events via WebSocket.
%
solve_with_trace_ws(WebSocket) :-
    parts(Parts),
    suppliers(Suppliers),
    build_model(Parts, Suppliers, RawAlloc, Vars, TCO),

    send_ws_domains(WebSocket, RawAlloc, "initial"),
    send_ws(WebSocket, _{event:"phase", phase:"searching"}),

    (   minimize_cost(TCO, Vars)
    ->  materialize(RawAlloc, Allocation),
        send_ws_domains_ground(WebSocket, Allocation, TCO, "final"),
        send_ws(WebSocket, _{event:"phase", phase:"optimal"}),
        send_ws(WebSocket, _{event:"optimal", tco:TCO}),
        allocation_to_ws(Allocation, TCO, WebSocket)
    ;   send_ws(WebSocket, _{event:"infeasible"})
    ).

%! solve_with_trace_ws(+WebSocket, +MaxCost) is nondet.
%
solve_with_trace_ws(WebSocket, MaxCost) :-
    parts(Parts),
    suppliers(Suppliers),
    build_model(Parts, Suppliers, RawAlloc, Vars, TCO),
    TCO #=< MaxCost,

    send_ws_domains(WebSocket, RawAlloc, "initial"),
    send_ws(WebSocket, _{event:"phase", phase:"searching"}),

    (   minimize_cost(TCO, Vars)
    ->  materialize(RawAlloc, Allocation),
        send_ws_domains_ground(WebSocket, Allocation, TCO, "final"),
        send_ws(WebSocket, _{event:"phase", phase:"optimal"}),
        send_ws(WebSocket, _{event:"optimal", tco:TCO}),
        allocation_to_ws(Allocation, TCO, WebSocket)
    ;   send_ws(WebSocket, _{event:"infeasible"})
    ).

%! send_ws_domains(+WebSocket, +RawAlloc, +Phase) is det.
%
send_ws_domains(WebSocket, RawAlloc, Phase) :-
    findall(D,
            ( member(alloc(Part, Qs), RawAlloc),
              member(q(Supplier, Q, _), Qs),
              var(Q),
              atom_string(Supplier, SStr),
              atom_string(Part, PStr),
              string_concat("q.", SStr, T1),
              string_concat(T1, ".", T2),
              string_concat(T2, PStr, QName),
              domain_json(QName, Q, D)
            ),
            Vars),
    send_ws(WebSocket, _{event:"domain_snapshot", phase:Phase, vars:Vars}).

%! send_ws_domains_ground(+WebSocket, +Allocation, +TCO, +Phase) is det.
%
send_ws_domains_ground(WebSocket, Allocation, TCO, Phase) :-
    findall(D,
            ( member(alloc(Part, Qs), Allocation),
              member(q(Supplier, Q), Qs),
              Q > 0,
              atom_string(Supplier, SStr),
              atom_string(Part, PStr),
              string_concat("q.", SStr, T1),
              string_concat(T1, ".", T2),
              string_concat(T2, PStr, QName),
              domain_json(QName, Q, D)
            ),
            QVars),
    send_ws(WebSocket, _{event:"domain_snapshot", phase:Phase,
                         vars:QVars, tco:TCO}).

%! allocation_to_ws(+Allocation, +TCO, +WebSocket) is det.
%
allocation_to_ws(Allocation, TCO, WebSocket) :-
    findall(PartJSON,
            ( member(alloc(Part, Qs), Allocation),
              findall(SupplierJSON,
                      ( member(q(Supplier, Q), Qs),
                        Q > 0,
                        SupplierJSON = _{supplier:Supplier, qty:Q}
                      ),
                      SuppliersJSON),
              PartJSON = _{part:Part, suppliers:SuppliersJSON}
            ),
            PartList),
    send_ws(WebSocket, _{event:"allocation", allocation:PartList, tco:TCO}).

%! send_ws(+WebSocket, +Dict) is det.
%
send_ws(WebSocket, Dict) :-
    with_output_to(string(Msg),
                   json_write(current_output, Dict, [width(0)])),
    ws_send(WebSocket, text(Msg)).

%! close_ws(+WebSocket) is det.
%
close_ws(WebSocket) :-
    ws_close(WebSocket).

%% ------------------------------------------------------------------ %%
%%  /trace  (HTML visualization page)                                 %%
%% ------------------------------------------------------------------ %%

serve_trace_html(_Request) :-
    http_reply_file('trace.html', [], [unsafe(true)]).

%% ------------------------------------------------------------------ %%
%%  /health                                                            %%
%% ------------------------------------------------------------------ %%

handle_health(_Request) :-
    reply_json_dict(_{status:ok}).

%% ------------------------------------------------------------------ %%
%%  JSON CONVERSION                                                    %%
%% ------------------------------------------------------------------ %%

%! allocation_to_json(+Allocation, +TCO, +Status, -JSON) is det.
allocation_to_json(Allocation, TCO, Status, JSON) :-
    findall(PartJSON,
            ( member(alloc(Part, Qs), Allocation),
              part_allocations_to_json(Part, Qs, SuppliersJSON),
              PartJSON = _{part:Part, suppliers:SuppliersJSON}
            ),
            Allocations),
    JSON = _{tco:TCO, status:Status, allocations:Allocations}.

part_allocations_to_json(Part, Qs, SuppliersJSON) :-
    findall(SupplierJSON,
            ( member(q(Supplier, Q), Qs),
              Q > 0,
              effective_unit_cost(Supplier, Part, Q, EffCost),
              Subtotal is Q * EffCost,
              (   fixed_cost(Supplier, Part, Fixed)
              ->  FixedCost = Fixed
              ;   FixedCost = 0
              ),
              SupplierJSON = _{supplier:Supplier, qty:Q, unit_cost:EffCost,
                               subtotal:Subtotal, fixed_cost:FixedCost}
            ),
            SuppliersJSON).

%! scenarios_to_json(+Results, -JSON) is det.
scenarios_to_json(Results, JSON) :-
    findall(ResultJSON,
            ( member(result(Name, Status, TCO, _), Results),
              ResultJSON = _{name:Name, status:Status, tco:TCO}
            ),
            ResultsJSON),
    (   ResultsJSON = [First|_],
        First.get(name) = FirstName,
        member(result(FirstName, _, BaseTCO, _), Results)
    ->  findall(DeltaJSON,
                ( member(result(Name, _, TCO, _), Results),
                  Name \= FirstName,
                  TCO \= -,
                  Delta is TCO - BaseTCO,
                  Pct is round(Delta * 100 / BaseTCO),
                  DeltaJSON = _{name:Name, delta:Delta, pct:Pct}
                ),
                DeltasJSON)
    ;   DeltasJSON = []
    ),
    JSON = _{results:ResultsJSON, deltas:DeltasJSON}.

%% ------------------------------------------------------------------ %%
%%  JSON SCENARIO PARSING                                              %%
%% ------------------------------------------------------------------ %%

%! json_to_scenarios(+JSONScenarios, -ScenarioList) is det.
%  Converts JSON scenario objects to Prolog Name-Overrides pairs.
%  "overrides" may be omitted; a scenario without it is the baseline.
json_to_scenarios([], []).
json_to_scenarios([H|T], [Name-Overrides|Rest]) :-
    get_dict(name, H, Name),
    (   get_dict(overrides, H, JSONOverrides)
    ->  true
    ;   JSONOverrides = []
    ),
    json_overrides_to_prolog(JSONOverrides, Overrides),
    json_to_scenarios(T, Rest).

json_overrides_to_prolog([], []).
json_overrides_to_prolog([H|T], [Override|Rest]) :-
    json_override_to_prolog(H, Override),
    json_overrides_to_prolog(T, Rest).

%! json_override_to_prolog(+JSON, -Override) is det.
%
%  Names arrive as text and must become atoms, because that is what the
%  loaded facts hold: the string "ti" does not unify with the atom ti, and
%  an override on it would silently change nothing. An override this
%  does not recognise is an error for the same reason.
json_override_to_prolog(JSON, Override) :-
    (   get_dict(set, JSON, FactText)
    ->  override_term(FactText, Fact),
        Override = set(Fact)
    ;   get_dict(remove, JSON, TemplateText)
    ->  override_term(TemplateText, Template),
        Override = remove(Template)
    ;   get_dict(cost_delta, JSON, [Supplier0, Part0, Pct])
    ->  atom_string(Supplier, Supplier0),
        atom_string(Part, Part0),
        Override = cost_delta(Supplier, Part, Pct)
    ;   get_dict(demand_delta, JSON, [Part0, Pct])
    ->  atom_string(Part, Part0),
        Override = demand_delta(Part, Pct)
    ;   throw(error(domain_error(scenario_override, JSON), _))
    ).

%! override_term(+Text, -Term) is det.
%
%  Parse a fact written as text, reading every name as a name.
%
%  Prolog reads a capitalised word as a VARIABLE, and part numbers are
%  capitalised — "share(ABC,ti,70,70)" would otherwise mean "the share of
%  any part at all", and the solve died with "Arguments are not
%  sufficiently instantiated". So each named variable is bound to the atom
%  it spells. Only `_` and `_Name` stay variables: they are how a remove/1
%  template says "any value" (remove(max_global_share(supplier2,_))).
override_term(Text, Term) :-
    term_string(Term, Text, [variable_names(Bindings)]),
    maplist(bind_name_as_atom, Bindings).

bind_name_as_atom(Name=Var) :-
    (   sub_atom(Name, 0, 1, _, '_')
    ->  true
    ;   Var = Name
    ).

%! compare_scenario_dicts_to_json(+Scenarios, -JSON) is det.
%  Entry point for callers that hold scenarios as data (Python dicts via
%  janus). Nothing is pasted into query text, so no name can break it.
compare_scenario_dicts_to_json(Scenarios, JSON) :-
    json_to_scenarios(Scenarios, ScenarioList),
    compare_scenarios(ScenarioList, Results),
    scenarios_to_json(Results, JSON).

%% ------------------------------------------------------------------ %%
%%  STANDALONE JSON (no HTTP)                                          %%
%% ------------------------------------------------------------------ %%

%! validate_to_json(-JSON) is det.
%  Structured validation findings. `status` is "error" when any issue
%  would make the model unsolvable or wrong, "warning" for suspicious
%  data, "ok" when clean.
validate_to_json(JSON) :-
    validation_issues(Issues),
    findall(_{severity:SevStr, message:Msg, detail:DetailStr},
            ( member(Issue, Issues),
              issue_severity(Issue, Sev),
              atom_string(Sev, SevStr),
              issue_message(Issue, MsgAtom),
              atom_string(MsgAtom, Msg),
              term_string(Issue, DetailStr)
            ),
            Findings),
    overall_validation_status(Issues, Status),
    length(Findings, N),
    JSON = _{status:Status, issue_count:N, issues:Findings}.

overall_validation_status(Issues, Status) :-
    (   member(I, Issues), issue_severity(I, error)
    ->  Status = "error"
    ;   member(I, Issues), issue_severity(I, warning)
    ->  Status = "warning"
    ;   Status = "ok"
    ).

%! rebates_to_json(-JSON) is det.
%  Portfolio rebates currently in effect.
rebates_to_json(JSON) :-
    findall(_{supplier:S, threshold:T, pct:P},
            rebate(S, T, P),
            JSON).

%! disqualified_to_json(-JSON) is det.
%  Excluded (part, supplier) pairs with reasons, as JSON dicts.
disqualified_to_json(JSON) :-
    disqualified_pairs(Exclusions),
    findall(_{part:P, supplier:S, reasons:RStrs},
            ( member(excluded(P, S, Rs), Exclusions),
              findall(RStr, (member(R, Rs), term_string(R, RStr)), RStrs)
            ),
            JSON).

%! solve_to_json(-JSON) is det.
%  Solve using already-loaded facts, return JSON dict.
%  Hides compound terms from janus-swi.
solve_to_json(JSON) :-
    (   solve(Allocation, TCO)
    ->  allocation_to_json(Allocation, TCO, ok, JSON)
    ;   JSON = _{status:infeasible, tco:null, allocations:[]}
    ).

%! solve_to_json(+MaxCost, -JSON) is det.
solve_to_json(MaxCost, JSON) :-
    (   solve(Allocation, TCO, MaxCost)
    ->  allocation_to_json(Allocation, TCO, ok, JSON)
    ;   JSON = _{status:infeasible, tco:null, allocations:[]}
    ).

%! solve_json(+Path, -JSON) is det.
%  Load CSV, solve, return JSON dict (for janus-swi / Python).
solve_json(Path, JSON) :-
    with_output_to(string(_), load_csv(Path)),
    solve_to_json(JSON).

%! solve_json(+Path, +MaxCost, -JSON) is det.
solve_json(Path, MaxCost, JSON) :-
    with_output_to(string(_), load_csv(Path)),
    solve_to_json(MaxCost, JSON).

%! scenarios_json(+Path, +Scenarios, -JSON) is det.
%  Load CSV, run scenarios, return JSON dict.
scenarios_json(Path, Scenarios, JSON) :-
    with_output_to(string(_), load_csv(Path)),
    compare_scenarios(Scenarios, Results),
    scenarios_to_json(Results, JSON).

%! compare_scenarios_to_json(+Scenarios, -JSON) is det.
%  Run scenarios using already-loaded facts, return JSON.
%  Hides compound terms from janus-swi.
compare_scenarios_to_json(Scenarios, JSON) :-
    compare_scenarios(Scenarios, Results),
    scenarios_to_json(Results, JSON).

%% ------------------------------------------------------------------ %%
%%  RULES READ BACK                                                    %%
%% ------------------------------------------------------------------ %%
%
%  "The rules are the model" is only a promise if a buyer can see the
%  model. validate/1 speaks up when something is wrong; this says what
%  was understood, with the defaults the solver will apply filled in, so
%  a sign-off is on the rules that run — not on a reading of the CSV.
%  Only rules that are present appear; an absent key means "no limit".

%! rules_to_json(-JSON) is det.
rules_to_json(_{parts:PartsJSON, suppliers:SuppliersJSON, portfolio:Portfolio}) :-
    parts(Parts),
    suppliers(Suppliers),
    findall(J, ( member(P, Parts), part_rules_json(P, Suppliers, J) ), PartsJSON),
    findall(J, ( member(S, Suppliers), supplier_rules_json(S, J) ), SuppliersJSON),
    portfolio_rules_json(Portfolio).

part_rules_json(P, Suppliers, J) :-
    demand(P, D),
    min_suppliers_of(P, MinN),
    findall(Q, ( member(S, Suppliers), allocatable(P, S),
                 quote_rules_json(P, S, Q) ),
            Quotes),
    findall(K-V,
            (   K = max_suppliers, max_suppliers(P, V)
            ;   K = dual_source, dual_source(P), V = true
            ;   K = award_step_pct, once(share_increment_of(P, V))
            ;   K = max_lead_time_days, max_lead_time(P, V)
            ;   K = required_certifications,
                findall(C, required_certification(P, C), V), V \== []
            ),
            Optional),
    rules_dict([part-P, demand-D, min_suppliers-MinN, quotes-Quotes|Optional], J).

quote_rules_json(P, S, J) :-
    share_of(P, S, SMin, SMax),
    (   qualified(P, S) -> Qualified = true ; Qualified = false ),
    findall(K-V,
            (   K = unit_cost, cost(S, P, V)
            ;   K = price_tiers, has_tiers(S, P),
                findall(_{from:Mn, to:To, unit_cost:C},
                        ( price_tier(S, P, Mn, Mx, C),
                          ( Mx == sup -> To = null ; To = Mx ) ),
                        V)
            ;   K = lowest_landed_unit_cost, unit_cost_floor(S, P, V)
            ;   K = capacity, capacity_of(S, P, V), V \== sup
            ;   K = moq, moq(S, P, V), V > 0
            ;   K = share_min_pct, SMin > 0, V = SMin
            ;   K = share_max_pct, SMax < 100, V = SMax
            ;   K = fixed_cost, fixed_cost(S, P, V)
            ;   K = lead_time_days, lead_time(S, P, V)
            ;   K = excluded_because,
                findall(Str, ( disqualified(P, S, R),
                               reason_phrase(R, Ph),
                               format(string(Str), "~w", [Ph]) ),
                        V0),
                sort(V0, V), V \== []
            ),
            Optional),
    rules_dict([supplier-S, qualified-Qualified|Optional], J).

supplier_rules_json(S, J) :-
    findall(K-V,
            (   K = global_capacity, global_capacity(S, V)
            ;   K = max_share_of_total_pct, max_global_share(S, V)
            ;   K = rebate, rebate(S, Th, Pct), V = _{threshold:Th, pct:Pct}
            ;   K = otif_pct, otif(S, V)
            ;   K = region, region(S, V)
            ;   K = fx_rate_pct, region(S, R), fx_rate(R, V)
            ;   K = logistics_per_unit, region(S, R), logistics_cost(R, V)
            ;   K = noncost_adjustment, noncost_adjustment(S, V)
            ;   K = certifications,
                findall(C, certification(S, C), V), V \== []
            ;   K = route, supplier_route(S, V)
            ),
            Optional),
    rules_dict([supplier-S|Optional], J).

portfolio_rules_json(J) :-
    findall(K-V,
            (   K = min_otif_pct, min_otif(V)
            ;   K = required_certifications,
                findall(C, required_certification(C), V), V \== []
            ;   K = route_capacity,
                findall(_{route:R, capacity:C}, route_capacity(R, C), V), V \== []
            ;   K = route_share_cap,
                findall(_{route:R, max_pct:C}, max_route_share(R, C), V), V \== []
            ;   K = default_award_step_pct, share_increment(V)
            ),
            Optional),
    rules_dict(Optional, J).

%  First value per key wins, so a stray duplicate fact cannot make
%  dict_pairs/3 throw.
rules_dict(Pairs, Dict) :-
    first_per_key(Pairs, [], Unique),
    dict_pairs(Dict, _, Unique).

first_per_key([], _, []).
first_per_key([K-V|Rest], Seen, Out) :-
    (   memberchk(K, Seen)
    ->  Out = Out1
    ;   Out = [K-V|Out1]
    ),
    first_per_key(Rest, [K|Seen], Out1).
