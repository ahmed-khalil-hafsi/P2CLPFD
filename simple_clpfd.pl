% Constraint Logic Programming

:- use_module(library(clpfd)).	% Finite domain constraints

% Global Demand for parts

demand(part1,250).
demand(part2,220).

% Who can win what matrix
can(part1, supplier1, 0,100).
can(part1, supplier2,30,100).
can(part1, supplier3,0,100).

can(part2, _,0,100).

% Global Capacity Supplier Constraints

global_capacity(supplier1,5000).
global_capacity(supplier2,1000).
global_capacity(supplier3,5000).

% Global non-cost adjustments 

noncost_adjustment(supplier1,0).
noncost_adjustment(supplier2,3).
noncost_adjustment(supplier3,-5).

% Capacities for Part1
capacity(supplier1, part1, 1000).
capacity(supplier2, part1, 150).
capacity(supplier3, part1, 800).

% Capacities for Part2
capacity(_,part2,inf).

% Cost for Part1
cost(supplier1, part1, 100).
cost(supplier2, part1, 10). 
cost(supplier3, part1, 50).

% Cost for Part 2
cost(supplier1, part2, 100).
cost(supplier2, part2, 30). 
cost(supplier3, part2, 70).

% Each supplier's allocation must be one of 0, 30 or 70 percent.
possible_allocations([0, 30, 70]).

