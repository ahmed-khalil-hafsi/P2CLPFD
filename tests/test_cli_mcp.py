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
import pathlib
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

    def test_a_step_coarser_than_the_part_still_awards(self):
        # 25% of nut's 15 units is 3.75. Awards round to whole units, so the
        # two suppliers nut needs can take 8 and 7.
        responses = _mcp([
            _tool_call(1, "set_award_grid",
                       {"csv_path": TINY, "increment_pct": 25}),
        ])
        result = json.loads(_tool_text(responses[1]))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["tco"], 381)

    def test_impossible_grid_explains_itself_rather_than_just_failing(self):
        # A 12-13% band has no 5% level. An explicitly requested grid is
        # never dropped, so this must be reported, and explained.
        with tempfile.NamedTemporaryFile("w", suffix=".csv",
                                         delete=False) as fh:
            fh.write("part,supplier,demand,unit_cost,share_min,share_max\n"
                     "bolt,alpha,100,10,12,13\nbolt,beta,100,12,,\n")
        self.addCleanup(os.unlink, fh.name)
        responses = _mcp([
            _tool_call(1, "set_award_grid",
                       {"csv_path": fh.name, "increment_pct": 5}),
        ])
        result = json.loads(_tool_text(responses[1]))
        self.assertEqual(result["status"], "infeasible")
        self.assertIn("finer step", result["message"])

    def test_read_rules_reports_the_model(self):
        responses = _mcp([
            _tool_call(1, "read_rules", {"csv_path": TINY}),
        ])
        rules = json.loads(_tool_text(responses[1]))
        self.assertEqual([p["part"] for p in rules["parts"]], ["bolt", "nut"])
        alpha = rules["parts"][0]["quotes"][0]
        self.assertEqual((alpha["supplier"], alpha["capacity"],
                          alpha["share_max_pct"]), ("alpha", 12, 70))

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


@unittest.skipUnless(AVAILABLE, "requires SWI-Prolog + janus-swi")
class TestReport(unittest.TestCase):
    """`report` is the one command whose output leaves the machine, so these
    pin the things a recipient depends on: the file exists, it is standalone,
    and it says the same number as every other surface."""

    def test_writes_a_standalone_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "award.html")
            _, said, _ = _cli("report", TINY, "-o", out, expect=EXIT_OK)
            self.assertIn(out, said)
            html = pathlib.Path(out).read_text()
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("367", html)
        for forbidden in ("http://", "https://", "<script", "<img"):
            self.assertNotIn(forbidden, html)

    def test_goes_to_stdout_when_no_file_is_named(self):
        _, out, _ = _cli("report", TINY, "--no-trace", expect=EXIT_OK)
        self.assertTrue(out.lstrip().startswith("<!DOCTYPE html>"))

    def test_json_carries_the_same_decision_as_the_document(self):
        _, raw, _ = _cli("report", TINY, "--json", "--no-trace", expect=EXIT_OK)
        payload = json.loads(raw)
        self.assertEqual(payload["tco"], 367)
        self.assertEqual(payload["allocation"]["tco"], 367)
        self.assertEqual(payload["summary"]["awarded"], 367)
        self.assertTrue(payload["verdict"])
        self.assertTrue(payload["source"]["sha256"])
        self.assertIsNone(payload["trace"])

    def test_the_checksum_is_of_the_file_it_read(self):
        import hashlib
        _, raw, _ = _cli("report", TINY, "--json", "--no-trace", expect=EXIT_OK)
        expected = hashlib.sha256(pathlib.Path(TINY).read_bytes()).hexdigest()
        self.assertEqual(json.loads(raw)["source"]["sha256"], expected)

    def test_the_reasoning_section_is_included_by_default(self):
        _, raw, _ = _cli("report", TINY, "--json", expect=EXIT_OK)
        trace = json.loads(raw)["trace"]
        self.assertTrue(trace["phases"])
        self.assertIn("bolt", trace["parts"])

    def test_scenarios_are_included_when_asked_for(self):
        _, raw, _ = _cli(
            "report", TINY, "--json", "--no-trace",
            "--scenario", 'open_up:[{"remove": "min_suppliers(bolt,_)"}]',
            expect=EXIT_OK,
        )
        names = {r["name"] for r in json.loads(raw)["scenarios"]["results"]}
        self.assertEqual(names, {"baseline", "open_up"})

    def test_an_infeasible_model_still_gets_a_document(self):
        # The report is most valuable exactly here — it records which rule
        # is impossible — but the exit code must still say "no award".
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "broken.csv")
            with open(csv_path, "w") as fh:
                fh.write("part,supplier,demand,unit_cost,capacity,moq\n")
                fh.write("widget,alpha,100,10,50,80\n")   # MOQ 80 > capacity 50
            out = os.path.join(tmp, "award.html")
            code, _, _ = _cli("report", csv_path, "-o", out, "--no-trace")
            self.assertEqual(code, EXIT_NO_ANSWER)
            html = pathlib.Path(out).read_text()
        self.assertIn("No feasible award", html)

    def test_an_unwritable_path_fails_loudly(self):
        code, _, err = _cli("report", TINY, "-o", "/nonexistent/dir/award.html")
        self.assertEqual(code, EXIT_BAD_INPUT)
        self.assertIn("could not write", err)


