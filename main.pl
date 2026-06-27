%%% P2CLPFD — Entry Point
%%%
%%% Loads facts and solver, provides convenience predicates.
%%%
%%% Usage:
%%%   $ swipl -q -g run -g halt main.pl            % use facts.pl
%%%   $ swipl -q -g "load_and_run('data.csv')" -g halt main.pl
%%%
%%% Or interactively:
%%%   ?- ['main.pl'].
%%%   ?- run.                       % solve + pretty-print + verify
%%%   ?- run(15000).                % solve with cost ceiling
%%%   ?- load_and_run('data.csv').  % load CSV then solve
%%%   ?- solve(A, TCO).             % just solve

:- ['facts.pl'].
:- ['solver.pl'].
:- ['csv_loader.pl'].

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

%! load_and_run(+Path) is det.
%  Load facts from a CSV file, then solve and print.
load_and_run(Path) :-
    load_csv(Path),
    run.

%! load_and_run(+Path, +MaxCost) is det.
%  Load facts from a CSV, then solve with cost ceiling.
load_and_run(Path, MaxCost) :-
    load_csv(Path),
    run(MaxCost).

%% --- Example queries -------------------------------------------------------
%%
%%  ?- run.                                    % solve from facts.pl
%%  ?- run(15000).                             % solve with cost ceiling
%%  ?- load_and_run('sample.csv').             % load CSV then solve
%%  ?- load_and_run('sample.csv', 15000).      % load CSV, solve with ceiling
%%  ?- solve(A, TCO), print_allocation(A, TCO).