% Reference Allocation Cost
allocate_ref(DemandAllocationPart1,QuantityPart1,TotalCostPart1, MinCost) :-
    
    % Only capacity Constraints are taken into account
    capacity(supplier1,part1,C1), Q1 in 0..C1,
    capacity(supplier2,part1,C2), Q2 in 0..C2,
    capacity(supplier3,part1,C3), Q3 in 0..C3,

    DemandAllocationPart1 = [Q1,Q2,Q3],

    sum(DemandAllocationPart1,#=,QuantityPart1),
    
    % TCO Optimization
    cost(supplier1,part1, CostSupplier1),
    cost(supplier2,part1, CostSupplier2),
    cost(supplier3,part1, CostSupplier3),
  	TotalCostPart1 #= Q1 * CostSupplier1 + Q2 * CostSupplier2 + Q3 * CostSupplier3,
	    
  	TotalCostPart1 #=< MinCost.


% Reference Allocation Cost including non-cost elements
allocate_ref_noncost(DemandAllocationPart1,QuantityPart1,TotalCostPart1, MinCost) :-
    
    % Only capacity Constraints are taken into account
    capacity(supplier1,part1,C1), Q1 in 0..C1,
    capacity(supplier2,part1,C2), Q2 in 0..C2,
    capacity(supplier3,part1,C3), Q3 in 0..C3,

    DemandAllocationPart1 = [Q1,Q2,Q3],

    sum(DemandAllocationPart1,#=,QuantityPart1),
    
    % TCO Optimization
    cost(supplier1,part1, CostSupplier1),
    cost(supplier2,part1, CostSupplier2),
    cost(supplier3,part1, CostSupplier3),
    noncost_adjustment(supplier1,NC1),
    noncost_adjustment(supplier2,NC2),
    noncost_adjustment(supplier3,NC3),

  	TotalCostPart1 #= Q1 * (CostSupplier1 + NC1) + Q2 * (CostSupplier2 + NC2) + Q3 * (CostSupplier3 + NC3),
	    
  	TotalCostPart1 #=< MinCost.

allocate_with_constraints(DemandAllocationPart1,QuantityPart1,TotalCostPart1, MinCost) :-
    
    PercAllocationPart1 = [P1, P2, P3],
    possible_allocations(Allocations),
    member(P1, Allocations),
    member(P2, Allocations),
    member(P3, Allocations),
    % Ensure that the total allocation percentages add up to 100.
    sum(PercAllocationPart1, #=, 100),
    
    % Demand Constraint Definitions
    
    % Convert percentage allocations into actual quantities.
    Q1 #= P1 * QuantityPart1 // 100,
    Q2 #= P2 * QuantityPart1 // 100,
    Q3 #= P3 * QuantityPart1 // 100,
    DemandAllocationPart1 = [Q1, Q2, Q3],
    
    % Sourcing Strategy Constraints
    
    % Supplier 1 cannot win more than 30% of total volume
    10 * Q1  #=< 3 * QuantityPart1,
    
    % Suppliers 2 and 3 cannot win more than 70% of total volume
    10 * Q2  #=< 7 * QuantityPart1,
    % Supplier 2 must have at least 30% of volume
    10 * Q2 #>= 3 * QuantityPart1,

    % Supplier 3 can win all
    10 * Q3  #=< 10 * QuantityPart1,
	
    % Capacity Constraints
    capacity(supplier1,part1,C1), Q1 in 0..C1,
    capacity(supplier2,part1,C2), Q2 in 0..C2,
    capacity(supplier3,part1,C3), Q3 in 0..C3,

    sum(DemandAllocationPart1,#=,QuantityPart1),
    
    % TCO Optimization
    cost(supplier1,part1, CostSupplier1),
    cost(supplier2,part1, CostSupplier2),
    cost(supplier3,part1, CostSupplier3),
  	TotalCostPart1 #= Q1 * CostSupplier1 + Q2 * CostSupplier2 + Q3 * CostSupplier3,
	

    
  	TotalCostPart1 #=< MinCost.


% Allocate for all parts
global_allocate_with_constraints(Allocation, TotalCost, MinCost) :-
    % Demand for each part
    demand(part1, D_P1),
    demand(part2, D_P2),

    % For each part and supplier, determine the allocation quantity.
    % Note: The allocation for part1 is QX_P1 and for part2 is QX_P2 where X is the supplier number.
    possible_allocations(Allocations),
    Allocations = [0, 30, 70],

    % Allocation for Part1
    member(P1_P1, Allocations), Q1_P1 #= P1_P1 * D_P1 // 100,
    member(P2_P1, Allocations), Q2_P1 #= P2_P1 * D_P1 // 100,
    member(P3_P1, Allocations), Q3_P1 #= P3_P1 * D_P1 // 100,
    sum([Q1_P1, Q2_P1, Q3_P1], #=, D_P1),

    % Allocation for Part2
    member(P1_P2, Allocations), Q1_P2 #= P1_P2 * D_P2 // 100,
    member(P2_P2, Allocations), Q2_P2 #= P2_P2 * D_P2 // 100,
    member(P3_P2, Allocations), Q3_P2 #= P3_P2 * D_P2 // 100,
    sum([Q1_P2, Q2_P2, Q3_P2], #=, D_P2),

    % Global capacity constraints
    global_capacity(supplier1, GC1), Q1 #= Q1_P1 + Q1_P2, Q1 in 0..GC1,
    global_capacity(supplier2, GC2), Q2 #= Q2_P1 + Q2_P2, Q2 in 0..GC2,
    global_capacity(supplier3, GC3), Q3 #= Q3_P1 + Q3_P2, Q3 in 0..GC3,

    Allocation = [[Q1_P1, Q2_P1, Q3_P1], [Q1_P2, Q2_P2, Q3_P2]],

    % Cost calculation
    cost(supplier1, part1, Cost1_P1), cost(supplier1, part2, Cost1_P2),
    cost(supplier2, part1, Cost2_P1), cost(supplier2, part2, Cost2_P2),
    cost(supplier3, part1, Cost3_P1), cost(supplier3, part2, Cost3_P2),
    TotalCostPart1 #= Q1_P1 * Cost1_P1 + Q2_P1 * Cost2_P1 + Q3_P1 * Cost3_P1,
    TotalCostPart2 #= Q1_P2 * Cost1_P2 + Q2_P2 * Cost2_P2 + Q3_P2 * Cost3_P2,
    TotalCost #= TotalCostPart1 + TotalCostPart2,
    
    % Minimize cost
    TotalCost #=< MinCost.






  






/** <examples> Your example queries go here, e.g.
?- allocate(AllocationBetweenSuppliers,100,TCO,20000),labeling([min(TCO)],AllocationBetweenSuppliers).
*/
