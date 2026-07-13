#!/usr/bin/env python3
"""Compare iris and Claude Code token efficiency from completed Harbor jobs.

Usage:
    analyze_tokens.py IRIS_JOB_DIR CLAUDE_CODE_JOB_DIR [-o REPORT.md]
                      [--json REPORT.json]

The comparison includes token/cost data only for tasks with at least one solved
attempt on both harnesses. Unsolved and environmental failures remain visible
in the per-attempt table and exclusion taxonomy.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# VERIFY/UPDATE as of 2026-07-13. Rates are USD per million tokens.
# cache_write/cache_read intentionally derive from input so editing one input
# rate preserves the requested 1.25x/0.10x relationship.
PRICING = {
    "claude-sonnet-5": {
        "input": 3.00,
        "output": 30.00,
        "cache_write": 3.00 * 1.25,
        "cache_read": 3.00 * 0.10,
    }
}
PRICING_AS_OF = "2026-07-13 (VERIFY/UPDATE)"
HIGH_VARIANCE_CV = 0.20

Number = int | float


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def number(value: Any, default: Number = 0) -> Number:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def task_and_reward(trial_dir: Path) -> tuple[str, float | None, dict[str, Any]]:
    result = load_json(trial_dir / "result.json")
    result = result if isinstance(result, dict) else {}
    task = result.get("task_name") or trial_dir.name.rsplit("__", 1)[0]
    reward = None
    verifier_result = result.get("verifier_result")
    rewards = verifier_result.get("rewards") if isinstance(verifier_result, dict) else None
    if isinstance(rewards, dict) and isinstance(rewards.get("reward"), (int, float)):
        reward = float(rewards["reward"])
    if reward is None:
        try:
            reward = float((trial_dir / "verifier" / "reward.txt").read_text().strip())
        except (OSError, ValueError):
            pass
    return str(task), reward, result


def sum_turns(turns: list[dict[str, Any]], key: str) -> Number:
    return sum(number(turn.get(key)) for turn in turns)


def totals_from_turns(turns: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Number]:
    return {
        "turns": len(turns),
        "fresh": sum_turns(turns, "fresh"),
        "cache_read": sum_turns(turns, "cache_read"),
        "cache_write": sum_turns(turns, "cache_write"),
        "input_full": sum_turns(turns, "input_full"),
        "output": sum_turns(turns, "output"),
        "reasoning": sum_turns(turns, "reasoning"),
        "tools": len(tools),
    }


def normalize_turn(raw: dict[str, Any], index: int) -> dict[str, Any]:
    fresh = number(raw.get("fresh"))
    cache_read = number(raw.get("cache_read"))
    cache_write = number(raw.get("cache_write"))
    computed_full = fresh + cache_read + cache_write
    return {
        "i": int(number(raw.get("i"), index)),
        "fresh": fresh,
        "cache_read": cache_read,
        "cache_write": cache_write,
        "output": number(raw.get("output")),
        "reasoning": number(raw.get("reasoning")),
        "input_full": number(raw.get("input_full"), computed_full),
        "duration_ms": raw.get("duration_ms"),
        "ttft_ms": raw.get("ttft_ms"),
        "stop_reason": raw.get("stop_reason"),
    }


def parse_iris_usage(path: Path) -> dict[str, Any] | None:
    usage = load_json(path)
    if not isinstance(usage, dict):
        return None

    warnings: list[str] = []
    schema = usage.get("schema_version")
    if schema not in (2, "2", "v2"):
        warnings.append("legacy iris usage report: totals only; per-turn/base/cost unavailable")
        totals = {
            "turns": usage.get("provider_turns"),
            "fresh": None,
            "cache_read": usage.get("cache_read_input_tokens"),
            "cache_write": usage.get("cache_write_input_tokens"),
            "input_full": usage.get("input_tokens"),
            "output": usage.get("output_tokens"),
            "reasoning": usage.get("reasoning_output_tokens"),
            "tools": usage.get("tool_calls"),
        }
        return {
            "schema_version": schema or 1,
            "provider": usage.get("provider"),
            "model": usage.get("model"),
            "base": None,
            "turns": [],
            "tools": [],
            "totals": totals,
            "legacy": True,
            "warnings": warnings,
        }

    raw_turns = usage.get("turns")
    raw_tools = usage.get("tools")
    if not isinstance(raw_turns, list) or not isinstance(raw_tools, list):
        warnings.append("invalid iris v2 report: turns/tools must be arrays")
        return None
    turns = [normalize_turn(t, i) for i, t in enumerate(raw_turns, 1) if isinstance(t, dict)]
    tools = [dict(t) for t in raw_tools if isinstance(t, dict)]
    for turn in turns:
        expected = turn["fresh"] + turn["cache_read"] + turn["cache_write"]
        if turn["input_full"] != expected:
            warnings.append(f"iris turn {turn['i']} input_full mismatch: {turn['input_full']} != {expected}")

    base = usage.get("base") if isinstance(usage.get("base"), dict) else {}
    base_total = base.get("base_total_tokens")
    if not isinstance(base_total, (int, float)):
        warnings.append("iris v2 base_total_tokens missing; base-netted metrics unavailable")
        base_total = None
    normalized_base = dict(base)
    normalized_base["base_total_tokens"] = base_total
    totals = totals_from_turns(turns, tools)
    reported = usage.get("totals") if isinstance(usage.get("totals"), dict) else {}
    for key in ("fresh", "cache_read", "cache_write", "input_full", "output", "reasoning"):
        if isinstance(reported.get(key), (int, float)) and totals[key] != reported[key]:
            warnings.append(f"iris totals.{key} mismatch: timeline={totals[key]} reported={reported[key]}")
    return {
        "schema_version": 2,
        "provider": usage.get("provider"),
        "model": usage.get("model"),
        "base": normalized_base,
        "turns": turns,
        "tools": tools,
        "totals": totals,
        "legacy": False,
        "warnings": warnings,
    }


def cc_usage_records(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Extract one usage turn per message id and deduplicated tool calls."""
    warnings: list[str] = []
    by_message: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    tools_by_id: dict[str, dict[str, Any]] = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return [], [], ["claude-code.txt missing"]

    for line_number, line in enumerate(lines, 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            warnings.append(f"claude-code.txt line {line_number}: invalid JSON ignored")
            continue
        if not isinstance(event, dict) or event.get("type") != "assistant":
            continue
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        message_id = str(message.get("id") or event.get("request_id") or f"line-{line_number}")
        raw_usage = message.get("usage")
        if isinstance(raw_usage, dict):
            turn = {
                "message_id": message_id,
                "fresh": number(raw_usage.get("input_tokens")),
                "cache_read": number(raw_usage.get("cache_read_input_tokens")),
                "cache_write": number(raw_usage.get("cache_creation_input_tokens")),
                "output": number(raw_usage.get("output_tokens")),
                "reasoning": 0,
                "duration_ms": None,
                "ttft_ms": None,
                "stop_reason": message.get("stop_reason"),
            }
            turn["input_full"] = turn["fresh"] + turn["cache_read"] + turn["cache_write"]
            if message_id not in by_message:
                by_message[message_id] = turn
                order.append(message_id)
            else:
                old = {k: by_message[message_id][k] for k in ("fresh", "cache_read", "cache_write", "output")}
                new = {k: turn[k] for k in old}
                if old != new:
                    warnings.append(f"Claude Code message {message_id} emitted conflicting usage; using final record")
                    by_message[message_id] = turn
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                call_id = str(block.get("id") or f"{message_id}-{len(tools_by_id) + 1}")
                tools_by_id[call_id] = {
                    "turn_message_id": message_id,
                    "name": block.get("name") or "?",
                    "call_id": call_id,
                    "input": block.get("input"),
                }

    turns = []
    message_to_turn = {}
    for i, message_id in enumerate(order, 1):
        turn = by_message[message_id]
        turn["i"] = i
        turns.append(turn)
        message_to_turn[message_id] = i
    tools = []
    for i, tool in enumerate(tools_by_id.values(), 1):
        tool["i"] = i
        tool["turn"] = message_to_turn.get(tool.pop("turn_message_id"))
        tools.append(tool)
    return turns, tools, warnings


def expected_cc_totals(final_metrics: dict[str, Any]) -> dict[str, Number]:
    extra = final_metrics.get("extra") if isinstance(final_metrics.get("extra"), dict) else {}
    cache_read = number(extra.get("total_cache_read_input_tokens"), number(final_metrics.get("total_cached_tokens")))
    cache_write = number(extra.get("total_cache_creation_input_tokens"))
    input_full = number(final_metrics.get("total_prompt_tokens"))
    return {
        "fresh": input_full - cache_read - cache_write,
        "cache_read": cache_read,
        "cache_write": cache_write,
        "input_full": input_full,
        "output": number(final_metrics.get("total_completion_tokens")),
    }


def parse_cc_trial(trial_dir: Path) -> dict[str, Any] | None:
    trajectory = load_json(trial_dir / "agent" / "trajectory.json")
    if not isinstance(trajectory, dict):
        return None
    final_metrics = trajectory.get("final_metrics")
    if not isinstance(final_metrics, dict):
        return None
    turns, tools, warnings = cc_usage_records(trial_dir / "agent" / "claude-code.txt")
    expected = expected_cc_totals(final_metrics)
    observed = totals_from_turns(turns, tools)
    mismatches = [key for key in expected if observed[key] != expected[key]]
    if mismatches:
        details = ", ".join(f"{key} {observed[key]} != {expected[key]}" for key in mismatches)
        warnings.append(f"Claude Code deduped usage does not match final_metrics: {details}")

    # Claude Code 2.1.207's stream omits hidden reasoning from output_tokens.
    # ATIF step metrics are authoritative when they map one-to-one to turns.
    agent_steps = [s for s in trajectory.get("steps", []) if isinstance(s, dict) and s.get("source") == "agent"]
    if observed["output"] != expected["output"] and len(agent_steps) == len(turns):
        step_outputs = [number((s.get("metrics") or {}).get("completion_tokens")) for s in agent_steps]
        if sum(step_outputs) == expected["output"]:
            for turn, output in zip(turns, step_outputs):
                turn["output"] = output
            warnings.append("Claude Code stream output omitted hidden tokens; used ATIF per-step completion_tokens")
    observed = totals_from_turns(turns, tools)
    base_total = turns[0]["input_full"] if turns else None
    agent = trajectory.get("agent") if isinstance(trajectory.get("agent"), dict) else {}
    return {
        "schema_version": trajectory.get("schema_version"),
        "provider": None,
        "model": agent.get("model_name"),
        "base": {"base_total_tokens": base_total} if base_total is not None else None,
        "turns": turns,
        "tools": tools,
        "totals": observed,
        "legacy": False,
        "reported_cost_usd": final_metrics.get("total_cost_usd"),
        "warnings": warnings,
    }


def pricing_for(model: Any, table: dict[str, dict[str, float]] = PRICING) -> dict[str, float] | None:
    if model in table:
        return table[model]
    if isinstance(model, str):
        short = model.rsplit("/", 1)[-1]
        return table.get(short)
    return None


def calculate_cost(turns: list[dict[str, Any]], rates: dict[str, float]) -> tuple[float, float]:
    actual = 0.0
    cold = 0.0
    for index, turn in enumerate(turns):
        fresh = number(turn.get("fresh"))
        read = number(turn.get("cache_read"))
        write = number(turn.get("cache_write"))
        output = number(turn.get("output"))
        actual += fresh * rates["input"] + read * rates["cache_read"] + write * rates["cache_write"] + output * rates["output"]
        cold_read_rate = rates["cache_write"] if index == 0 else rates["cache_read"]
        cold += fresh * rates["input"] + read * cold_read_rate + write * rates["cache_write"] + output * rates["output"]
    return actual / 1_000_000, cold / 1_000_000


def enrich_metrics(metrics: dict[str, Any]) -> None:
    totals = metrics["totals"]
    turns = totals.get("turns")
    base = metrics.get("base") or {}
    base_total = base.get("base_total_tokens")
    if isinstance(totals.get("input_full"), (int, float)) and isinstance(turns, (int, float)) and isinstance(base_total, (int, float)):
        totals["input_beyond_base"] = totals["input_full"] - base_total * turns
    else:
        totals["input_beyond_base"] = None
    rates = pricing_for(metrics.get("model"))
    if not metrics.get("legacy") and metrics.get("turns") and rates:
        actual, cold = calculate_cost(metrics["turns"], rates)
        totals["cost_actual"] = actual
        totals["cost_cold"] = cold
    else:
        totals["cost_actual"] = None
        totals["cost_cold"] = None


def failure_reason(trial_dir: Path, result: dict[str, Any], reward: float | None, metrics: dict[str, Any] | None) -> tuple[str, str]:
    text_parts = [json.dumps(result, default=str)]
    for path in (trial_dir / "exception.txt", trial_dir / "trial.log"):
        try:
            text_parts.append(path.read_text(errors="replace"))
        except OSError:
            pass
    text = "\n".join(text_parts).lower()
    if "glibc_2.39" in text or "glibc 2.39" in text or ("glibc" in text and "2.39" in text):
        return "environment", "iris glibc<2.39 install failure"
    if "timeout" in text or "timed out" in text:
        return "timeout", "agent timeout"
    if result.get("exception_info") or metrics is None or reward is None:
        return "infra", "infra/error or missing telemetry"
    return "capability", "task not solved"


def scan_job(job_dir: Path, harness: str) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for trial_dir in sorted(job_dir.iterdir() if job_dir.is_dir() else []):
        if not trial_dir.is_dir() or not (trial_dir / "result.json").exists():
            continue
        task, reward, result = task_and_reward(trial_dir)
        metrics = parse_iris_usage(trial_dir / "agent" / "iris_usage.json") if harness == "iris" else parse_cc_trial(trial_dir)
        if metrics:
            enrich_metrics(metrics)
        solved = reward is not None and reward >= 1.0
        category = detail = None
        if not solved:
            category, detail = failure_reason(trial_dir, result, reward, metrics)
        attempts.append({
            "task": task,
            "harness": harness,
            "trial": trial_dir.name,
            "reward": reward,
            "solved": solved,
            "metrics": metrics,
            "exclusion_category": category,
            "exclusion_reason": detail,
        })
    return attempts


def both_solved_tasks(attempts: list[dict[str, Any]]) -> set[str]:
    solved: dict[str, set[str]] = defaultdict(set)
    for attempt in attempts:
        if attempt["solved"]:
            solved[attempt["task"]].add(attempt["harness"])
    return {task for task, harnesses in solved.items() if {"iris", "claude-code"} <= harnesses}


def distribution(values: list[Number]) -> dict[str, float | int] | None:
    clean = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))]
    if not clean:
        return None
    return {
        "n": len(clean),
        "mean": statistics.fmean(clean),
        "median": statistics.median(clean),
        "min": min(clean),
        "max": max(clean),
        "stdev": statistics.stdev(clean) if len(clean) > 1 else 0.0,
    }


