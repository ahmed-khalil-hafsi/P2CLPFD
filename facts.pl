%%% ALLOCATION FACTS

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