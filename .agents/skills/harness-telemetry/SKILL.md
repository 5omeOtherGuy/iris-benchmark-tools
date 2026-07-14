---
name: harness-telemetry
description: How to collect per-turn token/cache/tool telemetry from a benchmark run and the exact schema of every telemetry source (iris + Claude Code via Harbor). Collection and field definitions only — analysis/cost/comparison live in the harness-benchmark skill and analyze_tokens.py.
---

# Harness telemetry collection

Produce and locate the raw token/cache/tool telemetry a benchmark run emits, and
know every field it contains. This skill is the data contract. It does **not**
cover interpretation — no cost math, cache-hit reasoning, base-netting,
cold-normalization, or cross-harness verdicts. For that, see the
`harness-benchmark` skill and the repository's `analyze_tokens.py`.

Two harnesses emit telemetry, in different shapes:
- **iris** — a single self-describing JSON report it writes itself.
- **Claude Code** — a stream-json transcript plus an ATIF trajectory, both
  written by Harbor's built-in agent.

## Producing telemetry

Runs go through the benchmark runner; each trial leaves its telemetry in the
preserved agent dir.

```
cd <iris-benchmark-tools-clone>
./run-bench.sh iris        anthropic/claude-sonnet-5 -i <task> -k <n> -y --job-name <name>
./run-bench.sh claude-code anthropic/claude-sonnet-5 -i <task> -k <n> -y --job-name <name>
```

Prerequisites:
- **Iris must be a v2-telemetry binary.** Run one smoke trial and confirm that
  `agent/iris_usage.json` exists and has `turns`, `base`, and `totals`. For a
  local build, set `IRIS_BINARY_PATH=<repo>/target/release/iris`.
- **Claude Code needs `CLAUDE_CODE_OAUTH_TOKEN`.** Export it in the current
  process environment; never save it in this repository.

Output layout (per trial):
```
jobs/<job>/result.json                                  # job-level rewards + started_at/finished_at
jobs/<job>/<task>__<trialid>/
  agent/iris_usage.json                                 # iris: the v2 report (iris legs)
  agent/iris-sessions/**/*.jsonl                        # iris: full transcript, per-message timestamps
  agent/iris.txt                                        # iris: final stdout answer
  agent/claude-code.txt                                 # cc: stream-json transcript (cc legs)
  agent/trajectory.json                                 # cc: ATIF trajectory + final_metrics
```

Wall-clock note: `result.json` timestamps are **job-level only** (no per-trial
timing). Per-trial wall-clock is the span of file mtimes in the trial dir — the
only source that is uniform and reliable across both harnesses (see caveats).

### iris standalone (outside Harbor)

iris emits the same report in headless mode whenever `IRIS_USAGE_JSON` names a
path:

```
IRIS_USAGE_JSON=/tmp/usage.json iris -p "<task>" --approve
```

The report is flushed after **every provider turn** (best-effort write), so a
timed-out or SIGKILLed run still leaves partial-but-valid telemetry. In Harbor,
the adapter (`agents/iris_installed.py`) sets `IRIS_USAGE_JSON` (→
`iris_usage.json`) and `IRIS_SESSION_DIR` (→ `iris-sessions/`) into the agent dir
for you.

## iris telemetry: `iris_usage.json`

Self-describing v2 JSON. Source: `src/print.rs` (`PrintObserver` / `UsageReport`),
wired in `src/lib.rs::run_print`. Shape:

```jsonc
{
  "schema_version": 2,
  "provider": "anthropic",
  "model": "claude-sonnet-5",

  "base": {                          // estimated fixed prefix sent before messages
    "system_prompt_tokens": 6796,
    "tools": [{"name": "read", "schema_tokens": 300}, ...],
    "tools_total_tokens": 0,
    "base_total_tokens": 6796        // = system_prompt_tokens + tools_total_tokens
  },

  "turns": [                         // one entry per completed provider round-trip
    {
      "i": 0,                        // turn index (0-based)
      "fresh": 2,                    // uncached input = input_tokens - cache_read - cache_write
      "cache_read": 21722,           // = cache_read_input_tokens
      "cache_write": 8476,           // = cache_creation_input_tokens
      "output": 200,                 // = output_tokens
      "reasoning": 20,               // = reasoning_output_tokens
      "input_full": 30200,           // = input_tokens (INCLUDES cache read + write)
      "duration_ms": 1200,           // provider round-trip time
      "ttft_ms": 300,                // time to first output token (nullable)
      "stop_reason": "tool_use"      // completion reason (nullable)
    }
  ],

  "tools": [                         // one entry per tool invocation, enriched by lifecycle events
    {
      "i": 0, "turn": 0,
      "name": "bash", "call_id": "call-2",
      "duration_ms": 75,
      "offloaded": true,             // output handed to an output-handle instead of inlined
      "handle": "h_ab12", "handle_bytes": 10000, "handle_lines": 200   // null unless offloaded
    }
  ],

  "totals": {                        // cumulative accounting (v1 fields), rebuilt each flush
    "provider_turns": 2,
    "input_tokens": 60400,
    "output_tokens": 500,
    "reasoning_output_tokens": 50,
    "cache_read_input_tokens": 43444,
    "cache_write_input_tokens": 16952,
    "cache_creation_5m_input_tokens": 16952,
    "cache_creation_1h_input_tokens": 0,
    "cache_creation_reported": true, // false => provider gave no 5m/1h breakdown ("zero" vs "unknown")
    "latest_total_tokens": 30200,    // last turn's snapshot total (level, not a flow sum)
    "tool_calls": 2,
    "tool_calls_by_name": {"read": 1, "bash": 1}
  }

  // The v1 `totals` keys are ALSO flattened at the top level (input_tokens, etc.)
  // for back-compat with pre-v2 consumers.
}
```