@unittest.skipUnless(AVAILABLE, "requires SWI-Prolog + janus-swi")
class TestMCPWriteReport(unittest.TestCase):
    def test_writes_the_file_and_returns_only_a_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "award.html")
            responses = _mcp([_tool_call(1, "write_report", {
                "csv_path": TINY, "output_path": out, "include_trace": False,
            })])
            reply = json.loads(_tool_text(responses[1]))
            self.assertEqual(reply["written_to"], out)
            self.assertEqual(reply["tco"], 367)
            self.assertTrue(reply["say_to_user"])
            # The document must not come back through the agent's context.
            self.assertNotIn("<!DOCTYPE", _tool_text(responses[1]))
            self.assertTrue(
                pathlib.Path(out).read_text().startswith("<!DOCTYPE html>")
            )

    def test_a_missing_output_path_is_an_error(self):
        responses = _mcp([_tool_call(1, "write_report", {"csv_path": TINY})])
        self.assertTrue(responses[1]["result"]["isError"])


def _write_csv(case: unittest.TestCase, text: str) -> str:
    """A throwaway CSV that is removed when the test finishes."""
    fh = tempfile.NamedTemporaryFile(
        "w", suffix=".csv", delete=False, encoding="utf-8"
    )
    fh.write(text)
    fh.close()
    case.addCleanup(os.unlink, fh.name)
    return fh.name


#: A real-shaped sourcing event: an uppercase part number, a million
#: units, three suppliers with no capacity figures, dual sourcing, and a
#: low-cost supplier held to 20%. Every one of those tripped the tool the
#: first time a buyer used it.
MCU_EVENT = (
    "part,supplier,demand,unit_cost,share_min,share_max,dual_source\n"
    "ABC,infineon,1000000,100,,,1\n"
    "ABC,ti,1000000,89,,,\n"
    "ABC,CNS,1000000,80,0,20,\n"
)


