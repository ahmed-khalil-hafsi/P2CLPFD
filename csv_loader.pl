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
%%%   global_capacity,global_share_cap,
%%%   otif,min_otif,lead_time,max_lead_time,
%%%   certifications,required_certs
%%%
%%% Qualification columns (all optional):
%%%   otif           per-supplier OTIF %% (0..100)
%%%   min_otif       global OTIF gate; suppliers below (or with no otif)
%%%                  are disqualified from all parts
%%%   lead_time      per part+supplier quoted lead time (days)
%%%   max_lead_time  per-part lead-time gate (days)
%%%   certifications per-supplier, semicolon-separated (iso9001;iatf16949)
%%%   required_certs per-part, semicolon-separated
%%%
%%% Landed-cost columns (all optional):
%%%   region         per-supplier region atom (china, eu, local, ...)
%%%   fx_rate        FX multiplier as integer % for that row's region
%%%   logistics_cost per-unit freight/customs for that row's region
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
    retractall(max_global_share(_, _)),
    retractall(rebate(_, _, _)),
    retractall(otif(_, _)),
    retractall(min_otif(_)),
    retractall(lead_time(_, _, _)),
    retractall(max_lead_time(_, _)),
    retractall(certification(_, _)),
    retractall(required_certification(_)),
    retractall(required_certification(_, _)),
    retractall(region(_, _)),
    retractall(fx_rate(_, _)),
    retractall(logistics_cost(_, _)).

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
    assert_pair_fact(lead_time, lead_time(_, Part, _), Supplier-Part, Pairs),
    % Per-part facts
    assert_part_fact(max_lead_time, max_lead_time(Part, _), Part, Pairs),
    assert_required_certs_fact(Part, Pairs),
    % Per-supplier facts
    assert_supplier_fact(global_capacity, global_capacity(_, _), Supplier, Pairs),
    assert_supplier_fact(global_share_cap, max_global_share(_, _), Supplier, Pairs),
    assert_supplier_fact(otif, otif(_, _), Supplier, Pairs),
    assert_certifications_fact(Supplier, Pairs),
    assert_region_facts(Supplier, Pairs),
    % Global facts (may appear on any row; last non-empty wins)
    assert_global_min_otif(Pairs).

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
    ;   Template = lead_time(_, Part, _)
    ->  (   Key = Supplier-Part
        ->  retractall(lead_time(Supplier, Part, _)),
            assert(lead_time(Supplier, Part, Number))
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
    ;   Template = max_lead_time(Part, _)
    ->  retractall(max_lead_time(Part, _)),
        assert(max_lead_time(Part, Number))
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
    ;   Template = otif(_, _)
    ->  retractall(otif(Supplier, _)),
        assert(otif(Supplier, Number))
    ).
assert_supplier_fact(_, _, _, _).

%% --- Qualification gate facts ----------------------------------------
%   certifications:  per-supplier, semicolon-separated (e.g. "iso9001;iatf16949")
%   required_certs:  per-part, semicolon-separated
%   min_otif:        global threshold (may appear on any row)

assert_certifications_fact(Supplier, Pairs) :-
    member(certifications-Value, Pairs),
    Value \= '',
    !,
    retractall(certification(Supplier, _)),
    split_cert_list(Value, Certs),
    forall(member(C, Certs), assert(certification(Supplier, C))).
assert_certifications_fact(_, _).

assert_required_certs_fact(Part, Pairs) :-
    member(required_certs-Value, Pairs),
    Value \= '',
    !,
    retractall(required_certification(Part, _)),
    split_cert_list(Value, Certs),
    forall(member(C, Certs), assert(required_certification(Part, C))).
assert_required_certs_fact(_, _).

assert_global_min_otif(Pairs) :-
    member(min_otif-Value, Pairs),
    Value \= '',
    !,
    to_number(Value, Number),
    retractall(min_otif(_)),
    assert(min_otif(Number)).
assert_global_min_otif(_).

%% --- Landed cost facts ------------------------------------------------
%   region:          per-supplier region atom (e.g. china, eu, local)
%   fx_rate:         per-region FX multiplier as integer % (105 = +5%)
%   logistics_cost:  per-region per-unit freight/customs cost
%   fx_rate / logistics_cost apply to the region named in the same row.

assert_region_facts(Supplier, Pairs) :-
    (   member(region-RegionVal, Pairs), RegionVal \= ''
    ->  retractall(region(Supplier, _)),
        assert(region(Supplier, RegionVal)),
        (   member(fx_rate-FxVal, Pairs), FxVal \= ''
        ->  to_number(FxVal, Fx),
            retractall(fx_rate(RegionVal, _)),
            assert(fx_rate(RegionVal, Fx))
        ;   true
        ),
        (   member(logistics_cost-LogVal, Pairs), LogVal \= ''
        ->  to_number(LogVal, Log),
            retractall(logistics_cost(RegionVal, _)),
            assert(logistics_cost(RegionVal, Log))
        ;   true
        )
    ;   true
    ).

%! split_cert_list(+Value, -Certs) is det.
%  Splits a semicolon-separated cell into a list of atoms.
split_cert_list(Value, Certs) :-
    atom_string(Value, Str),
    split_string(Str, ";", " \t", Parts),
    findall(C, (member(P, Parts), P \= "", atom_string(C, P)), Certs).

%% ------------------------------------------------------------------ %%
%%  EXAMPLE QUERIES                                                    %%
%% ------------------------------------------------------------------ %%

%% ?- load_csv('sample.csv').
%% ?- load_csv('sample.csv'), run.
%% ?- load_csv('sample.csv', [keep_existing(true)]).
