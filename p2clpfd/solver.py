"""
P2CLPFD Solver — Python wrapper around the Prolog CLP(FD) engine.

Uses janus-swi to embed SWI-Prolog in-process for zero-overhead calls.
"""

from __future__ import annotations

import os.path
import shutil
from pathlib import Path
from typing import Any, Optional

_PL_DIR = Path(__file__).parent / "pl"

_LOADED = False

#: The janus-swi module, bound lazily by :func:`_import_janus` once we have
#: confirmed SWI-Prolog is present. Stays ``None`` until the first Solver runs.
janus = None


class SwiPrologNotFound(RuntimeError):
    """Raised when the SWI-Prolog runtime P2CLPFD depends on is missing.

    P2CLPFD is a Python wrapper around a Prolog engine; ``pip install`` cannot
    install the Prolog runtime itself, so we fail here with instructions rather
    than let ``janus-swi`` raise a cryptic linker/consult error deep in a call.
    """


_INSTALL_HINT = """\
P2CLPFD needs SWI-Prolog (>= 9.0) installed on this system, and it was not found.

Install it, then reinstall p2clpfd if needed:

  macOS         brew install swi-prolog
  Ubuntu/Debian sudo apt install swi-prolog
  conda         conda install -c conda-forge swi-prolog

Verify with:  swipl --version

See https://github.com/ahmed-khalil-hafsi/P2CLPFD/blob/main/INSTALL.md"""


def _import_janus() -> None:
    """Bind the module-level ``janus`` handle, or fail with a clear error.

    ``janus_swi`` links against ``libswipl``; if the executable/runtime is not
    resolvable the import (or first call) raises an opaque error. We front-run
    that with a PATH check and wrap the import so the message is actionable.
    """
    global janus
    if janus is not None:
        return
    if shutil.which("swipl") is None:
        raise SwiPrologNotFound(_INSTALL_HINT)
    try:
        import janus_swi  # noqa: PLC0415 — deferred on purpose
    except Exception as exc:  # linker/runtime resolution failure
        raise SwiPrologNotFound(
            _INSTALL_HINT + f"\n\n(underlying error: {exc})"
        ) from exc
    janus = janus_swi


def _ensure_loaded() -> None:
    """Consult all .pl files exactly once."""
    global _LOADED
    if _LOADED:
        return
    _import_janus()
    for name in ["facts", "solver", "csv_loader", "decompose", "scenarios",
                 "sensitivity", "multiperiod", "json_api", "tracer"]:
        janus.consult(str(_PL_DIR / f"{name}.pl"))
    _LOADED = True


def _overrides_to_prolog(overrides: list[dict]) -> str:
    """Convert Python override dicts to a Prolog list of override terms."""
    parts = []
    for ov in overrides:
        if "set" in ov:
            parts.append(f"set({ov['set']})")
        elif "remove" in ov:
            parts.append(f"remove({ov['remove']})")
        elif "cost_delta" in ov:
            s, p, pct = ov["cost_delta"]
            parts.append(f"cost_delta({s},{p},{pct})")
        elif "demand_delta" in ov:
            p, pct = ov["demand_delta"]
            parts.append(f"demand_delta({p},{pct})")
    return "[" + ",".join(parts) + "]"


def _scenarios_to_prolog(scenarios: list[dict]) -> str:
    """Convert Python scenario dicts to a Prolog list of Name-Overrides pairs."""
    parts = []
    for sc in scenarios:
        name = sc["name"]
        overrides = _overrides_to_prolog(sc.get("overrides", []))
        parts.append(f"{name}-{overrides}")
    return "[" + ",".join(parts) + "]"


#: Fields that carry Prolog's `null` atom when they do not apply — a
#: constraint on a whole supplier has no part, and vice versa.
_NULLABLE_FIELDS = ("supplier", "part")


