# Constraint Logic Programming for Procurement Optimization

This Prolog program is used for allocating a quantity of a certain part across multiple suppliers, with the objective to minimize the total cost of ownership (TCO). It also considers sourcing strategy constraints such as maximum allowed allocation per supplier.

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

The main predicate in the program is `allocate/4`. Here is how you can use it:

`?- allocate(Allocation, Quantity, TCO, MaxCost).`


- `Allocation` is a list of quantities to be allocated to each supplier.
- `Quantity` is the total quantity that needs to be allocated.
- `TCO` is the total cost of ownership, which the program tries to minimize.
- `MaxCost` is the maximum allowed cost. The program will find solutions where TCO is less than or equal to MaxCost.

Here's an example query:

`?- allocate(Allocation, 100, TCO, 20000).`


This will find an allocation of 100 units across the suppliers, such that the total cost does not exceed 20000 and is as low as possible.

## Modifying the Program

You can modify the capacities and costs of suppliers by changing the `capacity/3` and `cost/3` facts in the program. The format is `capacity(Supplier, Part, Capacity)` and `cost(Supplier, Part, Cost)`, where `Supplier` and `Part` are atoms, `Capacity` is an integer representing the maximum quantity that the supplier can provide, and `Cost` is the cost per unit from the supplier.

## License

This project is licensed under the GPLv3 License.

