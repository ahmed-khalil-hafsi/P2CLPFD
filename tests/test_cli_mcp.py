"""
End-to-end tests for the CLI and the MCP server.

These drive the real binaries against real CSVs, so they cover the wiring
that unit tests cannot: argument parsing, exit codes, JSON shape, and the
JSON-RPC envelope. They need SWI-Prolog and janus-swi installed, and are
skipped when the solver cannot be imported.

    python -m unittest discover tests
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(REPO, "tests", "fixtures")

# These tests pin WIRING — argument parsing, exit codes, JSON shape, the
# JSON-RPC envelope — not solver throughput. A tiny fixture exercises the
# same code paths in ~0.5s where sample.csv takes ~9s per solve, and
# `advise`/`sensitivity` re-solve once per binding constraint on top of
# that. One test below still uses sample.csv to pin the documented number.
TINY = os.path.join(FIXTURES, "tiny.csv")
TINY_MULTIPERIOD = os.path.join(FIXTURES, "tiny_multiperiod.csv")
SAMPLE = os.path.join(REPO, "sample.csv")

EXIT_OK = 0
EXIT_NO_ANSWER = 1
EXIT_BAD_INPUT = 2

# Prolog start-up plus a full branch-and-bound solve is not instant.
TIMEOUT = 300


def _solver_available() -> bool:
    try:
        import janus_swi  # noqa: F401
    except Exception:
        return False
    return True


AVAILABLE = _solver_available()


def _cli(*args, expect=None):
    """Run the CLI in-process-ish (as a module) and return (code, stdout)."""
    proc = subprocess.run(
        [sys.executable, "-m", "p2clpfd.cli", *args],
        capture_output=True, text=True, cwd=REPO, timeout=TIMEOUT,
    )
    if expect is not None:
        assert proc.returncode == expect, (
            f"expected exit {expect}, got {proc.returncode}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
    return proc.returncode, proc.stdout, proc.stderr


def _mcp(requests: list[dict]) -> dict[int, dict]:
    """Drive the MCP server over stdio; return responses keyed by id."""
    payload = "\n".join(json.dumps(r) for r in requests) + "\n"
    proc = subprocess.run(
        [sys.executable, "-m", "p2clpfd.mcp"],
        input=payload, capture_output=True, text=True, cwd=REPO, timeout=TIMEOUT,
    )
    out = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        msg = json.loads(line)
        out[msg.get("id")] = msg
    return out


def _tool_call(tool_id: int, name: str, arguments: dict) -> dict:
    return {
        "jsonrpc": "2.0", "id": tool_id, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


def _tool_text(response: dict) -> str:
    return response["result"]["content"][0]["text"]


@unittest.skipUnless(AVAILABLE, "requires SWI-Prolog + janus-swi")
class TestCLI(unittest.TestCase):
    def test_solve_reports_the_optimum(self):
        _, out, _ = _cli("solve", TINY, expect=EXIT_OK)
        self.assertIn("367", out)

    def test_documented_sample_answer_does_not_drift(self):
        # The one test on the real sample: README and TECHNICAL.md quote
        # this number, so it must not change silently.
        _, out, _ = _cli("solve", SAMPLE, "--json", expect=EXIT_OK)
        data = json.loads(out)
        self.assertEqual(data["tco"], 19534)
        self.assertEqual({a["part"] for a in data["allocations"]}, {"part1", "part2"})

    def test_solve_json_is_machine_readable(self):
        _, out, _ = _cli("solve", TINY, "--json", expect=EXIT_OK)
        data = json.loads(out)
        self.assertEqual(data["tco"], 367)
        self.assertEqual({a["part"] for a in data["allocations"]}, {"bolt", "nut"})

    def test_json_and_table_agree_on_the_number(self):
        _, table, _ = _cli("solve", TINY, expect=EXIT_OK)
        _, raw, _ = _cli("solve", TINY, "--json", expect=EXIT_OK)
        self.assertIn(f"{json.loads(raw)['tco']:,}", table)

    def test_max_cost_below_optimum_is_no_answer(self):
        code, out, _ = _cli("solve", TINY, "--max-cost", "100")
        self.assertEqual(code, EXIT_NO_ANSWER)
        self.assertIn("No award", out)

    def test_validate_clean_data_exits_ok(self):
        _, out, _ = _cli("validate", TINY, "--json", expect=EXIT_OK)
        self.assertEqual(json.loads(out)["status"], "ok")

    def test_validate_broken_data_exits_nonzero(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as fh:
            fh.write("part,supplier,demand,unit_cost,capacity,moq\n")
            fh.write("widget,alpha,100,10,50,80\n")   # MOQ 80 > capacity 50
            path = fh.name
        try:
            code, out, _ = _cli("validate", path, "--json")
            self.assertEqual(code, EXIT_NO_ANSWER)
            report = json.loads(out)
            self.assertEqual(report["status"], "error")
            self.assertTrue(report["issues"])
        finally:
            os.unlink(path)

    def test_advise_returns_a_verdict_and_findings(self):
        _, out, _ = _cli("advise", TINY, "--step", "2", "--json", expect=EXIT_OK)
        report = json.loads(out)
        self.assertTrue(report["verdict"])
        for finding in report["findings"]:
            self.assertIn("say_to_user", finding)
            self.assertIn(finding["severity"],
                          {"critical", "warning", "opportunity", "info"})

    def test_sensitivity_orders_levers_by_savings(self):
        _, out, _ = _cli("sensitivity", TINY, "--step", "2", "--json",
                         expect=EXIT_OK)
        levers = json.loads(out)["negotiation_levers"]
        savings = [l["savings"] for l in levers]
        self.assertEqual(savings, sorted(savings, reverse=True))

    def test_inapplicable_fields_are_json_null_not_the_string(self):
        # An agent must never see a supplier literally named "null".
        _, out, _ = _cli("sensitivity", TINY, "--step", "2", "--json",
                         expect=EXIT_OK)
        for row in json.loads(out)["binding_constraints"]:
            self.assertNotEqual(row.get("supplier"), "null")
            self.assertNotEqual(row.get("part"), "null")

    def test_scenarios_report_deltas_against_baseline(self):
        _, out, _ = _cli(
            "scenarios", TINY,
            "--scenario", 'cheaper:[{"cost_delta": ["beta", "bolt", -20]}]',
            "--json", expect=EXIT_OK,
        )
        report = json.loads(out)
        self.assertEqual(report["results"][0]["name"], "baseline")
        self.assertTrue(any(d["name"] == "cheaper" for d in report["deltas"]))

    def test_scenarios_reject_malformed_specs(self):
        code, _, err = _cli("scenarios", TINY, "--scenario", "missing_json_part")
        self.assertEqual(code, EXIT_BAD_INPUT)
        self.assertIn("NAME:JSON", err)

    def test_multiperiod_plan_carries_inventory(self):
        _, out, _ = _cli("multiperiod", TINY_MULTIPERIOD, "--json", expect=EXIT_OK)
        plan = json.loads(out)
        self.assertEqual(plan["tco"], 420)          # 40 units @10 + 10 carried @2
        first = next(r for r in plan["plan"] if r["period"] == 1)
        self.assertEqual(first["end_inventory"], 10)

    def test_missing_file_is_a_usage_error(self):
        code, _, err = _cli("solve", "/nonexistent/nope.csv")
        self.assertEqual(code, EXIT_BAD_INPUT)
        self.assertIn("no such CSV", err)

    def test_non_procurement_csv_is_rejected(self):
        # Must not silently fall back to the demo facts in facts.pl.
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as fh:
            fh.write("alpha,beta,gamma\n1,2,3\n")
            path = fh.name
        try:
            code, out, err = _cli("solve", path)
            self.assertEqual(code, EXIT_BAD_INPUT)
            self.assertNotIn("367", out)        # the tiny fixture's answer
        finally:
            os.unlink(path)

    def test_decimal_cost_is_rejected_at_load_not_at_solve(self):
        # The engine is integer-only; a decimal unit_cost used to load fine and
        # then crash the solver with an opaque Prolog type error. It must now be
        # a clean input error that names the cell and the workaround.
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as fh:
            fh.write("part,supplier,demand,unit_cost,capacity\n"
                     "widget,acme,100,4.2,100\n"
                     "widget,globex,100,5,100\n")
            path = fh.name
        try:
            code, _, err = _cli("solve", path)
            self.assertEqual(code, EXIT_BAD_INPUT)
            self.assertIn("4.2", err)
            self.assertIn("integer", err.lower())
            self.assertNotIn("Type error", err)   # no raw Prolog leak
        finally:
            os.unlink(path)

    def test_scenario_name_with_spaces_and_symbols_round_trips(self):
        # Free-text names ("C +10% on MCC") are quoted into a Prolog atom rather
        # than interpolated raw, which used to be a "Operator expected" crash.
        name = "C +10% on MCC"
        _, out, _ = _cli(
            "scenarios", TINY,
            "--scenario", f'{name}:[{{"cost_delta": ["beta", "bolt", -20]}}]',
            "--json", expect=EXIT_OK,
        )
        report = json.loads(out)
        self.assertTrue(any(r["name"] == name for r in report["results"]))


@unittest.skipUnless(AVAILABLE, "requires SWI-Prolog + janus-swi")
class TestMCP(unittest.TestCase):
    def test_initialize_advertises_tools(self):
        responses = _mcp([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        ])
        result = responses[1]["result"]
        self.assertEqual(result["serverInfo"]["name"], "p2clpfd")
        self.assertIn("tools", result["capabilities"])

    def test_tools_list_is_well_formed(self):
        responses = _mcp([
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        ])
        tools = responses[1]["result"]["tools"]
        names = {t["name"] for t in tools}
        self.assertIn("get_advice", names)
        self.assertIn("analyze_sensitivity", names)
        for tool in tools:
            self.assertTrue(tool["description"].strip())
            self.assertEqual(tool["inputSchema"]["type"], "object")
            for required in tool["inputSchema"].get("required", []):
                self.assertIn(required, tool["inputSchema"]["properties"])

    def test_notifications_get_no_response(self):
        responses = _mcp([
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}},
        ])
        self.assertEqual(set(responses), {7})

    def test_get_advice_returns_verdict_and_findings(self):
        responses = _mcp([
            _tool_call(1, "get_advice", {"csv_path": TINY, "sensitivity_step": 2}),
        ])
        report = json.loads(_tool_text(responses[1]))
        self.assertEqual(report["tco"], 367)
        self.assertTrue(report["verdict"])

    def test_solve_allocation_matches_the_cli(self):
        responses = _mcp([_tool_call(1, "solve_allocation", {"csv_path": TINY})])
        mcp_tco = json.loads(_tool_text(responses[1]))["tco"]
        _, out, _ = _cli("solve", TINY, "--json", expect=EXIT_OK)
        self.assertEqual(mcp_tco, json.loads(out)["tco"])
        self.assertEqual(mcp_tco, 367)

    def test_infeasible_is_reported_as_content_not_a_crash(self):
        responses = _mcp([
            _tool_call(1, "solve_allocation", {"csv_path": TINY, "max_cost": 10}),
        ])
        self.assertNotIn("error", responses[1])
        self.assertEqual(json.loads(_tool_text(responses[1]))["status"], "infeasible")

    def test_missing_csv_is_a_tool_error_the_agent_can_read(self):
        responses = _mcp([
            _tool_call(1, "solve_allocation", {"csv_path": "/nonexistent/nope.csv"}),
        ])
        result = responses[1]["result"]
        self.assertTrue(result["isError"])
        self.assertIn("not found", _tool_text(responses[1]).lower())

    def test_award_grid_rounds_the_award(self):
        responses = _mcp([
            _tool_call(1, "set_award_grid",
                       {"csv_path": TINY, "increment_pct": 10}),
        ])
        result = json.loads(_tool_text(responses[1]))
        self.assertEqual(result["status"], "ok")
        for part in result["allocations"]:
            for s in part["suppliers"]:
                # 10% of bolt(20)=2 and nut(15)=1.5 -> only even levels for nut
                self.assertGreater(s["qty"], 0)

    def test_award_grid_reports_what_the_rounding_costs(self):
        responses = _mcp([
            _tool_call(1, "set_award_grid",
                       {"csv_path": TINY, "increment_pct": 10, "compare": True}),
        ])
        result = json.loads(_tool_text(responses[1]))
        comp = result["comparison"]
        self.assertEqual(comp["unrestricted_tco"], 367)
        self.assertGreaterEqual(comp["extra_cost"], 0)
        self.assertTrue(comp["say_to_user"])

    def test_impossible_grid_explains_itself_rather_than_just_failing(self):
        # 25% of nut's 15 units is 3.75, so only 0 or all-of-it lands on the
        # grid — which collides with needing two suppliers.
        responses = _mcp([
            _tool_call(1, "set_award_grid",
                       {"csv_path": TINY, "increment_pct": 25}),
        ])
        result = json.loads(_tool_text(responses[1]))
        self.assertEqual(result["status"], "infeasible")
        self.assertIn("finer step", result["message"])

    def test_award_grid_rejects_a_step_that_cannot_divide_100(self):
        # 3% can never sum to 100%, so the model would be quietly infeasible.
        responses = _mcp([
            _tool_call(1, "set_award_grid",
                       {"csv_path": TINY, "increment_pct": 3}),
        ])
        self.assertTrue(responses[1]["result"]["isError"])
        self.assertIn("divide 100", _tool_text(responses[1]))

    def test_award_grid_does_not_leak_into_later_solves(self):
        responses = _mcp([
            _tool_call(1, "set_award_grid",
                       {"csv_path": TINY, "increment_pct": 10}),
            _tool_call(2, "solve_allocation", {"csv_path": TINY}),
        ])
        self.assertEqual(json.loads(_tool_text(responses[2]))["tco"], 367)

    def test_trace_actually_runs(self):
        # The tracer sat broken for two releases because nothing called it:
        # build_rebates/4 changed signature and tracer.pl kept the old order.
        responses = _mcp([_tool_call(1, "solve_trace", {"csv_path": TINY})])
        self.assertFalse(responses[1]["result"].get("isError"),
                         msg=_tool_text(responses[1])[:200])
        lines = [l for l in _tool_text(responses[1]).splitlines() if l.strip()]
        self.assertGreater(len(lines), 10)
        events = [json.loads(l)["event"] for l in lines]
        self.assertIn("optimal", events)

    def test_trace_agrees_with_the_plain_solve(self):
        responses = _mcp([
            _tool_call(1, "solve_trace", {"csv_path": TINY}),
            _tool_call(2, "solve_allocation", {"csv_path": TINY}),
        ])
        traced = [json.loads(l) for l in _tool_text(responses[1]).splitlines()
                  if l.strip()]
        optimal = next(e for e in traced if e["event"] == "optimal")
        self.assertEqual(optimal["tco"],
                         json.loads(_tool_text(responses[2]))["tco"])

    def test_trace_narrows_domains_as_constraints_are_posted(self):
        # The point of the tracer is showing options being eliminated.
        responses = _mcp([_tool_call(1, "solve_trace", {"csv_path": TINY})])
        snaps = [json.loads(l) for l in _tool_text(responses[1]).splitlines()
                 if l.strip() and json.loads(l)["event"] == "domain_snapshot"]
        self.assertGreater(len(snaps), 1)
        first = sum(len(v["domain"]) for v in snaps[0]["vars"])
        last = sum(len(v["domain"]) for v in snaps[-1]["vars"])
        self.assertLess(last, first)

    def test_unknown_tool_is_an_error(self):
        responses = _mcp([_tool_call(1, "no_such_tool", {})])
        self.assertTrue(responses[1]["result"]["isError"])

    def test_unknown_method_is_a_jsonrpc_error(self):
        responses = _mcp([{"jsonrpc": "2.0", "id": 1, "method": "nope/nope"}])
        self.assertEqual(responses[1]["error"]["code"], -32601)

    def test_a_failed_call_does_not_poison_later_calls(self):
        # The solver is a long-lived process; a bad load must not leave
        # stale facts behind for the next request.
        responses = _mcp([
            _tool_call(1, "solve_allocation", {"csv_path": "/nonexistent/nope.csv"}),
            _tool_call(2, "solve_allocation", {"csv_path": TINY}),
        ])
        self.assertTrue(responses[1]["result"]["isError"])
        self.assertEqual(json.loads(_tool_text(responses[2]))["tco"], 367)


class TestMCPResources(unittest.TestCase):
    """The resource surface is pure-Python — it serves without the solver, so
    these run even where SWI-Prolog is not installed."""

    def test_initialize_advertises_resources(self):
        responses = _mcp([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        ])
        self.assertIn("resources", responses[1]["result"]["capabilities"])

    def test_resources_list_offers_the_csv_schema(self):
        responses = _mcp([
            {"jsonrpc": "2.0", "id": 1, "method": "resources/list", "params": {}},
        ])
        resources = responses[1]["result"]["resources"]
        uris = {r["uri"] for r in resources}
        self.assertIn("p2clpfd://csv-schema", uris)
        for res in resources:
            self.assertTrue(res["name"].strip())
            self.assertTrue(res["description"].strip())

    def test_resources_read_returns_the_column_reference(self):
        responses = _mcp([
            {"jsonrpc": "2.0", "id": 1, "method": "resources/read",
             "params": {"uri": "p2clpfd://csv-schema"}},
        ])
        contents = responses[1]["result"]["contents"]
        self.assertEqual(contents[0]["uri"], "p2clpfd://csv-schema")
        text = contents[0]["text"]
        # The four required columns must be named so an agent can build a CSV.
        for col in ("part", "supplier", "demand", "unit_cost"):
            self.assertIn(col, text)

    def test_reading_an_unknown_resource_is_an_error(self):
        responses = _mcp([
            {"jsonrpc": "2.0", "id": 1, "method": "resources/read",
             "params": {"uri": "p2clpfd://nope"}},
        ])
        self.assertIn("error", responses[1])


if __name__ == "__main__":
    unittest.main()
