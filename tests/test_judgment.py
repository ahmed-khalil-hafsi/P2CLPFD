"""
Tests for the judgment layer.

These run on hand-built solver output rather than through Prolog, so they
are fast and pin the INTERPRETATION independently of the math. If a
verdict changes, that should be a deliberate edit here, not a surprise.

    python -m unittest discover tests
"""

import unittest

from p2clpfd.judgment import (
    advise,
    assess_award_granularity,
    assess_concentration,
    assess_data_quality,
    assess_negotiation_levers,
    assess_rebate_proximity,
    assess_exclusions,
)


def _solution(tco, allocations):
    return {"tco": tco, "status": "ok", "allocations": allocations}


def _part(name, suppliers):
    return {"part": name, "suppliers": suppliers}


def _supplier(name, qty, subtotal, fixed_cost=0):
    return {
        "supplier": name,
        "qty": qty,
        "unit_cost": subtotal // qty if qty else 0,
        "subtotal": subtotal,
        "fixed_cost": fixed_cost,
    }


CLEAN = {"status": "ok", "issue_count": 0, "issues": []}


class TestDataQuality(unittest.TestCase):
    def test_clean_data_says_nothing(self):
        self.assertEqual(assess_data_quality(CLEAN), [])

    def test_error_is_critical_and_quotes_the_issue(self):
        report = {
            "status": "error",
            "issues": [{"severity": "error", "message": "Capacity is below demand."}],
        }
        findings = assess_data_quality(report)
        self.assertEqual(findings[0].severity, "critical")
        self.assertIn("Capacity is below demand.", findings[0].say_to_user)

    def test_warning_is_not_critical(self):
        report = {
            "status": "warning",
            "issues": [{"severity": "warning", "message": "Supplier has no price."}],
        }
        findings = assess_data_quality(report)
        self.assertEqual(findings[0].severity, "warning")


class TestConcentration(unittest.TestCase):
    def test_single_sourced_part_is_flagged(self):
        sol = _solution(1000, [_part("p1", [_supplier("a", 100, 1000)])])
        kinds = [f.kind for f in assess_concentration(sol)]
        self.assertIn("single_source", kinds)

    def test_two_suppliers_is_not_single_sourced(self):
        sol = _solution(
            1000,
            [_part("p1", [_supplier("a", 50, 500), _supplier("b", 50, 500)])],
        )
        kinds = [f.kind for f in assess_concentration(sol)]
        self.assertNotIn("single_source", kinds)

    def test_zero_quantity_supplier_does_not_count_as_active(self):
        # A supplier awarded nothing must not make the part look dual-sourced.
        sol = _solution(
            1000,
            [_part("p1", [_supplier("a", 100, 1000), _supplier("b", 0, 0)])],
        )
        kinds = [f.kind for f in assess_concentration(sol)]
        self.assertIn("single_source", kinds)

    def test_dominant_supplier_is_flagged(self):
        sol = _solution(
            1000,
            [
                _part("p1", [_supplier("a", 90, 900)]),
                _part("p2", [_supplier("b", 10, 100)]),
            ],
        )
        conc = [f for f in assess_concentration(sol) if f.kind == "spend_concentration"]
        self.assertEqual(len(conc), 1)
        self.assertEqual(conc[0].detail["supplier"], "a")
        self.assertEqual(conc[0].detail["share_pct"], 90.0)

    def test_balanced_spend_is_not_flagged(self):
        sol = _solution(
            1000,
            [
                _part("p1", [_supplier("a", 50, 500)]),
                _part("p2", [_supplier("b", 50, 500)]),
            ],
        )
        conc = [f for f in assess_concentration(sol) if f.kind == "spend_concentration"]
        self.assertEqual(conc, [])

    def test_fixed_costs_count_towards_spend(self):
        sol = _solution(
            2000,
            [
                _part("p1", [_supplier("a", 10, 100, fixed_cost=900)]),
                _part("p2", [_supplier("b", 10, 100)]),
            ],
        )
        conc = [f for f in assess_concentration(sol) if f.kind == "spend_concentration"]
        self.assertEqual(conc[0].detail["supplier"], "a")


