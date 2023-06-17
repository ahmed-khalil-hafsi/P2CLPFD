:- use_module(library(clpfd)).	% Finite domain constraints

% Global Demand for parts

demand(part1,250).

% Who can win what rules

%%% part1
can(part1, supplier1, 0,100).
can(part1, supplier2,30,100).
can(part1, supplier3,0,100).

% Cost Facts

%%% Cost for Part1
% cost(supplier, part, cost, volume bracket)
cost(supplier1, part1, 100, 0).
cost(supplier1, part1, 40, 40). % 60% discount for quantities more than 40.
cost(supplier2, part1, 10, _).  % flat price
cost(supplier3, part1, 50, _). % flat price

%%% Each supplier's allocation must be one of 0, 30 or 70 percent.
possible_allocations([0, 30, 70]).

global_allocate_with_constraints(Allocation, TotalCost, MinCost) :-

    % Demand for each part
    demand(part1, D_P1),
    

    % For each part and supplier, determine the allocation quantity.
    % Note: The allocation for part1 is QX_P1 and for part2 is QX_P2 where X is the supplier number.
    possible_allocations(Allocations),

    % Allocation for Part1
    can(part1, supplier1, Min1_P1, Max1_P1), member(P1_P1, Allocations), P1_P1 in Min1_P1..Max1_P1, Q1_P1 #= P1_P1 * D_P1 // 100,
    can(part1, supplier2, Min2_P1, Max2_P1), member(P2_P1, Allocations), P2_P1 in Min2_P1..Max2_P1, Q2_P1 #= P2_P1 * D_P1 // 100,
    can(part1, supplier3, Min3_P1, Max3_P1), member(P3_P1, Allocations), P3_P1 in Min3_P1..Max3_P1, Q3_P1 #= P3_P1 * D_P1 // 100,
    sum([Q1_P1, Q2_P1, Q3_P1], #=, D_P1),



    Allocation = [[selection(P1_P1,cost(supplier1,part1,Cost1_P1,VolumeBracketSupplier1)), selection(P2_P1,cost(supplier2,part1,Cost2_P1,VolumeBracketSupplier2)), selection(P3_P1,cost(supplier3,part1,Cost3_P1,VolumeBracketSupplier3))]],

    % Cost calculation
    cost(supplier1, part1, Cost1_P1,VolumeBracketSupplier1), 
    cost(supplier2, part1, Cost2_P1,VolumeBracketSupplier2), 
    cost(supplier3, part1, Cost3_P1,VolumeBracketSupplier3),

    Q1_P1 #>= VolumeBracketSupplier1,
    Q2_P1 #>= VolumeBracketSupplier2,
    Q3_P1 #>= VolumeBracketSupplier3,

    TotalCostPart1 #= Q1_P1 * Cost1_P1 + Q2_P1 * Cost2_P1 + Q3_P1 * Cost3_P1,

    TotalCost #= TotalCostPart1,
    
    % Minimize cost
    TotalCost #=< MinCost.