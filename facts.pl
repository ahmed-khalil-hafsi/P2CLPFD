%%% PROCUREMENT ALLOCATION FACTS
%%%
%%% Declaring optional predicates as dynamic so the solver can check them
%%% gracefully even when no facts are present.

:- dynamic min_suppliers/2.
:- dynamic max_suppliers/2.
:- dynamic dual_source/1.
:- dynamic max_global_share/2.
:- dynamic fixed_cost/3.
:- dynamic rebate/3.
%%%
%%% Schema (all quantities are absolute integers, not percentages):
%%%
%%%   demand(Part, Quantity).
%%%       Total quantity of Part that must be sourced across all suppliers.
%%%
%%%   cost(Supplier, Part, UnitCost).
%%%       Unit price. REQUIRED for any (Supplier, Part) pair that may be
%%%       allocated. A pair with no cost/3 fact is non-allocatable (forced 0).
%%%
%%%   capacity(Supplier, Part, MaxQty).          % optional
%%%       Per-part-supplier maximum. Absent => unlimited for that pair.
%%%
%%%   moq(Supplier, Part, MinQty).               % optional
%%%       Minimum order quantity for the pair. Absent => 0.
%%%
%%%   share(Part, Supplier, MinPct, MaxPct).     % optional
%%%       Sourcing-strategy bounds as a PERCENTAGE of the part's demand
%%%       (0..100). Absent => 0..100 (no strategy restriction).
%%%
%%%   global_capacity(Supplier, MaxQty).         % optional
%%%       Total a supplier may win across ALL parts. Absent => unlimited.
%%%
%%%   noncost_adjustment(Supplier, Adj).         % optional
%%%       Per-unit additive adjustment to unit cost when computing TCO
%%%       (e.g. quality, logistics, risk premium; may be negative). Absent => 0.
%%%
%%%   price_tier(Supplier, Part, MinQty, MaxQty, UnitCost).   % optional
%%%       Volume-based tiered pricing. Tiers for a given (Supplier, Part)
%%%       pair must be non-overlapping and collectively cover 0..sup.
%%%       Use 'sup' for an unbounded MaxQty. The solver selects the tier
%%%       whose [MinQty, MaxQty] range contains the allocated quantity Q
%%%       and applies that tier's UnitCost.
%%%       If no price_tier/5 facts exist for a pair, falls back to cost/3.
%%%
%%%   fixed_cost(Supplier, Part, Amount).             % optional
%%%       One-time charge (NRE / tooling / setup) incurred when Q > 0.
%%%       Added to TCO as B * Amount where B is a 0/1 active variable.
%%%       Absent => 0.
%%%
%%%   min_suppliers(Part, N).                         % optional
%%%       Part must be sourced from at least N suppliers (active pairs).
%%%       Absent => no lower bound on supplier count.
%%%
%%%   max_suppliers(Part, N).                         % optional
%%%       Part may be sourced from at most N suppliers.
%%%       Absent => no upper bound on supplier count.
%%%
%%%   dual_source(Part).                              % optional
%%%       Shorthand for min_suppliers(Part, 2).
%%%       If both min_suppliers and dual_source exist, the larger is used.
%%%
%%%   max_global_share(Supplier, Pct).                % optional
%%%       Supplier's total across all parts may not exceed Pct% of total
%%%       demand across all parts. Absent => unrestricted.

% --- Parts and demand --------------------------------------------------------

demand(part1, 250).
demand(part2, 220).

% --- Suppliers (derived automatically from cost/3, listed here for reference)

% supplier1, supplier2, supplier3

% --- Unit costs (flat pricing — fallback when no price_tier/5 exists) --------

cost(supplier1, part1, 100).
cost(supplier2, part1, 10).
cost(supplier3, part1, 50).

cost(supplier1, part2, 100).
cost(supplier2, part2, 30).
cost(supplier3, part2, 70).

% --- Volume-based tiered pricing --------------------------------------------
%   price_tier(Supplier, Part, MinQty, MaxQty, UnitCost)
%   Overrides cost/3 for that pair when present.

% supplier1 / part1: 60% volume discount above 40 units
price_tier(supplier1, part1,   0,  39, 100).
price_tier(supplier1, part1,  40, sup,  40).

% supplier2 and supplier3 on part1: flat pricing (no price_tier/5 => cost/3)
% supplier1, supplier2, supplier3 on part2: flat pricing

% --- Per-part-supplier capacity (absent = unlimited) ------------------------

capacity(supplier1, part1, 1000).
capacity(supplier2, part1, 150).
capacity(supplier3, part1, 800).

% part2: no per-pair capacity facts => unlimited for every supplier.

% --- Minimum order quantities ------------------------------------------------

moq(supplier2, part1, 75).

% --- Sourcing strategy (percentage of part demand) ---------------------------

share(part1, supplier1, 0, 30).    % supplier1 may win at most 30% of part1
share(part1, supplier2, 30, 70).   % supplier2 must win 30%..70% of part1
share(part1, supplier3, 0, 100).   % supplier3 unrestricted on part1

% part2: no share facts => no strategy restriction.

% --- Global supplier capacity (total across all parts) -----------------------

global_capacity(supplier1, 5000).
global_capacity(supplier2, 1000).
global_capacity(supplier3, 5000).

% --- Non-cost TCO adjustments (per unit) -------------------------------------

noncost_adjustment(supplier1, 0).
noncost_adjustment(supplier2, 3).
noncost_adjustment(supplier3, -5).

% --- Fixed costs (NRE / tooling / setup) ------------------------------------
%   One-time charge when Q > 0 for that pair.

fixed_cost(supplier1, part1, 2000).   % $2000 tooling to use supplier1 for part1

% --- Risk & sourcing rules --------------------------------------------------
%   min_suppliers: must use at least N suppliers (dual-source or more)
%   max_suppliers: cap on supply-base size for a part
%   dual_source:   shorthand for min_suppliers(Part, 2)

dual_source(part1).                   % part1 must have at least 2 suppliers
max_suppliers(part2, 2).             % part2 at most 2 suppliers

% --- Global share cap -------------------------------------------------------
%   No supplier may exceed Pct% of total demand across all parts.

max_global_share(supplier2, 40).     % supplier2 capped at 40% of total volume

% --- Rebates (portfolio-level volume discounts) --------------------------------
%   If total volume across all parts exceeds Threshold, get DiscountPct% off
%   the ENTIRE supplier spend (retrospective, cross-part).

rebate(supplier2, 150, 5).          % supplier2: 5% off if total volume >= 150