@unittest.skipUnless(AVAILABLE, "SWI-Prolog / janus-swi not installed")
class TestAwardGrid(unittest.TestCase):
    """
    The award grid is on by default, so these pin the ways a default can go
    wrong: claiming more than it proved, and being WRONG where it should
    at worst be slow.
    """

    def test_default_grid_awards_the_mcu_event(self):
        # CNS takes its 20% ceiling at 80, ti the rest at 89.
        _, out, _ = _cli("solve", _write_csv(self, MCU_EVENT), "--json",
                         expect=EXIT_OK)
        self.assertEqual(json.loads(out)["tco"], 87_200_000)

    def test_grid_is_disclosed_on_stderr_and_json_stays_clean(self):
        """
        A gridded award is optimal ON THE GRID, which is a smaller claim
        than optimal — so a run has to admit it. It goes to stderr so it
        can never corrupt --json or a piped report.
        """
        _, out, err = _cli("solve", _write_csv(self, MCU_EVENT), "--json",
                           expect=EXIT_OK)
        self.assertIn("5% steps", err)
        json.loads(out)  # would raise if the note leaked into stdout

    def test_increment_zero_turns_the_grid_off(self):
        _, out, err = _cli("solve", TINY, "--increment", "0", "--json",
                           expect=EXIT_OK)
        self.assertEqual(err.strip(), "")
        self.assertEqual(json.loads(out)["tco"], 367)

    def test_a_step_that_does_not_divide_demand_rounds_instead_of_failing(self):
        """
        5% of 333 is 16.65 units. The grid used to demand an exact whole
        number and so reported "no award" for a model that plainly has
        one; each award now rounds to a whole unit.
        """
        csv = _write_csv(self, MCU_EVENT.replace("1000000", "333"))
        _, out, _ = _cli("solve", csv, "--json", expect=EXIT_OK)
        result = json.loads(out)
        self.assertEqual(result["tco"], 29_043)
        qty = sum(s["qty"] for s in result["allocations"][0]["suppliers"])
        self.assertEqual(qty, 333)

    def test_an_odd_million_is_gridded_too(self):
        # No percentage step divides 999,999 — this used to fall back to an
        # unbounded search and never return.
        csv = _write_csv(self, MCU_EVENT.replace("1000000", "999999"))
        _, out, _ = _cli("solve", csv, "--json", expect=EXIT_OK)
        # CNS: 20% of 999,999 is 199,999.8, so 199,999 at 80; ti: 800,000 at 89.
        self.assertEqual(json.loads(out)["tco"], 199_999 * 80 + 800_000 * 89)

    def test_a_small_part_is_not_made_worse_by_the_grid(self):
        # 5% of tiny.csv's parts is at most one unit, so the grid must not
        # cost anything: the exact optimum is 367.
        _, out, _ = _cli("solve", TINY, "--json", expect=EXIT_OK)
        self.assertEqual(json.loads(out)["tco"], 367)

    def test_the_default_grid_is_dropped_rather_than_blamed(self):
        """
        A 12-13% share band has no 5% level. The grid is a speed setting,
        not the buyer's rule, so it must not produce "no award satisfies
        every rule" — the search covers every quantity instead, and says so.
        """
        csv = _write_csv(self, (
            "part,supplier,demand,unit_cost,share_min,share_max\n"
            "bolt,alpha,100,10,12,13\n"
            "bolt,beta,100,12,,\n"
        ))
        _, out, err = _cli("solve", csv, "--json", expect=EXIT_OK)
        self.assertEqual(json.loads(out)["tco"], 13 * 10 + 87 * 12)
        self.assertIn("every quantity was searched", err)

    def test_a_grid_set_in_the_file_is_a_rule_and_stays(self):
        csv = _write_csv(self, (
            "part,supplier,demand,unit_cost,share_min,share_max,share_increment\n"
            "bolt,alpha,100,10,12,13,5\n"
            "bolt,beta,100,12,,,\n"
        ))
        _cli("solve", csv, "--increment", "0", expect=EXIT_NO_ANSWER)

    def test_a_step_that_does_not_divide_100_is_rejected(self):
        _, _, err = _cli("solve", TINY, "--increment", "7",
                         expect=EXIT_BAD_INPUT)
        self.assertIn("must divide 100", err)

    def test_the_report_states_the_grid_it_used(self):
        """
        The document outlives the conversation, so it cannot inherit a
        claim of proven optimality it did not earn.
        """
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "award.html")
            _cli("report", _write_csv(self, MCU_EVENT), "-o", out_path,
                 expect=EXIT_OK)
            html = pathlib.Path(out_path).read_text(encoding="utf-8")
        self.assertIn("5% steps, rounded to whole", html)
        self.assertNotIn("not an estimate, and not a heuristic", html)


