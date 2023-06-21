% Supplier Allocation Using CLP(FD)

:- use_module(library(clpfd)).	% Finite domain constraints

% Global Demand for parts

demand(part1,250).
demand(part2,220).

% Who can win what rules

%%% part1
can(part1, supplier1, 0,100).
can(part1, supplier2,30,100).
can(part1, supplier3,0,100).

%%% part2
can(part2, _,0,100).

% Volume Constraints

%%% Global Capacity Supplier Constraints

global_capacity(supplier1,5000).
global_capacity(supplier2,1000).
global_capacity(supplier3,5000).

%%% Global non-cost adjustments 

noncost_adjustment(supplier1,0).
noncost_adjustment(supplier2,3).
noncost_adjustment(supplier3,-5).

%%% Capacities for Part1
capacity(supplier1, part1, 1000).
capacity(supplier2, part1, 150).
capacity(supplier3, part1, 800).

%%% Capacities for Part2
capacity(_,part2,inf).

% Cost Facts

%%% Cost for Part1
cost(supplier1, part1, 100).
cost(supplier2, part1, 10). 
cost(supplier3, part1, 50).

%%% Cost for Part 2
cost(supplier1, part2, 100).
cost(supplier2, part2, 30). 
cost(supplier3, part2, 70).

%%% Each supplier's allocation must be one of 0, 30 or 70 percent.
possible_allocations([0, 30, 70]).

global_allocate_with_constraints(Parts,Suppliers,Allocation, TotalCost, MaxCost) :-


    % Calculate allocations and total cost for each part
    calculate_allocation(Parts, Suppliers, Allocation, TotalCosts),

    % Calculate the total cost
    sum(TotalCosts, #=, TotalCost),
    
    % Minimize cost
    TotalCost #=< MaxCost,

    % Global capacity constraints
    check_global_capacity(Suppliers, Allocation).

calculate_allocation([], _, [], []).
calculate_allocation([Part|RestParts], Suppliers, [PartAllocations|RestAllocation], [PartCost|RestCosts]) :-
    calculate_supplier_allocation(Part, Suppliers, PartAllocations, PartCost),
    calculate_allocation(RestParts, Suppliers, RestAllocation, RestCosts).

calculate_supplier_allocation(_, [], [], 0).
calculate_supplier_allocation(Part, [Supplier|RestSuppliers], [Q|RestQ], TotalCost) :-
    % For each part and supplier, determine the allocation quantity.
    possible_allocations(Allocations),
    
    % Allocation for Part
    can(Part, Supplier, Min, Max),
    member(P, Allocations),
    P in Min..Max,
    Q #= P * demand(Part) // 100,

    % Calculate the cost
    cost(Supplier, Part, CostPart),
    PartCost #= Q * CostPart,

    % Calculate the allocation and cost for the rest suppliers
    calculate_supplier_allocation(Part, RestSuppliers, RestQ, RestCosts),
    
    % Calculate the total cost for this part
    TotalCost #= PartCost + RestCosts.

check_global_capacity([], _).
check_global_capacity([Supplier|RestSuppliers], Allocations) :-
    % Get allocations for this supplier from all parts
    get_supplier_allocations(Supplier, Allocations, SupplierAllocations),
    
    % Global capacity constraint
    sum(SupplierAllocations, #=, TotalQ),
    global_capacity(Supplier, GC),
    TotalQ in 0..GC,

    % Check the rest suppliers
    check_global_capacity(RestSuppliers, Allocations).

get_supplier_allocations(_, [], []).
get_supplier_allocations(Supplier, [PartAllocations|RestAllocations], [Q|RestQ]) :-
    nth1(Index, Suppliers, Supplier),
    nth1(Index, PartAllocations, Q),
    get_supplier_allocations(Supplier, RestAllocations, RestQ).
