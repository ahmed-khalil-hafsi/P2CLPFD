"""
P2CLPFD Judgment Layer — turns solver output into decisions an agent can act on.

The CLP(FD) engine answers "what is the cheapest legal award?". That is a
mathematical fact, and it is never wrong. But an agent handed a bare TCO and
a list of quantities cannot tell whether the number is trustworthy, whether
the buyer is about to concentrate 80% of spend on one supplier, or which of
twelve constraints is the one worth a phone call.

This module supplies that reading. Every finding carries:

    kind        machine-readable category, stable across versions
    severity    "critical" | "warning" | "opportunity" | "info"
    say_to_user one sentence in plain procurement language, no jargon
    detail      the numbers behind it, for an agent that wants to dig

Design rules:

  * Never restate the math. The solver already proved optimality; the
    judgment layer only comments on what the optimum implies.
  * Thresholds are named constants, not magic numbers, and every one of
    them is a business convention rather than a mathematical truth.
  * Findings are ordered by how much they should change what the agent
    does next, not by how interesting they are.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# ── thresholds ────────────────────────────────────────────────────────────
#
# These encode procurement convention, not mathematics. They are the knobs
# a category manager would argue about; keeping them named and together
# makes that argument easy to have.

SLOW_SOLVE_SECONDS = 5.0      # past this, suggest an award grid
SINGLE_SOURCE_SHARE = 100.0   # % of a part from one supplier = single-sourced
HIGH_CONCENTRATION = 60.0     # % of total spend with one supplier = concentrated
REBATE_NEAR_MISS = 0.15       # within 15% of a rebate threshold is worth chasing
MATERIAL_SAVING = 0.005       # a lever worth <0.5% of TCO is noise
LARGE_SAVING = 0.02           # a lever worth >2% of TCO leads the agenda


@dataclass
class Finding:
    """One thing the agent should know about this award."""

    kind: str
    severity: str
    say_to_user: str
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


_SEVERITY_ORDER = {"critical": 0, "warning": 1, "opportunity": 2, "info": 3}


def _money(n: float | int) -> str:
    """Format a cost the way a buyer writes it."""
    return f"{round(n):,}"


def _pct(part: float, whole: float) -> float:
    return 0.0 if not whole else round(part * 100 / whole, 1)


# ── individual assessments ────────────────────────────────────────────────


def assess_data_quality(validation: dict) -> list[Finding]:
    """
    Judge whether the input data is fit to make a decision on.

    An error-level issue means the answer is unsafe to quote, so this
    outranks everything else the layer can say.
    """
    findings: list[Finding] = []
    issues = validation.get("issues", [])
    errors = [i for i in issues if i.get("severity") == "error"]
    warnings = [i for i in issues if i.get("severity") == "warning"]

    if errors:
        findings.append(Finding(
            kind="data_unfit",
            severity="critical",
            say_to_user=(
                f"Fix the data before trusting this result — "
                f"{len(errors)} problem{'s' if len(errors) != 1 else ''} "
                f"would make the answer wrong or impossible: "
                + errors[0]["message"]
            ),
            detail={"errors": errors},
        ))
    if warnings:
        findings.append(Finding(
            kind="data_suspect",
            severity="warning",
            say_to_user=(
                f"{len(warnings)} thing{'s' if len(warnings) != 1 else ''} "
                f"in the data look unintended: " + warnings[0]["message"]
            ),
            detail={"warnings": warnings},
        ))
    return findings


def assess_infeasibility(validation: dict) -> list[Finding]:
    """
    Explain WHY there is no answer, rather than reporting that there isn't one.

    Infeasibility is the case where an agent most needs steering: the
    solver says "no" and the buyer needs to know which rule to relax.
    """
    issues = validation.get("issues", [])
    blocking = [
        i for i in issues
        if i.get("severity") == "error"
        and any(k in i.get("detail", "") for k in (
            "capacity_below_demand",
            "all_suppliers_disqualified",
            "share_minimums_exceed_demand",
            "share_maximums_below_demand",
            "moq_over_capacity",
        ))
    ]

    if blocking:
        return [Finding(
            kind="infeasible_explained",
            severity="critical",
            say_to_user=(
                "No award is possible with these rules. "
                + blocking[0]["message"]
                + " Relax that first."
            ),
            detail={"blocking_issues": blocking},
        )]

    return [Finding(
        kind="infeasible_unexplained",
        severity="critical",
        say_to_user=(
            "No award satisfies every rule at once, and no single rule is "
            "obviously at fault — the conflict is between rules rather than "
            "in any one of them. Try relaxing the tightest share or "
            "supplier-count requirement and re-solving."
        ),
        detail={},
    )]


def assess_concentration(solution: dict) -> list[Finding]:
    """
    Flag supply-risk concentration the cost objective is blind to.

    Cost minimization has no opinion about putting every unit with one
    supplier. A buyer does.
    """
    findings: list[Finding] = []
    allocations = solution.get("allocations", [])

    spend_by_supplier: dict[str, float] = {}
    total_spend = 0.0
    for part in allocations:
        for s in part.get("suppliers", []):
            amount = s.get("subtotal", 0) + s.get("fixed_cost", 0)
            spend_by_supplier[s["supplier"]] = (
                spend_by_supplier.get(s["supplier"], 0.0) + amount
            )
            total_spend += amount

    # Single-sourced parts.
    for part in allocations:
        active = [s for s in part.get("suppliers", []) if s.get("qty", 0) > 0]
        if len(active) == 1:
            findings.append(Finding(
                kind="single_source",
                severity="warning",
                say_to_user=(
                    f"All of {part['part']} comes from {active[0]['supplier']} — "
                    f"if they have a problem, you have no second source."
                ),
                detail={
                    "part": part["part"],
                    "supplier": active[0]["supplier"],
                    "qty": active[0]["qty"],
                },
            ))

    # Portfolio concentration.
    for supplier, spend in sorted(
        spend_by_supplier.items(), key=lambda kv: -kv[1]
    ):
        share = _pct(spend, total_spend)
        if share >= HIGH_CONCENTRATION:
            findings.append(Finding(
                kind="spend_concentration",
                severity="warning",
                say_to_user=(
                    f"Spend is concentrated — {supplier} would hold {share}% of "
                    f"it ({_money(spend)}), which is a lot of leverage to give "
                    f"one supplier."
                ),
                detail={
                    "supplier": supplier,
                    "spend": round(spend),
                    "share_pct": share,
                },
            ))
    return findings


def assess_negotiation_levers(sensitivity: dict) -> list[Finding]:
    """
    Rank the binding constraints into a negotiation agenda.

    A binding constraint with a large shadow price is a phone call worth
    making. A binding constraint worth nothing is worth knowing about too,
    because it tells the buyer NOT to spend effort there.
    """
    findings: list[Finding] = []
    tco = sensitivity.get("tco") or 0
    levers = sensitivity.get("negotiation_levers", [])
    if not tco:
        return findings

    worthwhile = [l for l in levers if l.get("savings", 0) > tco * MATERIAL_SAVING]
    worthless = [l for l in levers if l.get("savings", 0) == 0]

    for lever in worthwhile:
        savings = lever["savings"]
        share = _pct(savings, tco)
        severity = "opportunity" if savings >= tco * LARGE_SAVING else "info"
        findings.append(Finding(
            kind="negotiation_lever",
            severity=severity,
            say_to_user=_lever_sentence(lever, savings, share),
            detail=lever,
        ))

    if worthless and not worthwhile:
        names = ", ".join(_lever_name(l) for l in worthless[:3])
        findings.append(Finding(
            kind="no_levers",
            severity="info",
            say_to_user=(
                f"Nothing is worth negotiating on the constraint side — "
                f"relaxing {names} would not lower the cost at all. "
                f"To save money here you need better prices, not looser rules."
            ),
            detail={"zero_value_constraints": worthless},
        ))
    return findings


def _lever_name(lever: dict) -> str:
    """Human name for a constraint, e.g. 'supplier2's share cap'."""
    kind = lever.get("constraint", "")
    supplier = lever.get("supplier")
    part = lever.get("part")
    supplier = None if supplier in (None, "null") else supplier
    part = None if part in (None, "null") else part

    names = {
        "capacity": f"{supplier}'s capacity on {part}",
        "global_capacity": f"{supplier}'s total capacity",
        "max_global_share": f"the share cap on {supplier}",
        "share_max": f"{supplier}'s maximum share of {part}",
        "share_min": f"{supplier}'s minimum share of {part}",
        "moq": f"{supplier}'s minimum order quantity on {part}",
        "min_suppliers": f"the minimum supplier count on {part}",
        "max_suppliers": f"the maximum supplier count on {part}",
    }
    return names.get(kind, kind)


