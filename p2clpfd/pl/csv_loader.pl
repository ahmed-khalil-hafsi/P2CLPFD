%%% P2CLPFD — CSV Loader
%%%
%%% Reads a single CSV file and asserts all procurement facts.
%%% Replaces any previously loaded facts (both from facts.pl and
%%% prior load_csv/1 calls).
%%%
%%% Usage:
%%%   ?- ['csv_loader.pl'].
%%%   ?- load_csv('data.csv').
%%%   ?- run.
%%%
%%% CSV format (header row required):
%%%
%%%   part,supplier,demand,unit_cost,capacity,moq,
%%%   share_min,share_max,noncost_adj,fixed_cost,
%%%   min_suppliers,max_suppliers,dual_source,
%%%   global_capacity,global_share_cap
%%%
%%% Empty cells are treated as "absent" (no constraint / default).
%%% Per-part and per-supplier attributes may appear in any row of
%%% that part/supplier; the last non-empty value wins.

:- use_module(library(csv)).

%% ------------------------------------------------------------------ %%
%%  Dynamic declarations (self-contained, no dependency on facts.pl)   %%
%% ------------------------------------------------------------------ %%

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
%%  PUBLIC API                                                         %%
%% ------------------------------------------------------------------ %%

%! load_csv(+Path) is det.
%
%  Reads a CSV file and asserts all procurement facts.
%  Clears any previously loaded facts first.
%
load_csv(Path) :-
    (   exists_file(Path)
    ->  true
    ;   format('ERROR: file not found: ~w~n', [Path]),
        fail
    ),
    csv_read_file(Path, Rows, [strip(true)]),
    retract_all_facts,
    Rows = [HeaderRow | DataRows],
    HeaderRow =.. [_ | Header],
    assert_rows(Header, DataRows),
    length(DataRows, N),
    format('Loaded ~w rows from ~w~n', [N, Path]).

%! load_csv(+Path, +Options) is det.
%
%  As load_csv/1 but with options:
%    keep_existing(true) — don't clear existing facts before loading
%
load_csv(Path, Options) :-
    (   memberchk(keep_existing(true), Options)
    ->  true
    ;   retract_all_facts
    ),
    csv_read_file(Path, Rows, [strip(true)]),
    Rows = [HeaderRow | DataRows],
    HeaderRow =.. [_ | Header],
    assert_rows(Header, DataRows),
    length(DataRows, N),
    format('Loaded ~w rows from ~w~n', [N, Path]).

%% ------------------------------------------------------------------ %%
%%  FACT MANAGEMENT                                                    %%
%% ------------------------------------------------------------------ %%

retract_all_facts :-
    retractall(demand(_, _)),
    retractall(cost(_, _, _)),
    retractall(price_tier(_, _, _, _, _)),
    retractall(capacity(_, _, _)),
    retractall(moq(_, _, _)),
    retractall(share(_, _, _, _)),
    retractall(global_capacity(_, _)),
    retractall(noncost_adjustment(_, _)),
    retractall(fixed_cost(_, _, _)),
    retractall(min_suppliers(_, _)),
    retractall(max_suppliers(_, _)),
    retractall(dual_source(_)),
    retractall(max_global_share(_, _)).

%% ------------------------------------------------------------------ %%
%%  HELPERS                                                            %%
%% ------------------------------------------------------------------ %%

%! to_number(+Value, -Number) is det.
%  Converts Value to a number. Handles atoms (strings) and integers.
to_number(Value, Number) :-
    (   atom(Value)
    ->  atom_number(Value, Number)
    ;   number(Value)
    ->  Number = Value
    ;   format('  !! WARNING: cannot convert ~w to number~n', [Value]),
        Number = 0
    ).

%% ------------------------------------------------------------------ %%
%%  ROW PROCESSING                                                     %%
%% ------------------------------------------------------------------ %%

assert_rows(_, []).
assert_rows(Header, [Row | Rest]) :-
    Row =.. [_Functor | Values],
    pairs_keys_values(Pairs, Header, Values),
    assert_row_facts(Pairs),
    assert_rows(Header, Rest).