class TestNegotiationLevers(unittest.TestCase):
    def test_large_saving_is_an_opportunity(self):
        sens = {
            "tco": 10000,
            "negotiation_levers": [
                {"constraint": "capacity", "supplier": "a", "part": "p1",
                 "relaxed_limit": 60, "new_tco": 9500, "savings": 500},
            ],
        }
        findings = assess_negotiation_levers(sens)
        self.assertEqual(findings[0].severity, "opportunity")
        self.assertIn("500", findings[0].say_to_user)

    def test_trivial_saving_is_ignored_as_noise(self):
        sens = {
            "tco": 10000,
            "negotiation_levers": [
                {"constraint": "capacity", "supplier": "a", "part": "p1",
                 "relaxed_limit": 60, "new_tco": 9999, "savings": 1},
            ],
        }
        self.assertEqual(assess_negotiation_levers(sens), [])

    def test_all_zero_levers_says_so_explicitly(self):
        # Telling a buyer NOT to negotiate is as useful as telling them to.
        sens = {
            "tco": 10000,
            "negotiation_levers": [
                {"constraint": "moq", "supplier": "a", "part": "p1",
                 "relaxed_limit": 0, "new_tco": 10000, "savings": 0},
            ],
        }
        findings = assess_negotiation_levers(sens)
        self.assertEqual(findings[0].kind, "no_levers")
        self.assertIn("not lower the cost", findings[0].say_to_user)

    def test_infeasible_sensitivity_is_silent(self):
        self.assertEqual(
            assess_negotiation_levers({"tco": None, "negotiation_levers": []}), []
        )

    def test_lever_names_avoid_prolog_jargon(self):
        sens = {
            "tco": 10000,
            "negotiation_levers": [
                {"constraint": "max_global_share", "supplier": "a", "part": None,
                 "relaxed_limit": 41, "new_tco": 9000, "savings": 1000},
            ],
        }
        said = assess_negotiation_levers(sens)[0].say_to_user
        self.assertIn("share cap on a", said)
        self.assertNotIn("max_global_share", said)


class TestRebateProximity(unittest.TestCase):
    def test_near_miss_is_reported(self):
        sol = _solution(1000, [_part("p1", [_supplier("a", 95, 1000)])])
        rebates = [{"supplier": "a", "threshold": 100, "pct": 5}]
        findings = assess_rebate_proximity(sol, rebates)
        self.assertEqual(findings[0].kind, "rebate_near_miss")
        self.assertEqual(findings[0].detail["gap"], 5)

    def test_far_short_is_not_reported(self):
        sol = _solution(1000, [_part("p1", [_supplier("a", 10, 100)])])
        rebates = [{"supplier": "a", "threshold": 100, "pct": 5}]
        self.assertEqual(assess_rebate_proximity(sol, rebates), [])

    def test_already_earned_is_not_reported(self):
        sol = _solution(1000, [_part("p1", [_supplier("a", 120, 1200)])])
        rebates = [{"supplier": "a", "threshold": 100, "pct": 5}]
        self.assertEqual(assess_rebate_proximity(sol, rebates), [])

    def test_unused_supplier_is_not_reported(self):
        # Nudging volume to a supplier with zero award is a different
        # decision entirely, not a near miss.
        sol = _solution(1000, [_part("p1", [_supplier("b", 100, 1000)])])
        rebates = [{"supplier": "a", "threshold": 100, "pct": 5}]
        self.assertEqual(assess_rebate_proximity(sol, rebates), [])