@unittest.skipUnless(AVAILABLE, "SWI-Prolog / janus-swi not installed")
class TestRealisticEvents(unittest.TestCase):
    """
    The fixtures elsewhere are small and lower-case. Real sourcing data is
    neither, and that is where the tool used to hang or crash. These keep
    it honest on the shape of data a buyer actually has.
    """

    def _event(self, suppliers: int, demand: int) -> str:
        rows = [
            f"MCU-{demand},SUP{i},{demand},{100 - 3 * i},,"
            f"{'20' if i == suppliers - 1 else ''},{'1' if i == 0 else ''}\n"
            for i in range(suppliers)
        ]
        return _write_csv(self, (
            "part,supplier,demand,unit_cost,share_min,share_max,dual_source\n"
            + "".join(rows)
        ))

    def test_eight_suppliers_on_a_million_units_both_ways(self):
        """
        Exact and gridded both finish — this used to depend on which
        supplier's name sorted first — and here they agree, because the
        cheapest supplier's 20% cap lands on a step.
        """
        csv = self._event(8, 1_000_000)
        for increment in ("0", "5"):
            with self.subTest(increment=increment):
                _, out, _ = _cli("solve", csv, "--json",
                                 "--increment", increment, expect=EXIT_OK)
                self.assertEqual(json.loads(out)["tco"], 81_400_000)

    def test_exact_search_finishes_whatever_the_supplier_names(self):
        # Same model as MCU_EVENT with the grid off. It ran past two minutes
        # while an identical model with other names finished instantly.
        _, out, _ = _cli("solve", _write_csv(self, MCU_EVENT), "--json",
                         "--increment", "0", expect=EXIT_OK)
        self.assertEqual(json.loads(out)["tco"], 87_200_000)

    def test_the_trace_of_a_million_units_stays_readable(self):
        """
        Each snapshot used to list every value still open: 103 MB and 16
        seconds for this model, and the report embeds the trace. Ranges
        are summarised; the full list is kept only while it is short.
        """
        _, out, _ = _cli("trace", _write_csv(self, MCU_EVENT), expect=EXIT_OK)
        self.assertLess(len(out), 50_000)
        snapshot = json.loads(out.splitlines()[1])
        cns = next(v for v in snapshot["vars"] if v["name"] == "q.CNS.ABC")
        self.assertEqual((cns["min"], cns["max"], cns["size"]),
                         (0, 200_000, 200_001))
        self.assertNotIn("domain", cns)

    def test_a_short_range_still_lists_its_values(self):
        _, out, _ = _cli("trace", TINY, expect=EXIT_OK)
        snapshot = json.loads(out.splitlines()[1])
        first = snapshot["vars"][0]
        self.assertEqual(len(first["domain"]), first["size"])

    def test_uppercase_names_work_in_every_kind_of_override(self):
        scenarios = [
            {"name": "baseline", "overrides": []},
            {"name": "TI 70 / IFX 30", "overrides": [
                {"set": "share(ABC,ti,70,70)"},
                {"set": "share(ABC,infineon,30,30)"}]},
            {"name": "CNS +10%", "overrides": [
                {"cost_delta": ["CNS", "ABC", 10]}]},
            {"name": "no dual source", "overrides": [
                {"remove": "dual_source(ABC)"}]},
            {"name": "ABC -50%", "overrides": [
                {"demand_delta": ["ABC", -50]}]},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.json")
            pathlib.Path(path).write_text(json.dumps(scenarios))
            _, out, _ = _cli("scenarios", _write_csv(self, MCU_EVENT),
                             "--scenarios-file", path, "--json",
                             expect=EXIT_OK)
        tco = {r["name"]: r["tco"] for r in json.loads(out)["results"]}
        self.assertEqual(tco, {
            "baseline": 87_200_000,
            "TI 70 / IFX 30": 92_300_000,
            "CNS +10%": 88_800_000,
            "no dual source": 87_200_000,
            "ABC -50%": 43_600_000,
        })

    def test_a_wildcard_in_a_remove_template_still_matches_anything(self):
        csv = _write_csv(self, (
            "part,supplier,demand,unit_cost,share_max,dual_source,global_share_cap\n"
            "ABC,infineon,1000000,100,,1,\n"
            "ABC,ti,1000000,89,,,50\n"
            "ABC,CNS,1000000,80,20,,\n"
        ))
        scenarios = [{"name": "base"},
                     {"name": "uncapped", "overrides": [
                         {"remove": "max_global_share(ti,_)"}]}]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.json")
            pathlib.Path(path).write_text(json.dumps(scenarios))
            _, out, _ = _cli("scenarios", csv, "--scenarios-file", path,
                             "--json", expect=EXIT_OK)
        base, uncapped = json.loads(out)["results"]
        self.assertGreater(base["tco"], uncapped["tco"])

    def test_an_unknown_override_is_rejected_not_ignored(self):
        # It used to be dropped silently: a scenario that changed nothing,
        # reported as if it had.
        _, _, err = _cli("scenarios", _write_csv(self, MCU_EVENT),
                         "--scenario", 'typo:[{"cost_detla": ["CNS","ABC",10]}]',
                         expect=EXIT_BAD_INPUT)
        self.assertIn("is not an override", err)

    def test_a_decimal_percentage_is_rejected(self):
        _, _, err = _cli("scenarios", _write_csv(self, MCU_EVENT),
                         "--scenario", 'up:[{"cost_delta": ["CNS","ABC",2.5]}]',
                         expect=EXIT_BAD_INPUT)
        self.assertIn("whole numbers", err)

    def test_an_unreadable_fact_is_rejected_before_solving(self):
        _, _, err = _cli("scenarios", _write_csv(self, MCU_EVENT),
                         "--scenario", 'bad:[{"set": "share(ABC,ti,70"}]',
                         expect=EXIT_BAD_INPUT)
        self.assertIn("set needs", err)
        self.assertNotIn("Traceback", err)


@unittest.skipUnless(AVAILABLE, "SWI-Prolog / janus-swi not installed")
class TestSpreadsheetInput(unittest.TestCase):
    """
    Files that come out of Excel. Each of these used to fail with a Prolog
    message — or a bare "could not parse" — that named neither the cell
    nor the fix.
    """

    def test_titled_headings_are_read(self):
        csv = _write_csv(self, "Part,Supplier,Demand,Unit Cost\n"
                               "ABC,TI,100,89\nABC,CNS,100,80\n")
        _, out, _ = _cli("solve", csv, "--json", expect=EXIT_OK)
        self.assertEqual(json.loads(out)["tco"], 8000)

    def test_a_byte_order_mark_is_harmless(self):
        csv = _write_csv(self, "\ufeffpart,supplier,demand,unit_cost\r\n"
                               "ABC,TI,100,89\r\n")
        _, out, _ = _cli("solve", csv, "--json", expect=EXIT_OK)
        self.assertEqual(json.loads(out)["tco"], 8900)

    def test_a_short_row_names_its_line(self):
        csv = _write_csv(self, "part,supplier,demand,unit_cost,capacity\n"
                               "ABC,TI,100,89\n")
        _, _, err = _cli("solve", csv, expect=EXIT_BAD_INPUT)
        self.assertIn("line 2 has 4 values but the header has 5", err)

    def test_formatted_numbers_name_the_cell(self):
        csv = _write_csv(self, 'part,supplier,demand,unit_cost\n'
                               'ABC,TI,"1,000,000",89\n')
        _, _, err = _cli("solve", csv, expect=EXIT_BAD_INPUT)
        self.assertIn("demand for TI/ABC is '1,000,000'", err)

    def test_a_file_without_part_and_supplier_says_so(self):
        csv = _write_csv(self, "item,vendor,qty\nABC,TI,100\n")
        _, _, err = _cli("solve", csv, expect=EXIT_BAD_INPUT)
        self.assertIn("needs part and supplier columns", err)
        self.assertIn("found: item, vendor, qty", err)


@unittest.skipUnless(AVAILABLE, "SWI-Prolog / janus-swi not installed")
class TestRules(unittest.TestCase):
    """The model read back, so a sign-off is on the rules that run."""

    def test_reads_back_what_the_buyer_wrote(self):
        _, out, err = _cli("rules", _write_csv(self, MCU_EVENT),
                           expect=EXIT_OK)
        self.assertIn("ABC — buy 1,000,000", out)
        self.assertIn("at least 2 suppliers (dual sourcing)", out)
        self.assertIn("at most 20% of the part", out)
        self.assertIn("awards in 5% steps", out)
        self.assertEqual(err, "")  # nothing is solved, so nothing to qualify

    def test_shows_what_the_file_implies_but_does_not_say(self):
        # supplier2 quotes 10 but carries a +3 adjustment; the solver prices
        # it at 13, and a buyer signing off should see that.
        _, out, _ = _cli("rules", SAMPLE, "--increment", "0", expect=EXIT_OK)
        self.assertIn("effective 13", out)
        self.assertIn("one-off 2,000 if awarded", out)
        self.assertIn("at most 40% of total volume", out)

    def test_names_the_reason_a_supplier_is_excluded(self):
        csv = _write_csv(self, (
            "part,supplier,demand,unit_cost,otif,min_otif\n"
            "ABC,TI,100,10,85,90\n"
            "ABC,CNS,100,12,95,\n"
        ))
        _, out, _ = _cli("rules", csv, expect=EXIT_OK)
        self.assertIn("EXCLUDED — on-time delivery is 85%, below the "
                      "required 90%", out)

    def test_json_carries_real_booleans(self):
        _, out, _ = _cli("rules", _write_csv(self, MCU_EVENT), "--json",
                         expect=EXIT_OK)
        part = json.loads(out)["parts"][0]
        self.assertIs(part["dual_source"], True)
        self.assertIs(part["quotes"][0]["qualified"], True)


if __name__ == "__main__":
    unittest.main()
