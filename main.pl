%%% P2CLPFD — Entry Point
%%%
%%% Loads facts and solver, provides convenience predicates.
%%%
%%% Usage:
%%%   $ swipl -q -g run -g halt main.pl
%%%
%%% Or interactively:
%%%   ?- ['main.pl'].
%%%   ?- run.                       % solve + pretty-print + verify
%%%   ?- solve(A, TCO).             % just solve
%%%   ?- solve(A, TCO, 15000).      % solve with cost ceiling
%%%   ?- solve(A, TCO), print_allocation(A, TCO).

:- ['facts.pl'].
:- ['solver.pl'].

%! run is det.
%  Solve the current facts, print the optimal allocation, and verify it.
run :-
    (   solve(Allocation, TCO)
    ->  print_allocation(Allocation, TCO)
    ;   format('~nNo feasible allocation exists for the current facts.~n',
               [])
    ).

%! run(+MaxCost) is det.
%  As run/0 but with a cost ceiling.
run(MaxCost) :-
    (   solve(Allocation, TCO, MaxCost)
    ->  print_allocation(Allocation, TCO)
    ;   format('~nNo feasible allocation with TCO =< ~w.~n', [MaxCost])
    ).

%% --- Example queries -------------------------------------------------------
%%
%%  ?- run.
%%  ?- run(15000).
%%  ?- solve(A, TCO), print_allocation(A, TCO).
%%  ?- findall(TCO-A, solve(A, TCO), All),   % enumerate solutions
%%     keysort(All, Sorted), writeln(Sorted).
