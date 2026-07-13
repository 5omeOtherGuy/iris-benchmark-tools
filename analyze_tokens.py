#!/usr/bin/env python3
"""Token-efficiency comparison for a harness benchmark (iris vs claude-code).

Parses two Harbor job dirs and emits a per-task diagnostics table plus
aggregates. iris token data comes from the per-trial `agent/iris_usage.json`
side file (emitted by iris `-p` under IRIS_USAGE_JSON); claude-code data comes
from Harbor's native `trajectory.json` (final_metrics + per-step tool calls).

Usage: analyze_tokens.py <iris_job_dir> <claude_code_job_dir>
"""
import json
import sys
from pathlib import Path


def load(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return None


def reward_of(trial_dir):
    """Best-effort per-trial reward in [0,1]; None if unavailable."""
    r = load(trial_dir / "result.json")
    if isinstance(r, dict):
        # terminal-bench 2.0 / Harbor: verifier_result.rewards.reward
        vr = r.get("verifier_result") or {}
        if isinstance(vr, dict):
            rewards = vr.get("rewards") or {}
            if isinstance(rewards, dict) and isinstance(rewards.get("reward"), (int, float)):
                return float(rewards["reward"])
        for key in ("reward", "score"):
            if isinstance(r.get(key), (int, float)):
                return float(r[key])
    # Fallback: verifier/reward.txt
    try:
        return float((trial_dir / "verifier" / "reward.txt").read_text().strip())
    except Exception:
        return None


def iris_metrics(trial_dir):
    u = load(trial_dir / "agent" / "iris_usage.json")
    if not isinstance(u, dict):
        return None
    return {
        "provider_turns": u.get("provider_turns"),
        "input_tokens": u.get("input_tokens"),
        "output_tokens": u.get("output_tokens"),
        "reasoning_tokens": u.get("reasoning_output_tokens"),
        "cache_read": u.get("cache_read_input_tokens"),
        "cache_write": u.get("cache_write_input_tokens"),
        "total_tokens": u.get("latest_total_tokens"),
        "tool_calls": u.get("tool_calls"),
        "tools_by_name": u.get("tool_calls_by_name") or {},
    }


def cc_metrics(trial_dir):
    # Harbor's claude-code adapter writes the trajectory under agent/.
    t = load(trial_dir / "agent" / "trajectory.json")
    if not isinstance(t, dict):
        return None
    fm = t.get("final_metrics") or {}
    extra = fm.get("extra") or {}
    steps = t.get("steps") or []
    # Tool calls aren't itemized in the ATIF trajectory (agent tool-turns have
    # empty messages), so count tool_use blocks from the raw stream-json log.
    tool_calls = 0
    tools_by_name = {}
    cc_txt = trial_dir / "agent" / "claude-code.txt"
    if cc_txt.exists():
        for line in cc_txt.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            msg = ev.get("message") if isinstance(ev, dict) else None
            blocks = (msg or {}).get("content") if isinstance(msg, dict) else None
            if isinstance(blocks, list):
                for b in blocks:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        tool_calls += 1
                        n = b.get("name") or "?"
                        tools_by_name[n] = tools_by_name.get(n, 0) + 1
    cache_read = extra.get("total_cache_read_input_tokens")
    if cache_read is None:
        cache_read = fm.get("total_cached_tokens")
    return {
        "provider_turns": fm.get("total_steps") if fm.get("total_steps") is not None else len(steps),
        "input_tokens": fm.get("total_prompt_tokens"),
        "output_tokens": fm.get("total_completion_tokens"),
        "cache_read": cache_read,
        "cache_write": extra.get("total_cache_creation_input_tokens"),
        "total_tokens": fm.get("total_prompt_tokens"),
        "tool_calls": tool_calls,
        "tools_by_name": tools_by_name,
        "cost_usd": fm.get("total_cost_usd"),
    }


def scan(job_dir, kind):
    job_dir = Path(job_dir)
    out = {}
    for tr in sorted(job_dir.iterdir()):
        if not tr.is_dir() or not (tr / "result.json").exists():
            continue
        res = load(tr / "result.json")
        task = res.get("task_name") if isinstance(res, dict) else tr.name
        m = iris_metrics(tr) if kind == "iris" else cc_metrics(tr)
        out[task] = {"trial": tr.name, "reward": reward_of(tr), "metrics": m}
    return out


def fmt(n):
    if n is None:
        return "-"
    if isinstance(n, float):
        return f"{n:.2f}"
    return f"{n:,}"


def main():
    iris_dir, cc_dir = sys.argv[1], sys.argv[2]
    iris = scan(iris_dir, "iris")
    cc = scan(cc_dir, "cc")
    tasks = sorted(set(iris) | set(cc))

    print("\n=== PER-TASK: input tokens (cache-read %) | tool calls | reward ===")
    hdr = f"{'task':32} | {'iris in':>10} {'ir$':>4} {'cr%':>4} {'tc':>3} {'rw':>3} | {'cc in':>10} {'cr%':>4} {'tc':>3} {'rw':>3}"
    print(hdr)
    print("-" * len(hdr))
    agg = {"iris": {}, "cc": {}}
    for t in tasks:
        i = iris.get(t, {}).get("metrics") or {}
        c = cc.get(t, {}).get("metrics") or {}
        ir = iris.get(t, {}).get("reward")
        cr = cc.get(t, {}).get("reward")

        def crp(m):
            it, ca = m.get("input_tokens"), m.get("cache_read")
            if it and ca is not None and it > 0:
                return f"{round(100*ca/it)}"
            return "-"
        row = (f"{t[:32]:32} | {fmt(i.get('input_tokens')):>10} {'-':>4} {crp(i):>4} "
               f"{fmt(i.get('tool_calls')):>3} {fmt(ir):>3} | "
               f"{fmt(c.get('input_tokens')):>10} {crp(c):>4} {fmt(c.get('tool_calls')):>3} {fmt(cr):>3}")
        print(row)

    def total(scanned, key):
        s = 0
        any_ = False
        for t in scanned.values():
            m = t.get("metrics") or {}
            if isinstance(m.get(key), (int, float)):
                s += m[key]
                any_ = True
        return s if any_ else None

    print("\n=== AGGREGATES ===")
    for label, sc in (("iris", iris), ("claude-code", cc)):
        rewards = [v["reward"] for v in sc.values() if isinstance(v.get("reward"), (int, float))]
        solved = sum(1 for r in rewards if r and r >= 1.0)
        print(f"\n[{label}]  trials={len(sc)}  solved={solved}/{len(rewards) if rewards else '?'}")
        for key in ("input_tokens", "output_tokens", "cache_read", "cache_write",
                    "reasoning_tokens", "total_tokens", "provider_turns", "tool_calls"):
            print(f"   {key:16}: {fmt(total(sc, key))}")

    # Head-to-head input-token ratio on tasks BOTH solved (fair efficiency view)
    both = [t for t in tasks
            if (iris.get(t, {}).get('metrics') or {}).get('input_tokens')
            and (cc.get(t, {}).get('metrics') or {}).get('input_tokens')]
    if both:
        ii = sum((iris[t]['metrics']['input_tokens']) for t in both)
        cci = sum((cc[t]['metrics']['input_tokens']) for t in both)
        print(f"\n=== INPUT-TOKEN TOTALS on {len(both)} tasks with data on both sides ===")
        print(f"   iris        : {ii:,}")
        print(f"   claude-code : {cci:,}")
        if cci:
            print(f"   iris / cc   : {ii/cci:.2f}x  ({'iris cheaper' if ii<cci else 'iris costlier'})")


if __name__ == "__main__":
    main()
