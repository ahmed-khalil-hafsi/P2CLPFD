%%% P2CLPFD — Traced Solver (real-time visualization)
%%%
%%% Emits NDJSON events as the solver builds constraints and finds
%%% the optimal solution.  Domain snapshots are taken after each
%%% constraint group to show narrowing in real time.
%%%
%%% Events:
%%%   {"event":"model_built","parts":[...],"suppliers":[...],
%%%    "vars":[{"name":"q.s1.p1","role":"qty"},...]}
%%%   {"event":"domain_snapshot","phase":"parts",
%%%    "vars":[{"name":"q.s1.p1","domain":[0,1,...]},...]}
%%%   {"event":"domain_snapshot","phase":"capacity","vars":[...]}
%%%   {"event":"domain_snapshot","phase":"risk","vars":[...]}
%%%   {"event":"domain_snapshot","phase":"global_share","vars":[...]}
%%%   {"event":"domain_snapshot","phase":"rebates","vars":[...]}
%%%   {"event":"phase","phase":"searching"}
%%%   {"event":"solution_found","tco":19534,"type":"first"}
%%%   {"event":"phase","phase":"optimal"}
%%%   {"event":"domain_snapshot","phase":"final","vars":[...]}
%%%   {"event":"optimal","tco":18200}
%%%   {"event":"infeasible"}

:- use_module(library(clpfd)).
:- use_module(library(http/json)).

%% ------------------------------------------------------------------ %%
%%  PUBLIC API                                                         %%
%% ------------------------------------------------------------------ %%

solve_with_trace(Allocation, TCO, Stream) :-
    parts(Parts),
    suppliers(Suppliers),
    build_var_index_only(Parts, Suppliers, VarIdx),

    emit(Stream, _{event:"model_built",
                   parts:Parts,
                   suppliers:Suppliers,
                   vars:VarIdx}),

    build_model_traced(Parts, Suppliers, RawAlloc, Vars, TCO, Stream),

    emit(Stream, _{event:"phase", phase:"searching"}),

    (   labeling([min(TCO)], Vars)
    ->  materialize(RawAlloc, Allocation),
        emit_domains_ground(Stream, Allocation, TCO, "final"),
        emit(Stream, _{event:"phase", phase:"optimal"}),
        emit(Stream, _{event:"optimal", tco:TCO})
    ;   emit(Stream, _{event:"infeasible"}),
        fail
    ).

solve_with_trace(Allocation, TCO, Stream, MaxCost) :-
    parts(Parts),
    suppliers(Suppliers),
    build_var_index_only(Parts, Suppliers, VarIdx),

    emit(Stream, _{event:"model_built",
                   parts:Parts, suppliers:Suppliers,
                   vars:VarIdx, max_cost:MaxCost}),

    build_model_traced(Parts, Suppliers, RawAlloc, Vars, TCO, Stream),

    TCO #=< MaxCost,
    emit(Stream, _{event:"phase", phase:"searching"}),

    (   labeling([min(TCO)], Vars)
    ->  materialize(RawAlloc, Allocation),
        emit_domains_ground(Stream, Allocation, TCO, "final"),
        emit(Stream, _{event:"phase", phase:"optimal"}),
        emit(Stream, _{event:"optimal", tco:TCO})
    ;   emit(Stream, _{event:"infeasible"}),
        fail
    ).

%% ------------------------------------------------------------------ %%
%%  STEP-BY-STEP MODEL BUILDING                                        %%
%% ------------------------------------------------------------------ %%

