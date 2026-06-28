%%% P2CLPFD — JSON API + HTTP Server
%%%
%%% Exposes the solver as a JSON HTTP API so any agent (Claude, GPT, etc.)
%%% can call it over HTTP.
%%%
%%% Start the server:
%%%   swipl -g "server(8080)" -g halt main.pl json_api.pl
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

%% ------------------------------------------------------------------ %%
%%  HTTP SERVER                                                        %%
%% ------------------------------------------------------------------ %%

:- http_handler('/solve',      handle_solve,      [method(post)]).
:- http_handler('/scenarios',   handle_scenarios,  [method(post)]).
:- http_handler('/validate',    handle_validate,   [method(post)]).
:- http_handler('/health',      handle_health,     [method(get)]).

%! server(+Port) is det.
server(Port) :-
    format('P2CLPFD server on port ~w~n', [Port]),
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
        with_output_to(string(_), validate_facts),
        Response = _{status:ok, warnings:[]}
    ;   Response = _{status:error, message:"csv_path required"}
    ),
    reply_json_dict(Response).

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
json_to_scenarios([], []).
json_to_scenarios([H|T], [Name-Overrides|Rest]) :-
    get_dict(name, H, Name),
    get_dict(overrides, H, JSONOverrides),
    json_overrides_to_prolog(JSONOverrides, Overrides),
    json_to_scenarios(T, Rest).

json_overrides_to_prolog([], []).
json_overrides_to_prolog([H|T], [Override|Rest]) :-
    json_override_to_prolog(H, Override),
    json_overrides_to_prolog(T, Rest).

json_override_to_prolog(JSON, Override) :-
    (   get_dict(set, JSON, FactStr)
    ->  term_string(Fact, FactStr),
        Override = set(Fact)
    ;   get_dict(remove, JSON, TemplateStr)
    ->  term_string(Template, TemplateStr),
        Override = remove(Template)
    ;   get_dict(cost_delta, JSON, [Supplier, Part, Pct])
    ->  Override = cost_delta(Supplier, Part, Pct)
    ;   get_dict(demand_delta, JSON, [Part, Pct])
    ->  Override = demand_delta(Part, Pct)
    ).

%% ------------------------------------------------------------------ %%
%%  STANDALONE JSON (no HTTP)                                          %%
%% ------------------------------------------------------------------ %%

%! solve_json(+Path, -JSON) is det.
%  Load CSV, solve, return JSON atom.
solve_json(Path, JSON) :-
    load_csv(Path),
    (   solve(Allocation, TCO)
    ->  allocation_to_json(Allocation, TCO, ok, Result),
        atom_json_dict(JSON, Result, [])
    ;   atom_json_dict(JSON, _{status:infeasible, tco:null, allocations:[]}, [])
    ).

%! solve_json(+Path, +MaxCost, -JSON) is det.
solve_json(Path, MaxCost, JSON) :-
    load_csv(Path),
    (   solve(Allocation, TCO, MaxCost)
    ->  allocation_to_json(Allocation, TCO, ok, Result),
        atom_json_dict(JSON, Result, [])
    ;   atom_json_dict(JSON, _{status:infeasible, tco:null, allocations:[]}, [])
    ).
