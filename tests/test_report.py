"""
Unit tests for the report layer.

`render_html` takes a payload and returns a string — no solver, no files —
so the whole presentation layer is testable without SWI-Prolog, and these
run everywhere. The end-to-end wiring lives in test_cli_mcp.py.

    python -m unittest discover tests
"""

import json
import re
import unittest

from p2clpfd import report


def _payload(**overrides) -> dict:
    """A minimal but complete report payload."""
    base = {
        "generated_at": "2026-01-01T09:00:00+01:00",
        "version": "0.0.0-test",
        "command": "p2clpfd report quotes.csv -o award.html",
        "source": {"path": "/tmp/quotes.csv", "name": "quotes.csv", "sha256": "abc123"},
        "verdict": "The cheapest legal award costs 1,000.",
        "findings": [
            {"kind": "concentration", "severity": "warning",
             "say_to_user": "Spend is concentrated.", "detail": {}},
        ],
        "tco": 1000,
        "solve_seconds": 0.5,
        "allocation": {
            "tco": 1000,
            "status": "ok",
            "allocations": [
                {"part": "bolt", "suppliers": [
                    {"supplier": "alpha", "qty": 60, "unit_cost": 10,
                     "subtotal": 600, "fixed_cost": 0},
                    {"supplier": "beta", "qty": 40, "unit_cost": 10,
                     "subtotal": 400, "fixed_cost": 0},
                ]},
            ],
        },
        "validation": {"status": "ok", "issues": []},
        "sensitivity": {"status": "ok", "tco": 1000,
                        "binding_constraints": [], "negotiation_levers": []},
        "disqualified": [],
        "rebates": [],
        "scenarios": None,
        "trace": None,
    }
    base["summary"] = report._award_summary(base["allocation"])
    base.update(overrides)
    return base


def _text(html: str) -> str:
    """Strip markup and styling so assertions read the document, not the file."""
    import html as _html
    without_css = re.sub(r"<style>.*?</style>", " ", html, flags=re.S)
    return _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", without_css)))


class TestAwardSummary(unittest.TestCase):
    def test_rolls_spend_up_per_supplier(self):
        summary = report._award_summary(_payload()["allocation"])
        by_name = {s["supplier"]: s for s in summary["suppliers"]}
        self.assertEqual(by_name["alpha"]["spend"], 600)
        self.assertEqual(by_name["alpha"]["share_pct"], 60.0)
        self.assertEqual(summary["awarded"], 1000)

    def test_biggest_supplier_comes_first(self):
        summary = report._award_summary(_payload()["allocation"])
        self.assertEqual(summary["suppliers"][0]["supplier"], "alpha")

    def test_one_off_costs_count_as_spend(self):
        allocation = {"tco": 1500, "allocations": [
            {"part": "bolt", "suppliers": [
                {"supplier": "alpha", "qty": 10, "unit_cost": 100,
                 "subtotal": 1000, "fixed_cost": 500},
            ]},
        ]}
        self.assertEqual(report._award_summary(allocation)["awarded"], 1500)

    def test_unawarded_suppliers_are_left_out(self):
        allocation = {"tco": 600, "allocations": [
            {"part": "bolt", "suppliers": [
                {"supplier": "alpha", "qty": 60, "unit_cost": 10,
                 "subtotal": 600, "fixed_cost": 0},
                {"supplier": "beta", "qty": 0, "unit_cost": 9,
                 "subtotal": 0, "fixed_cost": 0},
            ]},
        ]}
        names = {s["supplier"] for s in report._award_summary(allocation)["suppliers"]}
        self.assertEqual(names, {"alpha"})

    def test_a_rebate_shows_up_as_an_adjustment(self):
        # Line items add to 1,000 but the rebate brings the TCO to 900. The
        # gap must be reported, not silently absorbed.
        allocation = dict(_payload()["allocation"], tco=900)
        self.assertEqual(report._award_summary(allocation)["adjustment"], -100)

    def test_no_solution_summarises_to_nothing(self):
        self.assertEqual(report._award_summary(None)["awarded"], 0)