def _lever_sentence(lever: dict, savings: int, share: float) -> str:
    name = _lever_name(lever)
    new_limit = lever.get("relaxed_limit")
    return (
        f"Loosening {name} to {new_limit} would save {_money(savings)} "
        f"({share}% of total cost) — this is where negotiation pays."
    )


def assess_rebate_proximity(solution: dict, rebates: list[dict]) -> list[Finding]:
    """
    Spot volume that is nearly at a rebate threshold.

    The solver only sees rebates it can actually reach. When an award
    lands just short of one, that gap is a commercial conversation, not
    a modelling error.
    """
    findings: list[Finding] = []
    if not rebates:
        return findings

    qty_by_supplier: dict[str, int] = {}
    for part in solution.get("allocations", []):
        for s in part.get("suppliers", []):
            qty_by_supplier[s["supplier"]] = (
                qty_by_supplier.get(s["supplier"], 0) + s.get("qty", 0)
            )

    for rebate in rebates:
        supplier = rebate["supplier"]
        threshold = rebate["threshold"]
        pct = rebate["pct"]
        actual = qty_by_supplier.get(supplier, 0)
        if actual >= threshold or actual == 0:
            continue
        gap = threshold - actual
        if gap <= threshold * REBATE_NEAR_MISS:
            findings.append(Finding(
                kind="rebate_near_miss",
                severity="opportunity",
                say_to_user=(
                    f"You are {gap} units short of {supplier}'s {pct}% rebate "
                    f"(needs {threshold}, award has {actual}). Moving that "
                    f"volume across may pay for itself."
                ),
                detail={
                    "supplier": supplier,
                    "threshold": threshold,
                    "awarded": actual,
                    "gap": gap,
                    "rebate_pct": pct,
                },
            ))
    return findings


