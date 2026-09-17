"""
P2CLPFD Solver — Python wrapper around the Prolog CLP(FD) engine.

Uses janus-swi to embed SWI-Prolog in-process for zero-overhead calls.
"""

from __future__ import annotations

import csv as _csv
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


#: Columns that carry names or truthy flags, not integer economics. Every
#: other column in a P2CLPFD CSV feeds an integer CLP(FD) domain, so a decimal
#: there does not fail at load — it crashes the engine at solve time with an
#: opaque ``Type error: 'integer' expected``. See :func:`_check_integer_economics`.
#: Columns the loader reads as integers; text there cannot mean anything.
_NUMERIC_COLUMNS = frozenset({
    "demand", "unit_cost", "capacity", "moq", "share_min", "share_max",
    "share_increment", "noncost_adj", "fixed_cost", "min_suppliers",
    "max_suppliers", "lead_time", "max_lead_time", "global_capacity",
    "global_share_cap", "otif", "min_otif", "fx_rate", "logistics_cost",
    "rebate_threshold", "rebate_pct", "period", "holding_cost",
    "route_capacity", "route_share_cap",
})

_NON_NUMERIC_COLUMNS = frozenset({
    "part", "supplier", "region", "route",
    "certifications", "required_certs", "dual_source",
})


def _check_integer_economics(path: str) -> None:
    """Reject a CSV that carries decimal values in numeric columns.

    The engine is integer-only (CLP(FD) domains and ``//`` division), so a
    value like ``unit_cost=4.2`` slips through the loader and only surfaces as
    a cryptic Prolog type error once :meth:`Solver.solve` runs. We catch it up
    front and name the offending cell plus the cents workaround.

    Raises:
        ValueError: a numeric column holds a non-integer number.
    """
    try:
        fh = open(path, newline="", encoding="utf-8-sig")
    except OSError:
        return  # let the Prolog loader raise the real parse error
    with fh:
        try:
            lines = [r for r in _csv.reader(fh)]
        except (_csv.Error, UnicodeDecodeError):
            return
    if not lines:
        return
    # Same normalisation as column_key/2 in csv_loader.pl.
    header = ["_".join(h.strip().lower().split()) for h in lines[0]]
    missing = [c for c in ("part", "supplier") if c not in header]
    if missing:
        found = ", ".join(h for h in header if h) or "nothing"
        raise ValueError(
            f"this is not a P2CLPFD sourcing file: it needs "
            f"{' and '.join(missing)} column{'s' if len(missing) > 1 else ''} "
            f"(found: {found})"
        )
    # A spreadsheet export that trims trailing empty cells leaves short
    # rows. The Prolog reader rejects them as "row_arity(8) expected,
    # found 7", which names neither the row nor the fix.
    for number, cells in enumerate(lines[1:], start=2):
        if cells and len(cells) != len(header):
            raise ValueError(
                f"line {number} has {len(cells)} values but the header has "
                f"{len(header)} columns — every row needs one value per "
                f"column (leave a cell empty with a bare comma)"
            )
    rows = [dict(zip(header, cells)) for cells in lines[1:] if cells]
    for row in rows:
        for col, val in row.items():
            if col in _NON_NUMERIC_COLUMNS:
                continue
            val = (val or "").strip()
            if not val:
                continue
            try:
                int(val)
                continue
            except ValueError:
                pass
            who = f"{row.get('supplier', '?')}/{row.get('part', '?')}"
            try:
                float(val)
            except ValueError:
                if col in _NUMERIC_COLUMNS:
                    raise ValueError(
                        f"{col} for {who} is {val!r}, which is not a whole "
                        "number — write it without currency signs, "
                        "thousands separators or units (1000000, not "
                        "1,000,000 or $80)."
                    ) from None
                continue  # a column the loader does not read
            raise ValueError(
                f"{col.strip()} for {who} is {val} — P2CLPFD uses integer "
                "economics; multiply by 100 if you need finer precision "
                "(e.g. quote cents instead of dollars)."
            )


