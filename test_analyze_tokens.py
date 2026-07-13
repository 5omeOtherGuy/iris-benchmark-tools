#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path

import analyze_tokens as analyzer


WORK = Path("/mnt/bench/work")


class TokenAnalyzerTests(unittest.TestCase):
    def test_iris_v2_golden_fixture(self):
        parsed = analyzer.parse_iris_usage(WORK / "fixtures" / "iris_usage.v2.json")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["schema_version"], 2)
        self.assertEqual(parsed["totals"]["input_full"], 14_700)
        self.assertEqual(parsed["totals"]["tools"], 2)
        self.assertEqual(parsed["warnings"], [])

    def test_legacy_iris_has_totals_but_no_timeline_or_cost(self):
        with tempfile.TemporaryDirectory(dir=WORK) as directory:
            path = Path(directory) / "usage.json"
            path.write_text(json.dumps({
                "provider_turns": 2,
                "input_tokens": 100,
                "output_tokens": 10,
                "cache_read_input_tokens": 80,
                "cache_write_input_tokens": 15,
                "model": "claude-sonnet-5",
            }))
            parsed = analyzer.parse_iris_usage(path)
            analyzer.enrich_metrics(parsed)
        self.assertTrue(parsed["legacy"])
        self.assertEqual(parsed["totals"]["input_full"], 100)
        self.assertEqual(parsed["turns"], [])
        self.assertIsNone(parsed["totals"]["cost_actual"])
        self.assertIn("legacy", parsed["warnings"][0])

    def test_cc_usage_deduplicates_usage_and_tools_by_message_and_call_id(self):
        usage = {"input_tokens": 2, "cache_read_input_tokens": 80, "cache_creation_input_tokens": 18, "output_tokens": 7}
        message_start = {"type": "assistant", "message": {"id": "m1", "usage": usage, "content": []}}
        message_final = {"type": "assistant", "message": {"id": "m1", "usage": usage, "content": [{"type": "tool_use", "id": "tool-1", "name": "Read", "input": {"file_path": "x"}}]}}
        with tempfile.TemporaryDirectory(dir=WORK) as directory:
            path = Path(directory) / "claude-code.txt"
            path.write_text("\n".join(json.dumps(x) for x in (message_start, message_final, message_final)))
            turns, tools, warnings = analyzer.cc_usage_records(path)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["input_full"], 100)
        self.assertEqual(turns[0]["output"], 7)
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["turn"], 1)
        self.assertEqual(warnings, [])

    def test_both_solved_filter_requires_each_harness_to_solve(self):
        attempts = [
            {"task": "both", "harness": "iris", "solved": True},
            {"task": "both", "harness": "claude-code", "solved": True},
            {"task": "iris-only", "harness": "iris", "solved": True},
            {"task": "iris-only", "harness": "claude-code", "solved": False},
            {"task": "cc-only", "harness": "iris", "solved": False},
            {"task": "cc-only", "harness": "claude-code", "solved": True},
        ]
        self.assertEqual(analyzer.both_solved_tasks(attempts), {"both"})

    def test_base_netting(self):
        metrics = {
            "model": "unknown",
            "legacy": False,
            "base": {"base_total_tokens": 100},
            "turns": [{"fresh": 0, "cache_read": 0, "cache_write": 0, "output": 0}],
            "totals": {"turns": 3, "input_full": 450},
        }
        analyzer.enrich_metrics(metrics)
        self.assertEqual(metrics["totals"]["input_beyond_base"], 150)

    def test_cost_and_cold_normalization(self):
        rates = {"input": 2.0, "output": 10.0, "cache_write": 2.5, "cache_read": 0.2}
        turns = [
            {"fresh": 100, "cache_read": 1_000, "cache_write": 50, "output": 10},
            {"fresh": 200, "cache_read": 900, "cache_write": 100, "output": 20},
        ]
        actual, cold = analyzer.calculate_cost(turns, rates)
        expected_actual = (300 * 2.0 + 1_900 * 0.2 + 150 * 2.5 + 30 * 10.0) / 1_000_000
        expected_cold = expected_actual + 1_000 * (2.5 - 0.2) / 1_000_000
        self.assertAlmostEqual(actual, expected_actual)
        self.assertAlmostEqual(cold, expected_cold)

    def test_k_aggregation_statistics(self):
        stats = analyzer.distribution([1, 2, 3, 4])
        self.assertEqual(stats["n"], 4)
        self.assertEqual(stats["mean"], 2.5)
        self.assertEqual(stats["median"], 2.5)
        self.assertEqual(stats["min"], 1)
        self.assertEqual(stats["max"], 4)
        self.assertAlmostEqual(stats["stdev"], 1.2909944487358056)


if __name__ == "__main__":
    unittest.main()