def aggregate_distributions(attempts: list[dict[str, Any]], included_tasks: set[str]) -> dict[str, Any]:
    metrics = ("input_full", "input_beyond_base", "cache_read", "cache_write", "output", "turns", "tools", "cost_actual", "cost_cold")
    out: dict[str, Any] = {"iris": {}, "claude-code": {}}
    for harness in out:
        selected = [a for a in attempts if a["harness"] == harness and a["task"] in included_tasks and a["solved"] and a["metrics"]]
        for metric in metrics:
            values = [a["metrics"]["totals"].get(metric) for a in selected]
            out[harness][metric] = distribution(values)
    return out


def high_variance_tasks(attempts: list[dict[str, Any]], included_tasks: set[str]) -> list[dict[str, Any]]:
    flags = []
    for task in sorted(included_tasks):
        for harness in ("iris", "claude-code"):
            vals = [a["metrics"]["totals"].get("input_full") for a in attempts if a["task"] == task and a["harness"] == harness and a["solved"] and a["metrics"]]
            stats = distribution(vals)
            if stats and stats["n"] > 1 and stats["mean"] and stats["stdev"] / stats["mean"] > HIGH_VARIANCE_CV:
                flags.append({"task": task, "harness": harness, "cv": stats["stdev"] / stats["mean"]})
    return flags


