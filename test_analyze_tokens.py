#!/usr/bin/env python3

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import analyze_tokens as analyzer


ROOT = Path(__file__).resolve().parent


class TokenAnalyzerTests(unittest.TestCase):
    def test_iris_v2_golden_fixture(self):
        parsed = analyzer.parse_iris_usage(ROOT / "fixtures" / "iris_usage.v2.json")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["schema_version"], 2)
        self.assertEqual(parsed["totals"]["input_full"], 14_700)
        self.assertEqual(parsed["totals"]["tools"], 2)
        self.assertEqual(parsed["warnings"], [])

    def test_real_emitter_v2_without_schema_version_is_not_downgraded(self):
        # Reproduces actual src/print.rs output: no `schema_version` field, and
        # a `totals` block using v1-style names (input_tokens, cache_*_input_*).
        # Must be detected as v2 (populated timeline + base), not legacy.
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "iris_usage.json"
            path.write_text(json.dumps({
                "provider": "anthropic",
                "model": "claude-sonnet-5",
                "base": {
                    "system_prompt_tokens": 90,
                    "tools": [{"name": "read", "schema_tokens": 10}],
                    "tools_total_tokens": 10,
                    "base_total_tokens": 100,
                },
                "turns": [
                    {"i": 0, "fresh": 10, "cache_read": 80, "cache_write": 10,
                     "output": 5, "reasoning": 0, "input_full": 100,
                     "duration_ms": 100, "ttft_ms": 10, "stop_reason": "end_turn"},
                ],
                "tools": [{"i": 0, "turn": 0, "name": "read", "call_id": "c1"}],
                # v1-style totals names, exactly as the emitter serializes them.
                "totals": {
                    "provider_turns": 1,
                    "input_tokens": 100,
                    "output_tokens": 5,
                    "reasoning_output_tokens": 0,
                    "cache_read_input_tokens": 80,
                    "cache_write_input_tokens": 10,
                    "tool_calls": 1,
                },
            }))
            parsed = analyzer.parse_iris_usage(path)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["schema_version"], 2)
        self.assertFalse(parsed["legacy"])
        self.assertEqual(len(parsed["turns"]), 1)
        self.assertEqual(parsed["totals"]["input_full"], 100)
        # v1-style totals reconcile with the timeline: no mismatch warnings.
        self.assertEqual(parsed["warnings"], [])

    def test_legacy_iris_has_totals_but_no_timeline_or_cost(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
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

    def test_reward_falls_back_to_legacy_top_level_fields(self):
        for field in ("reward", "score"):
            with self.subTest(field=field), tempfile.TemporaryDirectory(dir=ROOT) as directory:
                trial = Path(directory)
                (trial / "result.json").write_text(json.dumps({"task_name": "legacy", field: 0.75}))
                task, reward, _ = analyzer.task_and_reward(trial)
                self.assertEqual(task, "legacy")
                self.assertEqual(reward, 0.75)

    def test_cc_atif_output_correction_clears_final_metrics_mismatch(self):
        usage = {
            "input_tokens": 2,
            "cache_read_input_tokens": 80,
            "cache_creation_input_tokens": 18,
            "output_tokens": 5,
        }
        event = {"type": "assistant", "message": {"id": "m1", "usage": usage, "content": []}}
        trajectory = {
            "schema_version": "ATIF-v1.7",
            "agent": {"model_name": "claude-sonnet-5"},
            "steps": [{"source": "agent", "metrics": {"completion_tokens": 20}}],
            "final_metrics": {
                "total_prompt_tokens": 100,
                "total_completion_tokens": 20,
                "extra": {
                    "total_cache_read_input_tokens": 80,
                    "total_cache_creation_input_tokens": 18,
                },
            },
        }
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            trial = Path(directory)
            agent = trial / "agent"
            agent.mkdir()
            (agent / "claude-code.txt").write_text(json.dumps(event) + "\n")
            (agent / "trajectory.json").write_text(json.dumps(trajectory))
            parsed = analyzer.parse_cc_trial(trial)
        self.assertEqual(parsed["totals"]["output"], 20)
        self.assertFalse(any("does not match final_metrics" in warning for warning in parsed["warnings"]))

    def test_cc_usage_deduplicates_usage_and_tools_by_message_and_call_id(self):
        usage = {"input_tokens": 2, "cache_read_input_tokens": 80, "cache_creation_input_tokens": 18, "output_tokens": 7}
        message_start = {"type": "assistant", "message": {"id": "m1", "usage": usage, "content": []}}
        message_final = {"type": "assistant", "message": {"id": "m1", "usage": usage, "content": [{"type": "tool_use", "id": "tool-1", "name": "Read", "input": {"file_path": "x"}}]}}
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
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

    def test_steady_state_cache_read_excludes_cold_turn1(self):
        # Cold turn 1 (all fresh+write, no read) drags the overall cache-read%
        # down; turns 2..N are warm. Excluding turn 1 must jump to near-parity,
        # demonstrating a cold-start artifact rather than a breakpoint problem.
        metrics = {
            "model": "unknown",
            "legacy": False,
            "base": {"base_total_tokens": 100},
            "turns": [
                {"fresh": 100, "cache_read": 0, "cache_write": 900, "output": 5, "input_full": 1000},
                {"fresh": 20, "cache_read": 950, "cache_write": 30, "output": 5, "input_full": 1000},
                {"fresh": 20, "cache_read": 950, "cache_write": 30, "output": 5, "input_full": 1000},
            ],
            "totals": {"turns": 3, "input_full": 3000},
        }
        analyzer.enrich_metrics(metrics)
        self.assertAlmostEqual(metrics["totals"]["cache_read_pct"], 100 * 1900 / 3000)
        self.assertAlmostEqual(metrics["totals"]["cache_read_pct_ex_turn1"], 95.0)
        per_turn = [t["cache_read_pct"] for t in metrics["turns"]]
        self.assertEqual(per_turn[0], 0.0)
        self.assertAlmostEqual(per_turn[1], 95.0)
        self.assertAlmostEqual(per_turn[2], 95.0)

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


class TokenAnalyzerEndToEndTests(unittest.TestCase):
    @staticmethod
    def write_result(trial, task, reward, exception=None):
        result = {"task_name": task, "exception_info": exception}
        if reward is not None:
            result["verifier_result"] = {"rewards": {"reward": reward}}
        (trial / "result.json").write_text(json.dumps(result))

    @staticmethod
    def write_iris_trial(job, task, suffix, reward, turns=None, legacy=False, exception=None, log=None):
        trial = job / f"{task}__{suffix}"
        agent = trial / "agent"
        agent.mkdir(parents=True)
        TokenAnalyzerEndToEndTests.write_result(trial, task, reward, exception)
        if log:
            (trial / "trial.log").write_text(log)
        if legacy:
            usage = {
                "provider": "anthropic",
                "model": "claude-sonnet-5",
                "provider_turns": 1,
                "input_tokens": 100,
                "output_tokens": 10,
                "cache_read_input_tokens": 80,
                "cache_write_input_tokens": 10,
                "tool_calls": 1,
            }
        else:
            turns = turns or [(10, 80, 10, 5), (20, 100, 30, 10)]
            normalized = []
            for index, (fresh, read, write, output) in enumerate(turns, 1):
                normalized.append({
                    "i": index,
                    "fresh": fresh,
                    "cache_read": read,
                    "cache_write": write,
                    "output": output,
                    "reasoning": 0,
                    "input_full": fresh + read + write,
                    "duration_ms": 100,
                    "ttft_ms": 10,
                    "stop_reason": "end_turn" if index == len(turns) else "tool_use",
                })
            usage = {
                "schema_version": 2,
                "provider": "anthropic",
                "model": "claude-sonnet-5",
                "base": {
                    "system_prompt_tokens": 90,
                    "tools": [{"name": "read", "schema_tokens": 10}],
                    "tools_total_tokens": 10,
                    "base_total_tokens": 100,
                },
                "turns": normalized,
                "tools": [{"i": 1, "turn": 1, "name": "read", "call_id": f"iris-{suffix}"}],
                "totals": {
                    "fresh": sum(t[0] for t in turns),
                    "cache_read": sum(t[1] for t in turns),
                    "cache_write": sum(t[2] for t in turns),
                    "output": sum(t[3] for t in turns),
                    "reasoning": 0,
                    "input_full": sum(sum(t[:3]) for t in turns),
                },
            }
        (agent / "iris_usage.json").write_text(json.dumps(usage))
        return trial

    @staticmethod
    def write_cc_trial(job, task, suffix, reward, turns=None):
        turns = turns or [(10, 80, 10, 5), (20, 100, 30, 10)]
        trial = job / f"{task}__{suffix}"
        agent = trial / "agent"
        agent.mkdir(parents=True)
        TokenAnalyzerEndToEndTests.write_result(trial, task, reward)
        events = []
        steps = []
        for index, (fresh, read, write, output) in enumerate(turns, 1):
            usage = {
                "input_tokens": fresh,
                "cache_read_input_tokens": read,
                "cache_creation_input_tokens": write,
                "output_tokens": 1,
            }
            content = ([{"type": "tool_use", "id": f"cc-{suffix}", "name": "Read", "input": {"file_path": "x"}}]
                       if index == 1 else [{"type": "text", "text": "done"}])
            start = {"type": "assistant", "message": {"id": f"{suffix}-{index}", "usage": usage, "content": []}}
            final = {"type": "assistant", "message": {"id": f"{suffix}-{index}", "usage": usage, "content": content}}
            events.extend((start, final))
            steps.append({"source": "agent", "metrics": {"completion_tokens": output}})
        (agent / "claude-code.txt").write_text("\n".join(json.dumps(event) for event in events) + "\n")
        trajectory = {
            "schema_version": "ATIF-v1.7",
            "agent": {"model_name": "claude-sonnet-5"},
            "steps": steps,
            "final_metrics": {
                "total_prompt_tokens": sum(sum(t[:3]) for t in turns),
                "total_completion_tokens": sum(t[3] for t in turns),
                "total_steps": len(turns),
                "extra": {
                    "total_cache_read_input_tokens": sum(t[1] for t in turns),
                    "total_cache_creation_input_tokens": sum(t[2] for t in turns),
                },
            },
        }
        (agent / "trajectory.json").write_text(json.dumps(trajectory))
        return trial

    def test_cli_builds_filtered_reports_distributions_costs_and_exclusions(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            iris_job = root / "iris-job"
            cc_job = root / "cc-job"
            iris_job.mkdir()
            cc_job.mkdir()

            self.write_iris_trial(iris_job, "shared", "i1", 1.0)
            self.write_iris_trial(iris_job, "shared", "i2", 1.0, [(10, 80, 10, 5), (30, 120, 50, 20)])
            self.write_cc_trial(cc_job, "shared", "c1", 1.0)
            self.write_cc_trial(cc_job, "shared", "c2", 1.0, [(10, 80, 10, 5), (30, 120, 50, 20)])
            self.write_iris_trial(iris_job, "legacy", "i1", 1.0, legacy=True)
            self.write_cc_trial(cc_job, "legacy", "c1", 1.0, [(10, 80, 10, 10)])
            self.write_iris_trial(iris_job, "iris-only", "i1", 1.0)
            self.write_cc_trial(cc_job, "iris-only", "c1", 0.0)
            self.write_iris_trial(iris_job, "timeout-task", "i1", 0.0, log="agent timed out")
            self.write_cc_trial(cc_job, "timeout-task", "c1", 1.0)
            self.write_iris_trial(iris_job, "infra-task", "i1", 0.0, exception={"type": "DockerError"})
            self.write_cc_trial(cc_job, "infra-task", "c1", 1.0)

            markdown = root / "report.md"
            json_report = root / "report.json"
            completed = subprocess.run(
                [sys.executable, str(ROOT / "analyze_tokens.py"), str(iris_job), str(cc_job),
                 "--output", str(markdown), "--json", str(json_report)],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            report = markdown.read_text()
            data = json.loads(json_report.read_text())

        self.assertIn("# Harness token-efficiency comparison", completed.stdout)
        self.assertEqual(completed.stdout.rstrip(), report.rstrip())
        self.assertEqual(data["both_solved_tasks"], ["legacy", "shared"])
        self.assertIn("| shared | iris | 2 |", report)
        self.assertEqual(data["aggregates"]["iris"]["input_full"]["n"], 3)

        first_iris = next(a for a in data["attempts"] if a["trial"] == "shared__i1")
        self.assertEqual(first_iris["metrics"]["totals"]["input_full"], 250)
        self.assertEqual(first_iris["metrics"]["totals"]["input_beyond_base"], 50)
        # Sonnet-5 intro rates: fresh 30*$2 + read 180*$0.20 + write 40*$2.50 +
        # output 15*$10 = $0.000346; cold re-prices turn-0 read (80) at write rate:
        # +80*($2.50-$0.20) = +$0.000184 -> $0.000530.
        self.assertAlmostEqual(first_iris["metrics"]["totals"]["cost_actual"], 0.000346)
        self.assertAlmostEqual(first_iris["metrics"]["totals"]["cost_cold"], 0.000530)

        warnings = "\n".join(data["warnings"])
        self.assertIn("legacy iris usage report", warnings)
        self.assertIn("used ATIF per-step completion_tokens", warnings)
        self.assertNotIn("does not match final_metrics", warnings)

        failed_exclusions = {
            (row["task"], row["harness"]): row["category"]
            for row in data["exclusions"]
            if row["harness"] == "iris" or row["task"] == "iris-only"
        }
        self.assertEqual(failed_exclusions[("iris-only", "claude-code")], "capability")
        self.assertEqual(failed_exclusions[("timeout-task", "iris")], "timeout")
        self.assertEqual(failed_exclusions[("infra-task", "iris")], "infra")
        excluded_cc = next(line for line in report.splitlines() if line.startswith("| iris-only | claude-code"))
        self.assertIn("| - | - | - | - | - | - | 0.00 | - | - |", excluded_cc)


if __name__ == "__main__":
    unittest.main()