class TestSummarizeTrace(unittest.TestCase):
    def _trace(self, *events) -> str:
        return "\n".join(json.dumps(e) for e in events)

    def test_keeps_only_what_changed(self):
        summary = report.summarize_trace(self._trace(
            {"event": "model_built", "parts": ["bolt"], "suppliers": ["a", "b"]},
            {"event": "domain_snapshot", "phase": "parts", "vars": [
                {"name": "q.a.bolt", "domain": [0, 1, 2]},
                {"name": "q.b.bolt", "domain": [0, 1, 2]},
            ]},
            {"event": "domain_snapshot", "phase": "capacity", "vars": [
                {"name": "q.a.bolt", "domain": [0, 1]},     # narrowed
                {"name": "q.b.bolt", "domain": [0, 1, 2]},  # untouched
            ]},
        ))
        capacity = summary["phases"][1]
        self.assertEqual([v["name"] for v in capacity["changed"]], ["q.a.bolt"])

    def test_records_the_range_before_and_after(self):
        summary = report.summarize_trace(self._trace(
            {"event": "domain_snapshot", "phase": "parts", "vars": [
                {"name": "q.a.bolt", "domain": [0, 1, 2, 3]},
            ]},
            {"event": "domain_snapshot", "phase": "risk", "vars": [
                {"name": "q.a.bolt", "domain": [2, 3]},
            ]},
        ))
        narrowed = summary["phases"][1]["changed"][0]
        self.assertEqual((narrowed["was_min"], narrowed["was_max"]), (0, 3))
        self.assertEqual((narrowed["min"], narrowed["max"], narrowed["size"]), (2, 3, 2))

    def test_drops_the_domain_values_themselves(self):
        # A 20,000-unit part carries 20,001 integers per variable per phase.
        # Keeping them would put megabytes of digits in the document.
        summary = report.summarize_trace(self._trace(
            {"event": "domain_snapshot", "phase": "parts", "vars": [
                {"name": "q.a.bolt", "domain": list(range(5000))},
            ]},
        ))
        self.assertNotIn("domain", summary["phases"][0]["changed"][0])

    def test_every_phase_is_explained_in_english(self):
        summary = report.summarize_trace(self._trace(
            *[{"event": "domain_snapshot", "phase": phase,
               "vars": [{"name": "q.a.bolt", "domain": [0, 1]}]}
              for phase in report._PHASE_LABELS]
        ))
        for phase in summary["phases"]:
            self.assertNotEqual(phase["label"], phase["phase"],
                                f"{phase['phase']} has no plain-language label")
            self.assertTrue(phase["explanation"])

    def test_collects_the_solutions_and_the_optimum(self):
        summary = report.summarize_trace(self._trace(
            {"event": "domain_snapshot", "phase": "parts", "vars": [
                {"name": "q.a.bolt", "domain": [0, 1]}]},
            {"event": "solution_found", "tco": 120, "type": "first"},
            {"event": "solution_found", "tco": 100, "type": "better"},
            {"event": "optimal", "tco": 100},
        ))
        self.assertEqual([s["tco"] for s in summary["solutions"]], [120, 100])
        self.assertEqual(summary["tco"], 100)

    def test_a_trace_with_no_snapshots_is_nothing_to_show(self):
        self.assertIsNone(report.summarize_trace(""))
        self.assertIsNone(report.summarize_trace(
            self._trace({"event": "infeasible"})))

    def test_a_truncated_line_does_not_sink_the_report(self):
        raw = '{"event":"domain_snapshot","phase":"parts","vars":[{"name":"q.a.b"\n'
        raw += json.dumps({"event": "domain_snapshot", "phase": "risk",
                           "vars": [{"name": "q.a.bolt", "domain": [1]}]})
        self.assertEqual(len(report.summarize_trace(raw)["phases"]), 1)