% Mirrors build_model/5 but emits domain snapshots between phases.
% Does NOT modify solver.pl — calls the same sub-predicates directly.
%
build_model_traced(Parts, Suppliers, RawAlloc, Vars, TCO, Stream) :-
    build_parts(Parts, Suppliers, RawAlloc, PartCosts, VarsParts, AllBs),
    emit_domains(Stream, RawAlloc, "parts"),

    build_global_capacity(Suppliers, RawAlloc),
    emit_domains(Stream, RawAlloc, "capacity"),

    post_risk_constraints(Parts, AllBs),
    emit_domains(Stream, RawAlloc, "risk"),

    post_global_share(RawAlloc, Parts),
    emit_domains(Stream, RawAlloc, "global_share"),

    (   build_rebates(Suppliers, RawAlloc, PartCosts, TCO)
    ->  append(VarsParts, Vars),
        emit_domains(Stream, RawAlloc, "rebates")
    ;   sum(PartCosts, #=, TCO),
        append(VarsParts, Vars),
        emit_domains(Stream, RawAlloc, "tco")
    ).

%% ------------------------------------------------------------------ %%
%%  VARIABLE INDEX (static, built from parts/suppliers only)          %%
%% ------------------------------------------------------------------ %%

build_var_index_only(Parts, Suppliers, VarIdx) :-
    findall(V,
            ( member(Part, Parts),
              member(Supplier, Suppliers),
              atom_string(Supplier, SStr),
              atom_string(Part, PStr),
              string_concat("q.", SStr, T1),
              string_concat(T1, ".", T2),
              string_concat(T2, PStr, QName),
              V = _{name:QName, role:"qty"}
            ),
            VarIdx).

%% ------------------------------------------------------------------ %%
%%  DOMAIN SNAPSHOT (variables are still FD vars)                     %%
%% ------------------------------------------------------------------ %%

emit_domains(Stream, RawAlloc, Phase) :-
    findall(D,
            ( member(alloc(Part, Qs), RawAlloc),
              member(q(Supplier, Q, _), Qs),
              var(Q),
              atom_string(Supplier, SStr),
              atom_string(Part, PStr),
              string_concat("q.", SStr, T1),
              string_concat(T1, ".", T2),
              string_concat(T2, PStr, QName),
              fd_dom(Q, Dom),
              dom_to_list(Dom, List),
              D = _{name:QName, domain:List}
            ),
            Vars),
    emit(Stream, _{event:"domain_snapshot", phase:Phase, vars:Vars}).

%% ------------------------------------------------------------------ %%
%%  DOMAIN SNAPSHOT (after labeling — vars are ground)                %%
%% ------------------------------------------------------------------ %%

emit_domains_ground(Stream, Allocation, TCO, Phase) :-
    findall(D,
            ( member(alloc(Part, Qs), Allocation),
              member(q(Supplier, Q), Qs),
              Q > 0,
              atom_string(Supplier, SStr),
              atom_string(Part, PStr),
              string_concat("q.", SStr, T1),
              string_concat(T1, ".", T2),
              string_concat(T2, PStr, QName),
              D = _{name:QName, domain:[Q]}
            ),
            QVars),
    emit(Stream, _{event:"domain_snapshot", phase:Phase,
                   vars:QVars, tco:TCO}).

%% ------------------------------------------------------------------ %%
%%  DOMAIN HELPERS                                                     %%
%% ------------------------------------------------------------------ %%

dom_to_list(Dom, List) :-
    (   integer(Dom)
    ->  List = [Dom]
    ;   Dom = (Lo..Hi)
    ->  numlist(Lo, Hi, List)
    ;   Dom = (A \/ B)
    ->  dom_to_list(A, LA),
        dom_to_list(B, LB),
        merge_ord(LA, LB, List)
    ;   List = []
    ).

merge_ord([], B, B) :- !.
merge_ord(A, [], A) :- !.
merge_ord([A|As], [B|Bs], [A,B|Cs]) :-
    A =< B, !,
    merge_ord(As, [B|Bs], Cs).
merge_ord([A|As], [B|Bs], [B|Cs]) :-
    merge_ord([A|As], Bs, Cs).

%% ------------------------------------------------------------------ %%
%%  EVENT EMISSION                                                     %%
%% ------------------------------------------------------------------ %%

emit(Stream, Dict) :-
    json_write(Stream, Dict),
    nl(Stream),
    flush_output(Stream).

%% ------------------------------------------------------------------ %%
%%  CAPTURE TRACE (for MCP / Python integration)                      %%
%% ------------------------------------------------------------------ %%

%! solve_with_trace_captured(-TraceString, -TCO) is semidet.
%
%  Like solve_with_trace/4 but captures the NDJSON trace into a string
%  and returns TCO.  Convenient for janus-swi / Python callers.
%
solve_with_trace_captured(Trace, TCO) :-
    with_output_to(string(Trace),
                   solve_with_trace(_, TCO, current_output)).

%! solve_with_trace_captured(+MaxCost, -TraceString, -TCO) is semidet.
%
solve_with_trace_captured(MaxCost, Trace, TCO) :-
    with_output_to(string(Trace),
                   solve_with_trace(_, TCO, current_output, MaxCost)).