_OVERRIDE_SHAPES = {
    "set": "a fact as text, e.g. \"share(ABC,ti,70,70)\"",
    "remove": "a fact as text, e.g. \"dual_source(ABC)\"",
    "cost_delta": "[supplier, part, percent], e.g. [\"TI\", \"ABC\", 10]",
    "demand_delta": "[part, percent], e.g. [\"ABC\", -5]",
}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_scenarios(scenarios: Any) -> list[dict]:
    """
    Validate scenarios and return them as plain data for Prolog.

    They used to be pasted into the query as text, which broke on any
    capitalised name (Prolog reads ``ABC`` as a variable) and silently
    ignored an override it did not recognise — a scenario that changed
    nothing, reported as if it had. Now they travel as data, names are
    turned into atoms on the Prolog side, and anything malformed is
    rejected here with a message that says what was expected.

    Raises:
        ValueError: a scenario or override is not in a usable shape.
    """
    if not isinstance(scenarios, list):
        raise ValueError("scenarios must be a list of {name, overrides}")
    checked = []
    for i, sc in enumerate(scenarios):
        if not isinstance(sc, dict) or "name" not in sc:
            raise ValueError(f"scenario {i + 1} needs a name")
        name = str(sc["name"])
        overrides = sc.get("overrides") or []
        if not isinstance(overrides, list):
            raise ValueError(f"scenario {name!r}: overrides must be a list")
        clean = []
        for ov in overrides:
            keys = list(ov) if isinstance(ov, dict) else []
            if len(keys) != 1 or keys[0] not in _OVERRIDE_SHAPES:
                raise ValueError(
                    f"scenario {name!r}: {ov!r} is not an override. Use one of "
                    + "; ".join(f"{k}: {v}" for k, v in _OVERRIDE_SHAPES.items())
                )
            kind, value = keys[0], ov[keys[0]]
            if kind in ("set", "remove"):
                ok = isinstance(value, str) and janus.query_once(
                    'catch(term_string(_T, Text), _, fail)', {'Text': value}
                ).get("truth") is not False
            elif kind == "cost_delta":
                ok = (isinstance(value, list) and len(value) == 3
                      and all(isinstance(v, str) for v in value[:2])
                      and _is_int(value[2]))
            else:
                ok = (isinstance(value, list) and len(value) == 2
                      and isinstance(value[0], str) and _is_int(value[1]))
            if not ok:
                raise ValueError(
                    f"scenario {name!r}: {kind} needs {_OVERRIDE_SHAPES[kind]}"
                    f" (percents are whole numbers), got {value!r}"
                )
            clean.append({kind: value})
        checked.append({"name": name, "overrides": clean})
    return checked


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