Field-definition notes (data properties, not analysis):
- Per-turn identity holds by construction: `fresh + cache_read + cache_write == input_full`.
- `input_full` / `input_tokens` **include** cached read + write tokens (a full-context count). The provider API's own `input_tokens` excludes cached tokens — iris's does not.
- `turns` is a **flow** (per round-trip); `latest_total_tokens` is a **level** (a
  snapshot). Do not sum levels.
- `base.*` tokens are **estimated** locally (tokenizer estimate of the system
  prompt + each tool's serialized declaration), not provider-reported.

## iris transcript: `iris-sessions/**/*.jsonl`

One JSON object per line; `message` entries carry `role`, `content`, and a
millisecond `timestamp`. Contains the full tool-call history (commands, results)
and brackets agent-active wall-clock (first→last timestamp). Appended live, so it
survives a mid-run kill.

## Claude Code telemetry

Two files, both under `agent/`.

### `claude-code.txt` — stream-json transcript
One event per line. `type == "assistant"` events carry `message.usage`:
```jsonc
{"type":"assistant","message":{"id":"m1","stop_reason":"tool_use",
  "usage":{"input_tokens":2,"output_tokens":5,
           "cache_read_input_tokens":21722,"cache_creation_input_tokens":8476},
  "content":[{"type":"tool_use","id":"tool-1","name":"Read","input":{...}}]}}
```
- Usage is keyed to Anthropic's Messages API: `input_tokens` here is **fresh
  only** (excludes cached); cached read/write are the separate `cache_*` fields.
- The **same message id is emitted twice** (a `message_start`-style event and a
  final event). Deduplicate by `message.id`.
- `content[]` `tool_use` blocks give per-turn tool calls.

### `trajectory.json` — ATIF trajectory
```jsonc
{
  "schema_version": "ATIF-v1.7",
  "agent": {"model_name": "claude-sonnet-5"},
  "steps": [{"source": "agent", "metrics": {"completion_tokens": 6055}}, ...],
  "final_metrics": {
    "total_prompt_tokens": 104113,
    "total_completion_tokens": 6558,
    "total_cost_usd": 0.0,
    "total_steps": 4,
    "extra": {
      "total_cache_read_input_tokens": 91399,
      "total_cache_creation_input_tokens": 12708
    }
  }
}
```

## Collection caveats (where the reliable data is)

These are data-source facts, not interpretation:

- **iris released binary may emit nothing.** Pre-v2 builds (e.g. the 0.3.1
  tarball) have no telemetry. Verify v2 before trusting an empty/absent file.
- **Claude Code stream `output_tokens` undercounts** — it omits hidden reasoning
  tokens (observed 10 vs a true 6,558). The complete output count is
  `trajectory.json` `final_metrics.total_completion_tokens`; per-step values are
  in `steps[].metrics.completion_tokens`. Prefer ATIF over the stream sum for
  output.
- **Claude Code usage is duplicated per message** — dedupe by `message.id`.
- **`trajectory.json` timestamps are unreliable** for timing (mixed timezones,
  `finished_at` sometimes null). Use trial-dir **file mtimes** for per-trial
  wall-clock instead; this is uniform across both harnesses.
- **Turn-0 `cache_read`** records whether the provider cache was warm at the
  start (large read = warm prefix inherited from prior same-account activity;
  ~0 = cold). It is a property of the recorded run, captured — not something this
  skill interprets.
- **iris `base` is estimated**, Claude Code emits no equivalent base field; its
  fixed prefix is only observable as turn-0 context in the transcript.

## Scope

Collection and schema only. Cost, pricing, cache-hit rates, base/task splits,
cold-normalization, and any iris-vs-Claude-Code comparison are **out of scope**
here — they live in the `harness-benchmark` skill and the repository's
`analyze_tokens.py`.
