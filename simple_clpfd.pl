% Constraint Logic Programming

:- use_module(library(clpfd)).	% Finite domain constraints

% Capacities for Part1
capacity(supplier1, part1, 100).
capacity(supplier2, part1, 150).
capacity(supplier3, part1, 80).

cost(supplier1, part1, 100).
cost(supplier2, part1, 10). 
cost(supplier3, part1, 50).


allocate(DemandAllocationPart1,QuantityPart1,TotalCostPart1, MinCost) :-
    
    % Demand Constraint Definitions

    DemandAllocationPart1 = [Q1,Q2,Q3],
    capacity(supplier1,part1,C1), Q1 in 0..C1,
    capacity(supplier2,part1,C2), Q2 in 0..C2,
    capacity(supplier3,part1,C3), Q3 in 0..C3,

    sum(DemandAllocationPart1,#=,QuantityPart1),
    
    
	
    % TCO Optimization
    cost(supplier1,part1,  CostSupplier1),
    cost(supplier2,part1,  CostSupplier2),
    cost(supplier3,part1,  CostSupplier3),
  	TotalCostPart1 #= Q1 * CostSupplier1 + Q2 * CostSupplier2 + Q3 * CostSupplier3,
	
    % Sourcing Strategy Constraints
    
    % Supplier 1 cannot win more than 30%
    10 * Q1 * CostSupplier1 #=< 3 * TotalCostPart1,
    
    % Suppliers 2 and 3 cannot win more than 70% 
    10 * Q2 * CostSupplier2 #=< 7 * TotalCostPart1,
    10 * Q3 * CostSupplier3 #=< 7 * TotalCostPart1,
    
  	TotalCostPart1 #=< MinCost,
    labeling([min(TotalCostPart1)], [Q1,Q2,Q3]).








  






/** <examples> Your example queries go here, e.g.
?- allocate(AllocationBetweenSuppliers,100,TCO,20000),labeling([min(TCO)],AllocationBetweenSuppliers).
*/