def assess_award_granularity(
    solve_seconds: Optional[float], has_increment: bool
) -> list[Finding]:
    """
    Offer the award grid when a slow solve has no granularity set.

    Quantities are free by default, so the solver must prove no better
    split exists across every whole unit — work that grows with the order
    quantity. Restricting awards to whole percentage steps collapses that
    to a couple of dozen options and makes solve time independent of
    quantity. Most buyers award in round numbers anyway, so the
    restriction usually costs nothing.

    Only raised when the solve was actually slow: telling someone to
    change their model when it already answers instantly is noise.
    """
    if has_increment or solve_seconds is None:
        return []
    if solve_seconds < SLOW_SOLVE_SECONDS:
        return []

    return [Finding(
        kind="suggest_award_grid",
        severity="opportunity",
        say_to_user=(
            f"That took {solve_seconds:.0f} seconds because awards can be any "
            f"quantity at all. If you are willing to award in round steps — "
            f"5% at a time, so splits look like 60/30/10 — it will run almost "
            f"instantly, and usually for the same money."
        ),
        detail={
            "solve_seconds": round(solve_seconds, 2),
            "setting": "share_increment",
            "suggested_pct": 5,
            "usable_steps": [1, 2, 4, 5, 10, 20, 25, 50],
            "caveat": (
                "Costs a little when the best split falls between steps, "
                "and minimum order quantities and price breaks do not "
                "follow the steps."
            ),
        },
    )]


