% Supplier Selection Framework

:- use_module(library(clpfd)).	% Finite domain constraints

% Capacities for Part1
capacity(supplier1, part1, 100).
capacity(supplier2, part1, 150).
capacity(supplier3, part1, 80).

% costs for part 1
cost(supplier1, part1, 100).
cost(supplier2, part1, 10). 
cost(supplier3, part1, 50).

% We are only interested in discrete allocations that are practical to implement
possible_allocations([0, 20, 30, 40, 60, 70, 80, 100]).

allocate(DemandAllocationPart1,QuantityPart1,TotalCostPart1, MinCost) :-
    
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
	
    % Sourcing Strategy Constraints
    
    % Supplier 1 cannot win more than 30% of total volume
    10 * Q1  #=< 3 * QuantityPart1,
    
    % Suppliers 2 and 3 cannot win more than 70% of total volume
    10 * Q2  #=< 7 * QuantityPart1,
    10 * Q3  #=< 7 * QuantityPart1,
    
  	TotalCostPart1 #=< MinCost,

    % find the solutions while optimzing TCO
    labeling([min(TotalCostPart1)], [Q1,Q2,Q3]).








  






/** <examples> Your example queries go here, e.g.
?- allocate(AllocationBetweenSuppliers,100,TCO,20000),labeling([min(TCO)],AllocationBetweenSuppliers).
*/
