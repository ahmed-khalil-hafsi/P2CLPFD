# Constraint Logic Programming for Procurement Optimization

This Prolog program is used for allocating a quantity of a certain part across multiple suppliers, with the objective to minimize the total cost of ownership (TCO). It also considers sourcing strategy constraints such as maximum allowed allocation per supplier, minimum and maximum possible allocations per supplier and part, and supplier capacity constraints.

## Getting Started

To run this program, you will need a Prolog interpreter. This script was developed using SWI-Prolog.

### Prerequisites

- [SWI-Prolog](http://www.swi-prolog.org/Download.html)

### Installing

1. Download or clone this repository to your local machine.
2. Open SWI-Prolog.
3. Navigate to the directory containing the Prolog script using the `cd` command in the SWI-Prolog terminal.
4. Load the script by typing `['script.pl'].`, replacing `script.pl` with the filename of your script.

## Using the Program

The main predicate in the program is `global_allocate_with_constraints/2`. Here is how you can use it:

`?- global_allocate_with_constraints(Allocation, MinCost).`

- `Allocation` is a list of quantities to be allocated to each supplier for each part.
- `MinCost` is the maximum allowed total cost. The program will find solutions where total cost is less than or equal to MinCost.

Here's an example query:

`?- global_allocate_with_constraints(Allocation, 20000).`

This will find an allocation of parts across the suppliers, such that the total cost does not exceed 20000 and is as low as possible.

## Supported Features & Reasoning Constraints

The procurement optimization program supports various constraints and features to fine-tune the allocation process:

- **Supplier Capacities and Costs:** You can modify the capacities and costs of suppliers by using the `capacity/3` and `cost/3` facts. The format is `capacity(Supplier, Part, Capacity)` and `cost(Supplier, Part, Cost)`, where `Supplier` and `Part` are atoms, `Capacity` is an integer representing the maximum quantity that the supplier can provide, and `Cost` is the cost per unit from the supplier.

- **Demand:** Specify the demand for each part using `demand/2` (format `demand(Part, Quantity)`).

- **Global Supplier Capacity:** Specify the global capacity of each supplier using `global_capacity/2` (format `global_capacity(Supplier, Capacity)`).

- **Allocation Ranges:** Specify the range of possible allocations for each supplier and part using `can/4` (format `can(Part, Supplier, Min, Max)`). This helps enforce sourcing strategy rules like minimum or maximum allocation to a specific supplier for a part.

## License

This project is licensed under the GPLv3 License.

## Copyright
Copyright (c) 2023 Ahmed Khalil Hafsi