assert_row_facts(Pairs) :-
    % Part and supplier are required
    (   member(part-Part, Pairs), Part \= ''
    ->  true
    ;   format('  !! SKIP: row missing "part"~n'),
        fail
    ),
    (   member(supplier-Supplier, Pairs), Supplier \= ''
    ->  true
    ;   format('  !! SKIP: row missing "supplier"~n'),
        fail
    ),
    % Per-pair facts
    assert_pair_fact(demand, demand(Part, _), Part, Pairs),
    assert_pair_fact(unit_cost, cost(_, Part, _), Supplier-Part, Pairs),
    assert_pair_fact(capacity, capacity(_, Part, _), Supplier-Part, Pairs),
    assert_pair_fact(moq, moq(_, Part, _), Supplier-Part, Pairs),
    assert_share_fact(Part, Supplier, Pairs),
    assert_noncost_fact(Supplier, Pairs),
    assert_pair_fact(fixed_cost, fixed_cost(_, Part, _), Supplier-Part, Pairs),
    % Per-part facts
    assert_part_fact(min_suppliers, min_suppliers(Part, _), Part, Pairs),
    assert_part_fact(max_suppliers, max_suppliers(Part, _), Part, Pairs),
    assert_dual_source_fact(Part, Pairs),
    % Per-supplier facts
    assert_supplier_fact(global_capacity, global_capacity(_, _), Supplier, Pairs),
    assert_supplier_fact(global_share_cap, max_global_share(_, _), Supplier, Pairs).

%% --- Per-pair facts (last non-empty value per CSV key wins) ----------

assert_pair_fact(CSVKey, Template, Key, Pairs) :-
    member(CSVKey-Value, Pairs),
    Value \= '',
    !,
    to_number(Value, Number),
    (   Template = demand(Part, _)
    ->  retractall(demand(Part, _)),
        assert(demand(Part, Number))
    ;   Template = cost(_, Part, _)
    ->  (   Key = Supplier-Part
        ->  retractall(cost(Supplier, Part, _)),
            assert(cost(Supplier, Part, Number))
        )
    ;   Template = capacity(_, Part, _)
    ->  (   Key = Supplier-Part
        ->  retractall(capacity(Supplier, Part, _)),
            assert(capacity(Supplier, Part, Number))
        )
    ;   Template = moq(_, Part, _)
    ->  (   Key = Supplier-Part
        ->  retractall(moq(Supplier, Part, _)),
            assert(moq(Supplier, Part, Number))
        )
    ;   Template = fixed_cost(_, Part, _)
    ->  (   Key = Supplier-Part
        ->  retractall(fixed_cost(Supplier, Part, _)),
            assert(fixed_cost(Supplier, Part, Number))
        )
    ).
assert_pair_fact(_, _, _, _).

%% --- Share fact (composite: share_min + share_max) ------------------

assert_share_fact(Part, Supplier, Pairs) :-
    (   member(share_min-MinVal, Pairs), MinVal \= ''
    ->  to_number(MinVal, MinPct)
    ;   MinPct = 0
    ),
    (   member(share_max-MaxVal, Pairs), MaxVal \= ''
    ->  to_number(MaxVal, MaxPct)
    ;   MaxPct = 100
    ),
    (   MinPct =:= 0, MaxPct =:= 100
    ->  true
    ;   retractall(share(Part, Supplier, _, _)),
        assert(share(Part, Supplier, MinPct, MaxPct))
    ).

%% --- Non-cost adjustment (per supplier, not per pair) ---------------

assert_noncost_fact(Supplier, Pairs) :-
    member(noncost_adj-Value, Pairs),
    Value \= '',
    !,
    to_number(Value, Adj),
    retractall(noncost_adjustment(Supplier, _)),
    assert(noncost_adjustment(Supplier, Adj)).
assert_noncost_fact(_, _).

%% --- Per-part facts -------------------------------------------------

assert_part_fact(CSVKey, Template, Part, Pairs) :-
    member(CSVKey-Value, Pairs),
    Value \= '',
    !,
    to_number(Value, Number),
    (   Template = min_suppliers(Part, _)
    ->  retractall(min_suppliers(Part, _)),
        assert(min_suppliers(Part, Number))
    ;   Template = max_suppliers(Part, _)
    ->  retractall(max_suppliers(Part, _)),
        assert(max_suppliers(Part, Number))
    ).
assert_part_fact(_, _, _, _).

assert_dual_source_fact(Part, Pairs) :-
    member(dual_source-Value, Pairs),
    Value \= '',
    !,
    retractall(dual_source(Part)),
    assert(dual_source(Part)).
assert_dual_source_fact(_, _).

%% --- Per-supplier facts ---------------------------------------------

assert_supplier_fact(CSVKey, Template, Supplier, Pairs) :-
    member(CSVKey-Value, Pairs),
    Value \= '',
    !,
    to_number(Value, Number),
    (   Template = global_capacity(_, _)
    ->  retractall(global_capacity(Supplier, _)),
        assert(global_capacity(Supplier, Number))
    ;   Template = max_global_share(_, _)
    ->  retractall(max_global_share(Supplier, _)),
        assert(max_global_share(Supplier, Number))
    ).
assert_supplier_fact(_, _, _, _).

%% ------------------------------------------------------------------ %%
%%  EXAMPLE QUERIES                                                    %%
%% ------------------------------------------------------------------ %%

%% ?- load_csv('sample.csv').
%% ?- load_csv('sample.csv'), run.
%% ?- load_csv('sample.csv', [keep_existing(true)]).