class TestAwardGranularity(unittest.TestCase):
    def test_slow_solve_without_a_grid_gets_the_offer(self):
        findings = assess_award_granularity(12.0, has_increment=False)
        self.assertEqual(findings[0].kind, "suggest_award_grid")
        self.assertEqual(findings[0].detail["suggested_pct"], 5)

    def test_fast_solve_is_left_alone(self):
        # Telling someone to change a model that already answers instantly
        # is noise, not advice.
        self.assertEqual(assess_award_granularity(0.4, has_increment=False), [])

    def test_existing_grid_is_not_re_offered(self):
        self.assertEqual(assess_award_granularity(30.0, has_increment=True), [])

    def test_unknown_timing_says_nothing(self):
        self.assertEqual(assess_award_granularity(None, has_increment=False), [])

    def test_offer_states_the_trade_off(self):
        finding = assess_award_granularity(12.0, has_increment=False)[0]
        self.assertIn("caveat", finding.detail)
        self.assertTrue(all(100 % s == 0 for s in finding.detail["usable_steps"]))


class TestExclusions(unittest.TestCase):
    def test_excluded_suppliers_are_surfaced(self):
        excluded = [{"part": "p1", "supplier": "a", "reasons": ["otif_below(90,95)"]}]
        findings = assess_exclusions(excluded)
        self.assertEqual(findings[0].kind, "suppliers_excluded")
        self.assertIn("a", findings[0].say_to_user)

    def test_nothing_excluded_is_silent(self):
        self.assertEqual(assess_exclusions([]), [])


class TestAdvise(unittest.TestCase):
    def test_clean_award_reads_as_ready(self):
        sol = _solution(
            1000,
            [_part("p1", [_supplier("a", 50, 500), _supplier("b", 50, 500)])],
        )
        report = advise(sol, CLEAN)
        self.assertEqual(report["tco"], 1000)
        self.assertIn("ready to go", report["verdict"])

    def test_infeasible_explains_which_rule_to_relax(self):
        validation = {
            "status": "error",
            "issues": [{
                "severity": "error",
                "message": "Qualified suppliers can supply 80 but 100 are needed.",
                "detail": "capacity_below_demand(p1,80,100)",
            }],
        }
        report = advise(None, validation)
        self.assertIsNone(report["tco"])
        kinds = [f["kind"] for f in report["findings"]]
        self.assertIn("infeasible_explained", kinds)

    def test_infeasible_without_a_clear_cause_says_so_honestly(self):
        report = advise(None, CLEAN)
        kinds = [f["kind"] for f in report["findings"]]
        self.assertIn("infeasible_unexplained", kinds)

    def test_data_errors_outrank_everything_in_the_verdict(self):
        sol = _solution(1000, [_part("p1", [_supplier("a", 100, 1000)])])
        validation = {
            "status": "error",
            "issues": [{"severity": "error", "message": "Prices are missing."}],
        }
        report = advise(sol, validation)
        self.assertEqual(report["findings"][0]["severity"], "critical")
        self.assertIn("do not quote", report["verdict"].lower())

    def test_findings_are_ordered_by_severity(self):
        sol = _solution(1000, [_part("p1", [_supplier("a", 100, 1000)])])
        sens = {
            "tco": 1000,
            "negotiation_levers": [
                {"constraint": "capacity", "supplier": "a", "part": "p1",
                 "relaxed_limit": 60, "new_tco": 900, "savings": 100},
            ],
        }
        report = advise(sol, CLEAN, sensitivity=sens)
        order = {"critical": 0, "warning": 1, "opportunity": 2, "info": 3}
        severities = [order[f["severity"]] for f in report["findings"]]
        self.assertEqual(severities, sorted(severities))

    def test_every_finding_carries_a_plain_language_sentence(self):
        sol = _solution(1000, [_part("p1", [_supplier("a", 95, 1000)])])
        report = advise(
            sol,
            CLEAN,
            rebates=[{"supplier": "a", "threshold": 100, "pct": 5}],
            disqualified=[{"part": "p1", "supplier": "z", "reasons": ["no cert"]}],
        )
        self.assertTrue(report["findings"])
        for finding in report["findings"]:
            self.assertTrue(finding["say_to_user"].strip())
            self.assertTrue(finding["say_to_user"][0].isupper()
                            or finding["say_to_user"][0].isdigit())


if __name__ == "__main__":
    unittest.main()