class TestRuleNames(unittest.TestCase):
    """Rule names are the one place solver vocabulary can leak into a
    document a category manager reads. These hold that line."""

    def test_every_rule_carries_a_label_meaning_and_example(self):
        for kind, entry in report._RULES.items():
            label, meaning, example = entry
            self.assertTrue(label and not label.endswith("."), kind)
            self.assertTrue(meaning.endswith("."), f"{kind} meaning is a sentence")
            self.assertTrue(example.endswith("."), f"{kind} example is a sentence")
            self.assertNotIn("_", label, f"{kind} label leaks an identifier")

    def test_a_known_rule_explains_itself_on_hover(self):
        html = report._rule_html("moq")
        self.assertIn('class="rule"', html)
        self.assertIn("minimum order", html)
        self.assertIn("smallest order this supplier will accept", html)
        self.assertIn("For example", html)

    def test_the_tooltip_is_reachable_without_a_mouse(self):
        # A document that can only be understood by hovering excludes anyone
        # on a keyboard, and prints to a page with no explanation at all.
        self.assertIn("tabindex", report._rule_html("moq"))

    def test_an_unknown_rule_gets_words_but_no_invented_explanation(self):
        html = report._rule_html("some_new_rule")
        self.assertEqual(html, "some new rule")
        self.assertNotIn("class=", html)

    def test_the_glossary_covers_the_rules_that_shaped_the_award(self):
        payload = _payload(sensitivity={
            "status": "ok", "tco": 1000,
            "binding_constraints": [
                {"constraint": "moq", "supplier": "alpha", "part": "bolt",
                 "used": 60, "limit": 60},
            ],
            "negotiation_levers": [
                {"constraint": "max_global_share", "supplier": "alpha",
                 "part": None, "relaxed_limit": 61, "savings": 40},
            ],
        })
        text = _text(report.render_html(payload))
        self.assertIn("What these rules mean", text)
        self.assertIn("smallest order this supplier will accept", text)
        self.assertIn("stops a cheap supplier quietly becoming critical", text)
        # A rule that did not shape this award is not explained here.
        self.assertNotIn("route", text)

    def test_no_glossary_when_no_rule_was_named(self):
        self.assertEqual(report._glossary(_payload()), "")

    def test_the_rendered_document_names_no_solver_identifiers(self):
        payload = _payload(sensitivity={
            "status": "ok", "tco": 1000, "negotiation_levers": [],
            "binding_constraints": [
                {"constraint": kind, "supplier": "alpha", "part": "bolt",
                 "used": 1, "limit": 1}
                for kind in report._RULES
            ],
        })
        text = _text(report.render_html(payload))
        # `capacity` is both an identifier and an ordinary English word, so
        # the test is about the shapes only a solver would write: snake_case
        # names, and the one acronym that is pure jargon.
        for kind in list(report._RULES) + ["moq", "dual_source", "tco"]:
            if "_" in kind or kind == "moq":
                self.assertNotIn(kind, text, f"{kind} leaked into the document")