def assess_exclusions(disqualified: list[dict]) -> list[Finding]:
    """
    Surface suppliers the gates removed.

    A buyer looking at an award will ask "why isn't X in here?". The
    honest answer is usually a qualification rule, not price — and
    sometimes the rule is the thing that should change.
    """
    if not disqualified:
        return []

    by_supplier: dict[str, list[str]] = {}
    for row in disqualified:
        by_supplier.setdefault(row["supplier"], []).extend(row.get("reasons", []))

    names = ", ".join(sorted(by_supplier))
    return [Finding(
        kind="suppliers_excluded",
        severity="info",
        say_to_user=(
            f"Excluded by your qualification rules before price was even "
            f"considered: {names}. Worth checking those rules are current."
        ),
        detail={"excluded": disqualified},
    )]


# ── top-level entry point ─────────────────────────────────────────────────


def advise(
    solution: Optional[dict],
    validation: dict,
    sensitivity: Optional[dict] = None,
    disqualified: Optional[list[dict]] = None,
    rebates: Optional[list[dict]] = None,
    solve_seconds: Optional[float] = None,
    has_increment: bool = False,
) -> dict:
    """
    Produce the full reading of one sourcing decision.

    Args:
        solution:     Solver.solve() output, or None if infeasible.
        validation:   Solver.validate() output.
        sensitivity:  Solver.sensitivity() output, if it was run.
        disqualified: Solver.disqualified() output.
        rebates:      [{supplier, threshold, pct}, ...] in effect.
        solve_seconds: How long the solve took, so a slow one can be
                      offered the award-grid shortcut.
        has_increment: Whether an award grid is already configured.

    Returns:
        {
          "verdict":  one-line summary the agent can lead with,
          "findings": [Finding-as-dict, ...] ordered by what to do next,
          "tco":      the optimal cost, or None,
        }
    """
    findings: list[Finding] = []
    findings.extend(assess_data_quality(validation))

    if solution is None:
        findings.extend(assess_infeasibility(validation))
        return {
            "verdict": (
                "No feasible award exists. The rules conflict — "
                "something has to give before there is an answer to quote."
            ),
            "findings": [f.to_dict() for f in _rank(findings)],
            "tco": None,
        }

    findings.extend(assess_concentration(solution))
    findings.extend(assess_rebate_proximity(solution, rebates or []))
    findings.extend(assess_exclusions(disqualified or []))
    findings.extend(assess_award_granularity(solve_seconds, has_increment))
    if sensitivity:
        findings.extend(assess_negotiation_levers(sensitivity))

    ranked = _rank(findings)
    return {
        "verdict": _verdict(solution, ranked),
        "findings": [f.to_dict() for f in ranked],
        "tco": solution.get("tco"),
    }


def _rank(findings: list[Finding]) -> list[Finding]:
    """Order by how much a finding should change the agent's next move."""
    return sorted(findings, key=lambda f: _SEVERITY_ORDER.get(f.severity, 99))


def _verdict(solution: dict, findings: list[Finding]) -> str:
    """One sentence to lead with, calibrated to the worst finding."""
    tco = solution.get("tco", 0)
    blocking = [f for f in findings if f.severity == "critical"]
    if blocking:
        return (
            f"The cheapest legal award costs {_money(tco)}, but do not quote "
            f"it yet — {blocking[0].say_to_user}"
        )

    risks = [f for f in findings if f.severity == "warning"]
    chances = [f for f in findings if f.severity == "opportunity"]

    verdict = f"The cheapest legal award costs {_money(tco)}."
    if chances:
        verdict += f" {chances[0].say_to_user}"
    elif risks:
        verdict += f" Before signing: {risks[0].say_to_user}"
    else:
        verdict += (
            " Nothing about it looks risky and no constraint is costing you "
            "money — this one is ready to go."
        )
    return verdict