def _flags_to_bools(value: Any) -> Any:
    """janus hands Prolog's true/false atoms over as strings."""
    if isinstance(value, dict):
        return {
            k: ({"true": True, "false": False}.get(v, v)
                if k in ("qualified", "dual_source") else _flags_to_bools(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_flags_to_bools(v) for v in value]
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
        #: What set_award_grid() did, or None. Mutated in place when the
        #: default grid has to be dropped, so callers holding it see that.
        self.award_grid: Optional[dict] = None

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
            ValueError: the file could not be parsed, or a numeric column
                holds a non-integer value (the engine is integer-only).

        A failed load MUST raise rather than return. The Prolog side ships
        demo facts in facts.pl, so a silent failure would leave those
        loaded and every later answer would describe the wrong data.
        """
        if not os.path.isfile(path):
            raise FileNotFoundError(f"no such CSV file: {path}")

        # Fail on decimal economics before we touch Prolog — otherwise the file
        # loads fine and the type error only surfaces at solve time.
        _check_integer_economics(path)

        result = janus.query_once(
            'with_output_to(string(_), load_csv(Path))',
            {'Path': path}
        )
        # janus reports goal failure via a falsy result or truth=False
        # depending on version; treat either as a failed load.
        if result is None or result.get("truth") is False:
            raise ValueError(f"could not parse {path} as procurement CSV")
        self.award_grid = None  # the load cleared any grid facts
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
        result = self._solve(max_cost)
        grid = self.award_grid
        if (result is None and grid and grid.get("requested")
                and not grid.get("dropped")):
            # The default grid is a speed setting, not one of the buyer's
            # rules. If it alone rules out every award (a 12-13% share band
            # has no 5% level), saying "no award satisfies your rules" would
            # be false. Drop it and search every quantity instead; a grid
            # the file itself sets is a rule, and stays.
            janus.query_once('retractall(share_increment(_))')
            result = self._solve(max_cost)
            if result is None:
                janus.query_once(
                    'assertz(share_increment(Pct))',
                    {'Pct': grid["requested"]}
                )
            else:
                grid["dropped"] = True
        return result

    def _solve(self, max_cost: Optional[int] = None) -> Optional[dict]:
        """One solve against exactly the facts currently loaded."""
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
        checked = _check_scenarios(scenarios)
        report = self._compare(checked)
        grid = self.award_grid
        if (grid and grid.get("requested") and not grid.get("dropped")
                and any(r.get("status") != "ok"
                        for r in report.get("results", []))):
            # Same reasoning as solve(): the default grid must not be the
            # reason a scenario reads "infeasible". Re-run the whole
            # comparison without it so every row is on the same footing.
            janus.query_once('retractall(share_increment(_))')
            exact = self._compare(checked)
            if any(r.get("status") == "ok" for r in exact.get("results", [])):
                grid["dropped"] = True
                return exact
            janus.query_once(
                'assertz(share_increment(Pct))', {'Pct': grid["requested"]}
            )
        return report

    def _compare(self, scenarios: list[dict]) -> dict:
        result = janus.query_once(
            'compare_scenario_dicts_to_json(Scenarios, JSON)',
            {'Scenarios': scenarios}
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

    def rules(self) -> dict:
        """
        The loaded model, read back: what the solver will actually enforce.

        validate() only speaks when something is wrong. This says what was
        understood — with defaults filled in and landed costs computed — so
        a buyer can sign off on the rules that run rather than on their own
        reading of the CSV. A key that is absent means "no limit".

        Returns:
            Dict with "parts" (each with its quotes), "suppliers" and
            "portfolio". Flags are real booleans.
        """
        result = janus.query_once('rules_to_json(JSON)')
        return _flags_to_bools(result.get("JSON", {}))

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
        return self.assess(sensitivity_step=sensitivity_step)["advice"]

    def assess(self, sensitivity_step: int = 1) -> dict:
        """
        Run the whole reading of one decision and keep every piece of it.

        :meth:`advise` answers "what should I do?" and throws the rest away.
        A report has to show the award, the data check and the priced
        constraints alongside the findings — and must not pay for a second
        solve to get them, because on a large model that is minutes.

        Args:
            sensitivity_step: Relaxation size for quantity constraints when
                computing shadow prices.

        Returns:
            Dict with "validation", "solution" (None when infeasible),
            "sensitivity" (None when there is no solution to price),
            "disqualified", "rebates", "solve_seconds", and "advice" —
            the judgment layer's verdict and findings over all of it.
        """
        import time
        from .judgment import advise as _advise

        validation = self.validate()
        started = time.perf_counter()
        solution = self.solve()
        solve_seconds = time.perf_counter() - started
        sensitivity = self.sensitivity(sensitivity_step) if solution else None
        disqualified = self.disqualified()
        rebates = self.rebates()
        return {
            "validation": validation,
            "solution": solution,
            "sensitivity": sensitivity,
            "disqualified": disqualified,
            "rebates": rebates,
            "solve_seconds": solve_seconds,
            "advice": _advise(
                solution=solution,
                validation=validation,
                sensitivity=sensitivity,
                disqualified=disqualified,
                rebates=rebates,
                solve_seconds=solve_seconds,
                has_increment=self.has_award_grid(),
            ),
        }

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
        saved = janus.query_once(
            'findall(_P, share_increment(_P), Saved)'
        ).get("Saved", [])
        janus.query_once(
            'retractall(share_increment(_)), assertz(share_increment(Pct))',
            {'Pct': increment_pct}
        )
        try:
            # _solve, not solve: an explicitly requested grid must never be
            # quietly dropped the way the default one may be.
            return self._solve()
        finally:
            janus.query_once('retractall(share_increment(_))')
            for pct in saved:
                janus.query_once(
                    'assertz(share_increment(Pct))', {'Pct': pct}
                )

    def set_award_grid(self, increment_pct: Optional[int]) -> dict:
        """
        Set the default award grid: whole percentage steps of each part's demand.

        The grid is the single biggest performance lever there is — three
        suppliers with no capacity bounds do not finish over a million units,
        and the same model on a 5% grid solves in a tenth of a second — so the
        CLI turns it on by default. Each award is the step rounded to a whole
        unit (see share_grid/4 in solver.pl), so any step works on any demand.

        A `share_increment` column in the CSV is part of the buyer's rules and
        always wins for its part; this only sets the step for parts without
        one. Passing None or 0 removes the default, not those per-part rules.

        Args:
            increment_pct: Award step as a percent of demand, or None/0 for no
                default grid.

        Returns:
            Dict with "requested" (the default step, or None) and "per_part"
            ({part: pct}) — the steps the file set for itself.

        Raises:
            ValueError: the step does not divide 100.
        """
        if increment_pct and 100 % increment_pct != 0:
            raise ValueError(
                f"award step must divide 100; {increment_pct} does not"
            )
        janus.query_once('retractall(share_increment(_))')
        if increment_pct:
            janus.query_once(
                'assertz(share_increment(Pct))', {'Pct': increment_pct}
            )
        # Template variables are underscore-prefixed on purpose: janus hands
        # back every variable in the query, and an unbound one fails to
        # convert with "Arguments are not sufficiently instantiated".
        result = janus.query_once(
            'findall([_P,_S], share_increment(_P,_S), Rows)'
        )
        return {
            "requested": increment_pct or None,
            "per_part": {
                str(part): int(step)
                for part, step in (result or {}).get("Rows", [])
            },
        }

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
