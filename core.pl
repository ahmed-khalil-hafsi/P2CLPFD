:- use_module(library(clpfd)).

optimize(Costs, Demands, M, X, Allocations, TotalCost) :-
    length(Costs, N),
    length(Costs, S),  % Assuming that the number of suppliers is equal to the length of the cost matrix row
    create_matrix(N, S, Allocations),
    meet_demands(N, S, Allocations, Demands),
    all_suppliers(N, M, Allocations),
    limit_suppliers(N, S, Allocations, X),
    total_cost(N, S, Allocations, Costs, TotalCost),
    flatten(Allocations, Vars),
    labeling([min(TotalCost)], Vars).

create_matrix(0, _, []).
create_matrix(N, S, [Row|Matrix]) :-
    length(Row, S),
    Row ins 0..sup,  % Ensuring that each allocation quantity is in the domain 0 to sup (sup is the maximum integer in the implementation)
    N1 is N - 1,
    create_matrix(N1, S, Matrix).

all_suppliers(_, 0, _, _).
all_suppliers(N, S, M, Allocations) :-
    get_column(S, Allocations, Column),
    foreach((member(Q, Column), Q #> 0), (Q #>= M)),
    S1 is S - 1,
    all_suppliers(N, S1, M, Allocations).

limit_suppliers(_, 0, _, _).
limit_suppliers(N, S, Allocations, X) :-
    get_column(S, Allocations, Column),
    sum(Column, #=<, X),
    S1 is S - 1,
    limit_suppliers(N, S1, Allocations, X).


meet_demands(0, _, _, _).
meet_demands(N, S, Allocations, Demands) :-
    get_row(N, Allocations, Row),
    nth1(N, Demands, Demand),
    sum(Row, #=, Demand),
    N1 is N - 1,
    meet_demands(N1, S, Allocations, Demands).

get_row(N, Matrix, Row) :-
    nth1(N, Matrix, Row).


calc_cost(0, _, _, TotalCost, TotalCost).
calc_cost(S, Allocations, Costs, AccumulatedCost, TotalCost) :-
    S > 0,
    get_column(S, Allocations, Column),
    nth1(S, Costs, CostColumn),
    calculate_row_cost(Column, CostColumn, 0, Cost),
    NewAccumulatedCost #= AccumulatedCost + Cost,
    S1 is S - 1,
    calc_cost(S1, Allocations, Costs, NewAccumulatedCost, TotalCost).

calculate_row_cost([], [], Cost, Cost).
calculate_row_cost([Alloc|AllocRest], [Cost|CostRest], Acc, TotalCost) :-
    NewAcc #= Acc + Alloc * Cost,
    calculate_row_cost(AllocRest, CostRest, NewAcc, TotalCost).

get_column(_, [], []).
get_column(N, [Row|Matrix], [Elem|Column]) :-
    nth1(N, Row, Elem),
    get_column(N, Matrix, Column).