def cc_cost_calibration(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for attempt in attempts:
        if attempt["harness"] != "claude-code" or not attempt["metrics"]:
            continue
        metrics = attempt["metrics"]
        reported = metrics.get("reported_cost_usd")
        calculated = metrics["totals"].get("cost_actual")
        totals = metrics["totals"]
        billed_tokens = sum(number(totals.get(k)) for k in ("fresh", "cache_read", "cache_write", "output"))
        if not isinstance(reported, (int, float)) or not isinstance(calculated, (int, float)) or not billed_tokens:
            continue
        divergence = abs(calculated - reported) / reported if reported else math.inf
        rows.append({
            "task": attempt["task"],
            "trial": attempt["trial"],
            "reported_cost": reported,
            "table_cost": calculated,
            "reported_blended_rate_per_mtok": reported * 1_000_000 / billed_tokens,
            "table_blended_rate_per_mtok": calculated * 1_000_000 / billed_tokens,
            "divergence": divergence,
            "warning": divergence > 0.10,
        })
    return rows


def fmt(value: Any, money: bool = False) -> str:
    if value is None:
        return "-"
    if money:
        return f"${value:.4f}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def compact_stats(stats: dict[str, Any] | None, money: bool = False) -> str:
    if not stats:
        return "-"
    if money:
        return f"{fmt(stats['mean'], True)} / {fmt(stats['median'], True)} / {fmt(stats['min'], True)} / {fmt(stats['max'], True)} / {fmt(stats['stdev'], True)}"
    return f"{stats['mean']:,.1f} / {stats['median']:,.1f} / {stats['min']:,.1f} / {stats['max']:,.1f} / {stats['stdev']:,.1f}"


def build_report(data: dict[str, Any]) -> str:
    attempts = data["attempts"]
    lines = [
        "# Harness token-efficiency comparison",
        "",
        f"- Iris job: `{data['iris_job']}`",
        f"- Claude Code job: `{data['claude_code_job']}`",
        f"- Pricing: USD/Mtok, {PRICING_AS_OF}; claude-sonnet-5 input $3.00, output $30.00, cache-write 1.25x input, cache-read 0.10x input.",
        "- Token/cost comparisons include solved attempts only, and only tasks with at least one solved attempt on both harnesses.",
        "",
    ]
    warnings = list(data["warnings"])
    if warnings:
        lines += ["## Warnings", ""] + [f"- {w}" for w in warnings] + [""]

    lines += [
        "## Per-attempt task table",
        "",
        "| Task | Harness | Trial | Turns | Input raw | Input beyond base | Cache read % | Cache write | Output | Tools | Reward | Actual cost | Cold-normalized |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    included = set(data["both_solved_tasks"])
    for attempt in sorted(attempts, key=lambda a: (a["task"], a["harness"], a["trial"])):
        # Keep failures visible, but never put their tokens beside solved runs.
        comparable = attempt["solved"] and attempt["task"] in included
        totals = ((attempt.get("metrics") or {}).get("totals") or {}) if comparable else {}
        input_full = totals.get("input_full")
        cache_read = totals.get("cache_read")
        cache_pct = 100 * cache_read / input_full if isinstance(cache_read, (int, float)) and input_full else None
        lines.append("| " + " | ".join([
            attempt["task"], attempt["harness"], attempt["trial"], fmt(totals.get("turns")),
            fmt(input_full), fmt(totals.get("input_beyond_base")), f"{cache_pct:.1f}%" if cache_pct is not None else "-",
            fmt(totals.get("cache_write")), fmt(totals.get("output")), fmt(totals.get("tools")),
            fmt(attempt.get("reward")), fmt(totals.get("cost_actual"), True), fmt(totals.get("cost_cold"), True),
        ]) + " |")

    lines += ["", "## Both-solved comparison", ""]
    included = data["both_solved_tasks"]
    if not included:
        lines += ["No task was solved by both harnesses; no token or cost comparison is reported.", ""]
    else:
        lines += [
            f"Included tasks ({len(included)}): " + ", ".join(f"`{task}`" for task in included),
            "",
            "Each cell is mean / median / min / max / sample stdev across solved attempts.",
            "",
            "| Task | Harness | solved k | Input raw | Input beyond base | Actual cost | Cold-normalized |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for task in included:
            for harness in ("iris", "claude-code"):
                selected = [a for a in attempts if a["task"] == task and a["harness"] == harness and a["solved"] and a["metrics"]]
                vals = lambda key: distribution([a["metrics"]["totals"].get(key) for a in selected])
                lines.append(f"| {task} | {harness} | {len(selected)} | {compact_stats(vals('input_full'))} | {compact_stats(vals('input_beyond_base'))} | {compact_stats(vals('cost_actual'), True)} | {compact_stats(vals('cost_cold'), True)} |")
        lines.append("")

    lines += [
        "## Aggregate distributions (both-solved only)", "",
        "Each cell is n; mean / median / min / max / sample stdev over solved attempts.", "",
        "| Metric | Iris | Claude Code |", "|---|---:|---:|",
    ]
    for metric in ("input_full", "input_beyond_base", "cache_read", "cache_write", "output", "turns", "tools", "cost_actual", "cost_cold"):
        iris_stats = data["aggregates"]["iris"].get(metric)
        cc_stats = data["aggregates"]["claude-code"].get(metric)
        money = metric.startswith("cost_")
        i_text = f"{iris_stats['n']}; {compact_stats(iris_stats, money)}" if iris_stats else "-"
        c_text = f"{cc_stats['n']}; {compact_stats(cc_stats, money)}" if cc_stats else "-"
        lines.append(f"| {metric} | {i_text} | {c_text} |")

    lines += ["", "## High variance", ""]
    if data["high_variance"]:
        lines += [f"- `{row['task']}` / {row['harness']}: input_full CV {row['cv']:.1%}" for row in data["high_variance"]]
    else:
        lines.append(f"No task with at least two solved attempts exceeded {HIGH_VARIANCE_CV:.0%} input_full coefficient of variation.")

    lines += ["", "## Claude Code cost self-calibration", ""]
    if data["cost_calibration"]:
        lines += [
            "| Task/trial | Reported | Table | Reported blended $/M | Table blended $/M | Divergence |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for row in data["cost_calibration"]:
            marker = " **WARN**" if row["warning"] else ""
            lines.append(f"| {row['task']} / {row['trial']} | {fmt(row['reported_cost'], True)} | {fmt(row['table_cost'], True)} | {row['reported_blended_rate_per_mtok']:.2f} | {row['table_blended_rate_per_mtok']:.2f} | {row['divergence']:.1%}{marker} |")
    else:
        lines.append("No Claude Code reported-cost data was available.")

    lines += ["", "## Exclusion taxonomy", ""]
    exclusions = data["exclusions"]
    if exclusions:
        lines += ["| Category | Task | Harness/trial | Reason |", "|---|---|---|---|"]
        for row in exclusions:
            lines.append(f"| {row['category']} | {row['task']} | {row['harness']} / {row['trial']} | {row['reason']} |")
    else:
        lines.append("No attempts were excluded.")
    lines.append("")
    return "\n".join(lines)


def analyze(iris_job: Path, cc_job: Path) -> dict[str, Any]:
    attempts = scan_job(iris_job, "iris") + scan_job(cc_job, "claude-code")
    included = both_solved_tasks(attempts)
    warnings = []
    for attempt in attempts:
        for warning in (attempt.get("metrics") or {}).get("warnings", []):
            warnings.append(f"{attempt['harness']} {attempt['trial']}: {warning}")
        metrics = attempt.get("metrics")
        if metrics and not pricing_for(metrics.get("model")) and not metrics.get("legacy"):
            warnings.append(f"{attempt['harness']} {attempt['trial']}: no pricing for model {metrics.get('model')!r}; costs unavailable")
    calibration = cc_cost_calibration(attempts)
    for row in calibration:
        if row["warning"]:
            warnings.append(f"Claude Code cost table diverges {row['divergence']:.1%} from reported cost for {row['trial']} (>10%)")
    exclusions = [{
        "category": a["exclusion_category"] or "not-both-solved",
        "task": a["task"], "harness": a["harness"], "trial": a["trial"],
        "reason": a["exclusion_reason"] or "task has no solved attempt on the other harness",
    } for a in attempts if not a["solved"] or a["task"] not in included]
    return {
        "schema_version": 1,
        "iris_job": str(iris_job),
        "claude_code_job": str(cc_job),
        "pricing_as_of": PRICING_AS_OF,
        "pricing": PRICING,
        "attempts": attempts,
        "both_solved_tasks": sorted(included),
        "aggregates": aggregate_distributions(attempts, included),
        "high_variance": high_variance_tasks(attempts, included),
        "cost_calibration": calibration,
        "exclusions": exclusions,
        "warnings": warnings,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iris_job", type=Path)
    parser.add_argument("claude_code_job", type=Path)
    parser.add_argument("-o", "--output", type=Path, help="Markdown output path (default: beside the job dirs)")
    parser.add_argument("--json", dest="json_output", type=Path, help="Optional machine-readable JSON output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not args.iris_job.is_dir() or not args.claude_code_job.is_dir():
        print("error: both arguments must be completed job directories", file=sys.stderr)
        return 2
    data = analyze(args.iris_job, args.claude_code_job)
    report = build_report(data)
    output = args.output or args.iris_job.parent / f"{args.iris_job.name}__vs__{args.claude_code_job.name}__tokens.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report + "\n")
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(report)
    print(f"\nReport written to {output}", file=sys.stderr)
    if args.json_output:
        print(f"JSON written to {args.json_output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