def _nulls_to_none(value: Any) -> Any:
    """
    Turn Prolog's `null` atom into a real None.

    janus hands atoms across as strings, so an inapplicable field arrives
    as the string "null" — which an agent would happily quote as a
    supplier called "null". Normalise at the boundary rather than making
    every caller remember the quirk.
    """
    if isinstance(value, dict):
        return {
            k: (None if k in _NULLABLE_FIELDS and v == "null" else _nulls_to_none(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_nulls_to_none(v) for v in value]
    return value


class Solver:
    """
    Procurement allocation solver.

    Wraps the P2CLPFD CLP(FD) engine. Each instance shares the same
    Prolog process (embedded via janus-swi).

    Example:
        >>> s = Solver()
        >>> s.load_csv("quotes.csv")
        >>> result = s.solve()
        >>> print(result["tco"])
        19534

        >>> result = s.solve(max_cost=15000)  # None if infeasible
        >>> print(result)
        None

        >>> results = s.compare_scenarios([
        ...     {"name": "baseline", "overrides": []},
        ...     {"name": "no_cap", "overrides": [
        ...         {"remove": "max_global_share(supplier2,_)"}
        ...     ]},
        ... ])
        >>> print(results["deltas"][0]["delta"])
        -5792
    """

    def __init__(self) -> None:
        _ensure_loaded()

    def load_csv(self, path: str) -> dict:
        """
        Load procurement data from a CSV file.

        Clears any previously loaded facts.

        Args:
            path: Path to CSV file with columns:
                part, supplier, demand, unit_cost, capacity, moq,
                share_min, share_max, noncost_adj, fixed_cost,
                min_suppliers, max_suppliers, dual_source,
                global_capacity, global_share_cap

        Raises:
            FileNotFoundError: the path does not exist.
            ValueError: the file exists but could not be parsed.

        A failed load MUST raise rather than return. The Prolog side ships
        demo facts in facts.pl, so a silent failure would leave those
        loaded and every later answer would describe the wrong data.
        """
        if not os.path.isfile(path):
            raise FileNotFoundError(f"no such CSV file: {path}")

        result = janus.query_once(
            'with_output_to(string(_), load_csv(Path))',
            {'Path': path}
        )
        # janus reports goal failure via a falsy result or truth=False
        # depending on version; treat either as a failed load.
        if result is None or result.get("truth") is False:
            raise ValueError(f"could not parse {path} as procurement CSV")
        return {"status": "ok", "path": path}

    def solve(self, max_cost: Optional[int] = None) -> Optional[dict]:
        """
        Find the optimal allocation minimizing TCO.

        Args:
            max_cost: Optional cost ceiling. If provided, only solutions
                      with TCO <= max_cost are considered.

        Returns:
            Dict with keys:
                - "tco": Total cost of ownership (int)
                - "status": "ok"
                - "allocations": List of {part, suppliers} dicts
            Returns None if no feasible allocation exists.
        """
        if max_cost is not None:
            result = janus.query_once(
                'solve_to_json(MaxCost, JSON)',
                {'MaxCost': max_cost}
            )
        else:
            result = janus.query_once(
                'solve_to_json(JSON)'
            )
        json = result.get("JSON")
        if json and json.get("status") == "ok":
            return json
        return None

    def compare_scenarios(self, scenarios: list[dict]) -> dict:
        """
        Compare multiple what-if scenarios against a baseline.

        Args:
            scenarios: List of scenario dicts, each with:
                - "name": Scenario name (str)
                - "overrides": List of override dicts:
                    - {"set": "cost(supplier1,part1,50)"}
                    - {"remove": "dual_source(part1)"}
                    - {"cost_delta": ["supplier2", "part1", 10]}
                    - {"demand_delta": ["part1", 10]}

        Returns:
            Dict with:
                - "results": List of {name, status, tco} dicts
                - "deltas": List of {name, delta, pct} vs first scenario

        Example:
            >>> results = s.compare_scenarios([
            ...     {"name": "baseline", "overrides": []},
            ...     {"name": "no_cap", "overrides": [
            ...         {"remove": "max_global_share(supplier2,_)"}
            ...     ]},
            ... ])
            >>> print(results["results"][1]["tco"])
            13742
        """
        prolog_scenarios = _scenarios_to_prolog(scenarios)
        result = janus.query_once(
            f'compare_scenarios_to_json({prolog_scenarios}, JSON)'
        )
        return result.get("JSON", {"results": [], "deltas": []})

    def validate(self) -> dict:
        """
        Validate the currently loaded facts for common issues.

        Checks tier coverage, MOQ vs capacity, missing demand/cost,
        share range validity, shares that cannot sum to demand,
        capacity below demand, and qualification-gate exclusions.

        Returns:
            Dict with:
                - "status": "error" (unsolvable or wrong), "warning"
                  (suspicious), or "ok"
                - "issue_count": int
                - "issues": [{severity, message, detail}, ...] where
                  message is plain language safe to show a buyer.
        """
        result = janus.query_once('validate_to_json(JSON)')
        return result.get("JSON", {"status": "error", "issues": []})

    def solve_multiperiod(self) -> Optional[dict]:
        """
        Solve across periods with inventory carryover.

        Requires period_demand facts (CSV columns period/period_demand).
        The plan may buy ahead of demand when a later period's capacity
        binds and holding cost is cheaper than the shortfall.

        Returns:
            Dict with "tco" and "plan" (a list of
            {part, period, suppliers, end_inventory}), or None when no
            feasible plan exists.
        """
        result = janus.query_once('solve_multiperiod_to_json(JSON)')
        json = result.get("JSON")
        if json and json.get("status") == "ok":
            return json
        return None

    def sensitivity(self, step: int = 1) -> dict:
        """
        Find binding constraints and their shadow prices.

        A binding constraint is one the optimal allocation sits exactly
        against — it is actively shaping the award. Its shadow price is
        the TCO saving from relaxing it one step.

        Args:
            step: Relaxation size for quantity constraints (capacity,
                  global capacity, MOQ). Percentage and supplier-count
                  constraints always relax by 1.

        Returns:
            Dict with:
                - "status": "ok" or "infeasible"
                - "tco": Baseline optimal TCO
                - "binding_constraints": [{constraint, supplier, part,
                                           used, limit}, ...]
                - "negotiation_levers": [{constraint, supplier, part,
                                          relaxed_limit, new_tco,
                                          savings}, ...] sorted by
                  savings, largest first.
        """
        result = janus.query_once(
            'sensitivity_to_json(Step, JSON)',
            {'Step': step}
        )
        return _nulls_to_none(result.get("JSON", {"status": "error"}))

    def disqualified(self) -> list:
        """
        List (part, supplier) pairs excluded by qualification gates
        (OTIF, lead time, certifications), with reasons.
        """
        result = janus.query_once('disqualified_to_json(JSON)')
        return result.get("JSON", [])

    def rebates(self) -> list:
        """Portfolio rebates in effect: [{supplier, threshold, pct}, ...]."""
        result = janus.query_once('rebates_to_json(JSON)')
        return result.get("JSON", [])

    def advise(self, sensitivity_step: int = 1) -> dict:
        """
        Solve, then interpret the result for a decision-maker.

        Runs the full pipeline — validate, solve, sensitivity, gates —
        and passes it through the judgment layer, which returns a
        one-line verdict plus ranked findings written in plain
        procurement language.

        This is the entry point an agent should reach for first: it
        answers "what should I do?" rather than "what is the optimum?".

        Args:
            sensitivity_step: Relaxation size for quantity constraints
                when computing shadow prices.

        Returns:
            Dict with "verdict", "findings", and "tco". See
            p2clpfd.judgment.advise for the finding schema.
        """
        import time
        from .judgment import advise as _advise

        validation = self.validate()
        started = time.perf_counter()
        solution = self.solve()
        solve_seconds = time.perf_counter() - started
        sensitivity = self.sensitivity(sensitivity_step) if solution else None
        return _advise(
            solution=solution,
            validation=validation,
            sensitivity=sensitivity,
            disqualified=self.disqualified(),
            rebates=self.rebates(),
            solve_seconds=solve_seconds,
            has_increment=self.has_award_grid(),
        )

    def solve_with_grid(self, increment_pct: int) -> Optional[dict]:
        """
        Solve with awards restricted to whole increment_pct% steps.

        The grid is applied for this call only and then removed, so it
        never leaks into a later solve on the same loaded data.

        Args:
            increment_pct: Award step as a percent of each part's demand.
                Must divide 100, or no split can total the full quantity.

        Returns:
            Same shape as solve(), or None when no award fits the grid.
        """
        if 100 % increment_pct != 0:
            raise ValueError(
                f"award step must divide 100; {increment_pct} does not"
            )
        janus.query_once(
            'retractall(share_increment(_)), assertz(share_increment(Pct))',
            {'Pct': increment_pct}
        )
        try:
            return self.solve()
        finally:
            janus.query_once('retractall(share_increment(_))')

    def has_award_grid(self) -> bool:
        """Whether awards are restricted to a percentage grid."""
        result = janus.query_once(
            '( share_increment(_) ; share_increment(_, _) ) -> '
            'Found = true ; Found = false'
        )
        return result.get("Found") == "true"

    def solve_trace(self, max_cost: Optional[int] = None) -> dict:
        """
        Solve and return the full solver trace as NDJSON lines.

        The trace shows domain narrowing and the final optimal allocation.
        Returns a dict with "trace" (string) and "tco" (int or None).
        """
        if max_cost is not None:
            result = janus.query_once(
                'solve_with_trace_captured(MaxCost, Trace, TCO)',
                {'MaxCost': max_cost}
            )
        else:
            result = janus.query_once(
                'solve_with_trace_captured(Trace, TCO)'
            )
        tco = result.get("TCO")
        trace = result.get("Trace", "")
        return {"trace": trace, "tco": tco}