class TestRenderHTML(unittest.TestCase):
    def test_renders_a_whole_document(self):
        html = report.render_html(_payload())
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("</html>", html.strip()[-10:])

    def test_leads_with_the_cost_and_the_verdict(self):
        text = _text(report.render_html(_payload()))
        self.assertIn("1,000", text)
        self.assertIn("The cheapest legal award costs 1,000.", text)

    def test_nothing_is_loaded_from_the_network(self):
        # This file has to open from an email attachment on a locked-down
        # laptop in five years. Nothing may be fetched at open time.
        html = report.render_html(_payload())
        for forbidden in ("http://", "https://", "<script", "<img", "@import", "url("):
            self.assertNotIn(forbidden, html, f"{forbidden} makes it not self-contained")

    def test_names_the_file_and_its_checksum(self):
        text = _text(report.render_html(_payload()))
        self.assertIn("/tmp/quotes.csv", text)
        self.assertIn("abc123", text)

    def test_quotes_the_command_that_produced_it(self):
        text = _text(report.render_html(_payload()))
        self.assertIn("p2clpfd report quotes.csv -o award.html", text)

    def test_shows_every_finding(self):
        payload = _payload(findings=[
            {"kind": "a", "severity": "critical", "say_to_user": "Fix the data.",
             "detail": {}},
            {"kind": "b", "severity": "opportunity", "say_to_user": "Call supplier2.",
             "detail": {}},
        ])
        text = _text(report.render_html(payload))
        self.assertIn("Fix the data.", text)
        self.assertIn("Call supplier2.", text)

    def test_severity_is_said_in_words_not_jargon(self):
        payload = _payload(findings=[
            {"kind": "a", "severity": "critical", "say_to_user": "Fix it.", "detail": {}},
        ])
        text = _text(report.render_html(payload))
        self.assertIn("must fix", text)

    def test_supplier_names_are_escaped(self):
        # Supplier names come out of a user's CSV and land in a file other
        # people open. They are data, never markup.
        payload = _payload()
        payload["allocation"]["allocations"][0]["suppliers"][0]["supplier"] = (
            '<script>alert("x")</script>'
        )
        payload["summary"] = report._award_summary(payload["allocation"])
        html = report.render_html(payload)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_an_infeasible_model_still_produces_a_document(self):
        payload = _payload(
            tco=None, allocation=None, summary=report._award_summary(None),
            verdict="No feasible award exists.",
            sensitivity=None,
            validation={"status": "error", "issues": [
                {"severity": "error", "message": "Capacity is below demand."},
            ]},
        )
        text = _text(report.render_html(payload))
        self.assertIn("No feasible award", text)
        self.assertIn("Capacity is below demand.", text)

    def test_a_rebate_gap_is_explained_not_hidden(self):
        payload = _payload(tco=900)
        payload["summary"] = report._award_summary(
            dict(payload["allocation"], tco=900)
        )
        text = _text(report.render_html(payload))
        self.assertIn("100", text)
        self.assertIn("rebates", text)

    def test_empty_sections_are_left_out(self):
        text = _text(report.render_html(_payload()))
        self.assertNotIn("What if", text)
        self.assertNotIn("Suppliers not in the award", text)

    def test_scenarios_appear_when_they_were_run(self):
        payload = _payload(scenarios={
            "results": [{"name": "baseline", "status": "ok", "tco": 1000},
                        {"name": "no cap", "status": "ok", "tco": 900}],
            "deltas": [{"name": "no cap", "delta": -100, "pct": -10}],
        })
        text = _text(report.render_html(payload))
        self.assertIn("no cap", text)
        self.assertIn("-100", text)

    def test_excluded_suppliers_name_the_rule_that_removed_them(self):
        payload = _payload(disqualified=[
            {"supplier": "delta", "part": "bolt", "reasons": ["otif 82 below 95"]},
        ])
        text = _text(report.render_html(payload))
        self.assertIn("delta", text)
        self.assertIn("otif 82 below 95", text)

    def test_the_trace_reads_as_rules_not_variables(self):
        payload = _payload(trace=report.summarize_trace("\n".join(json.dumps(e) for e in [
            {"event": "domain_snapshot", "phase": "parts",
             "vars": [{"name": "q.alpha.bolt", "domain": [0, 1, 2]}]},
            {"event": "domain_snapshot", "phase": "risk",
             "vars": [{"name": "q.alpha.bolt", "domain": [2]}]},
        ])))
        text = _text(report.render_html(payload))
        self.assertIn("alpha on bolt", text)          # not q.alpha.bolt
        self.assertNotIn("q.alpha.bolt", text)
        self.assertIn("Sourcing rules", text)

    def test_a_portfolio_share_rule_is_shown_on_one_scale(self):
        # sensitivity.pl reports what the award uses in units even for a rule
        # whose limit is a percentage, so the raw pair reads "used 188, limit
        # 40". A document someone audits cannot carry two scales in one row.
        used, limit = report._used_against_limit(
            _payload(),
            {"constraint": "max_global_share", "supplier": "alpha",
             "part": None, "used": 60, "limit": 60},
        )
        self.assertEqual((used, limit), ("60.0%", "60%"))  # 60 of 100 awarded

    def test_a_per_part_share_is_a_share_of_that_part(self):
        used, limit = report._used_against_limit(
            _payload(),
            {"constraint": "share_min", "supplier": "beta",
             "part": "bolt", "used": 40, "limit": 40},
        )
        self.assertEqual((used, limit), ("40.0%", "40%"))

    def test_a_quantity_rule_keeps_its_units(self):
        used, limit = report._used_against_limit(
            _payload(),
            {"constraint": "capacity", "supplier": "alpha",
             "part": "bolt", "used": 60, "limit": 60},
        )
        self.assertEqual((used, limit), ("60", "60"))

    def test_an_unconvertible_share_is_left_alone_not_guessed(self):
        # No award to compute a percentage from — say nothing rather than
        # invent a denominator.
        used, limit = report._used_against_limit(
            _payload(allocation=None),
            {"constraint": "max_global_share", "supplier": "alpha",
             "part": None, "used": 60, "limit": 60},
        )
        self.assertEqual((used, limit), ("60", "60"))

    def test_rules_are_named_the_way_a_buyer_would(self):
        payload = _payload(sensitivity={
            "status": "ok", "tco": 1000, "negotiation_levers": [],
            "binding_constraints": [
                {"constraint": "moq", "supplier": "alpha", "part": "bolt",
                 "used": 60, "limit": 60},
            ],
        })
        text = _text(report.render_html(payload))
        self.assertIn("minimum order", text)
        self.assertNotIn("moq", text)

    def test_an_unknown_rule_name_still_reads_as_words(self):
        self.assertEqual(report._rule("some_new_rule"), "some new rule")

    def test_a_settled_quantity_is_one_number_not_a_range(self):
        self.assertEqual(report._range(75, 75), "75")
        self.assertIn("&ndash;", report._range(75, 150))


if __name__ == "__main__":
    unittest.main()
