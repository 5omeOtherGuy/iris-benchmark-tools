# Iris Benchmark Tools

Operational entry point for agents running controlled coding-agent benchmarks with Harbor and Terminal-Bench 2.0.

## Start here

1. Resolve the repository root with `git rev-parse --show-toplevel`.
2. Read [`AGENTS.md`](AGENTS.md).
3. Check `<root>/.benchmark-setup`.
4. If the marker is absent, execute [`benchmark-onboarding`](.agents/skills/benchmark-onboarding/SKILL.md). Do not start a model-backed benchmark.
5. If the marker exists, execute [`harness-benchmark`](.agents/skills/harness-benchmark/SKILL.md).
6. Use [`harness-telemetry`](.agents/skills/harness-telemetry/SKILL.md) as the source-schema contract and [`benchmark-telemetry-report`](.agents/skills/benchmark-telemetry-report/SKILL.md) for deep analysis.

The files under `.agents/skills/` are canonical. Claude Code reaches the same files through `.claude/skills/`.

## Execution contract

- Inspect before asking. Ask once for unresolved choices; do not ask for facts recoverable from the checkout, commands, setup marker, or telemetry.
- Do not launch model-backed trials until the user approves contenders, model IDs, task scope, attempts, budget, and total run count.
- Run contenders sequentially unless the user explicitly accepts credential-race, resource-contention, and timing risks.
- In a controlled comparison, keep model ID, task selection, attempts, concurrency, and environment constant.
- Preserve failed attempts, missing values, parser warnings, and outliers. Never convert missing telemetry to zero.
- Never read or display credential contents. Direct the user to authenticate in their own shell.
- Do not selectively rerun capability failures.
- Do not delete raw jobs or prune Docker state without explicit confirmation.

## 1. Onboard a fresh checkout

Skip this phase when `.benchmark-setup` exists.

Run:

```bash
python3 .agents/skills/benchmark-onboarding/scripts/setup.py inspect --repo .
```

Summarize the detected Docker, Harbor, harness, authentication-presence, and Iris-source facts. Ask only for unresolved machine-level choices:

- contenders: `iris`, `claude-code`, `codex`, or `pi`;
- Iris build source, when selected: `latest-release`, `local-source`, `installed`, or `custom`;
- private jobs directory and concurrency;
- Harbor source path only when `harbor` is unavailable.

Do not ask for model, task, attempt, or budget choices during onboarding. Do not install Docker, Harbor, package managers, or harness CLIs automatically. Never silently substitute one Iris build source for another.

Follow the skill through no-token install checks and marker creation. Do not create or edit `.benchmark-setup` manually. Onboarding is complete only when selected prerequisites pass and the setup script writes the marker.

## 2. Define the benchmark

Recover prior user choices, then ask once for unresolved experiment fields:

1. contenders;
2. controlled comparison or product comparison;
3. exact model ID for each contender;
4. task filter or task count;
5. attempts per task;
6. primary metrics: resolution, tokens, API-equivalent cost, wall time, or all;
7. budget, expected duration, storage, and retention requirements.

Before running, present an execution manifest containing:

- tasks × contenders × attempts;
- run order and concurrency;
- exact commands;
- expected billing or subscription usage;
- exact Iris release version or source commit;
- whether the sample supports setup validation, directional findings, or broader claims.

Wait for user approval of the manifest. Treat small `k=1` runs as smoke tests. Prefer at least 20 tasks for directional comparisons.

## 3. Preflight without model requests

Run applicable checks:

```bash
df -h .
docker info --format '{{.ServerVersion}}'
harbor --version
harbor run --help
```

When Harbor comes from a source checkout, set `HARBOR_DIR`; the runner uses `uv run harbor` there.

Validate each untested contender with one install-only trial:

```bash
./run-bench.sh <contender> <provider/model> \
  --install-only -l 1 -y --job-name setup__<contender>
```

Install-only trials may download images and packages but must not make a model request. If Harbor rejects an argument, inspect its implemented CLI and adapt; do not guess.

## 4. Run sequential legs

`run-bench.sh` pins `terminal-bench@2.0`, maps `iris` to the repository adapter, applies setup defaults, and forwards remaining arguments to `harbor run`.

Controlled example:

```bash
./run-bench.sh iris anthropic/claude-sonnet-5 \
  -i '<task-glob>' -k 2 -y --job-name iris__pilot

./run-bench.sh claude-code anthropic/claude-sonnet-5 \
  -i '<task-glob>' -k 2 -y --job-name cc__pilot
```

Use identical task-selection arguments for every leg. Start the next contender only after the prior one finishes. Monitor `<jobs-dir>/<job-name>/result.json`; process exit alone does not establish benchmark success.

Classify failures from exact evidence as infrastructure, authentication, rate limit, harness, timeout, agent capability, tool misuse, or verifier failure. Apply only the predeclared retry policy. If a comparison remains incomplete, state exactly what ran.

## 5. Analyze and report

Run the compatible Iris and Claude Code analyzer:

```bash
python3 analyze_tokens.py \
  '<jobs-dir>/iris__pilot' \
  '<jobs-dir>/cc__pilot' \
  -o comparison.md \
  --json comparison.json
```

Analysis requirements:

- match tasks and attempts explicitly;
- keep every failure and exclusion visible;
- reconcile per-turn telemetry with aggregate totals;
- separate fresh, cache-read, cache-write, full-input, output, and reasoning tokens;
- report observed and cold-normalized API-equivalent cost when supported;
- use tasks solved at least once by both harnesses for the primary token-efficiency set;
- aggregate attempts within each task before aggregating across tasks;
- report raw outcomes, controlled views, timing, and outliers;
- state model, harness, Harbor, dataset, run-order, cache-state, environment, and sample-size caveats.

The analyzer states its pricing date and refuses to price unknown models. Do not invent prices or unsupported telemetry.

A complete report includes an aggregate verdict, per-task outcomes, failure taxonomy, turns, tool calls, token/cache/cost decomposition, wall time, outliers, limitations, and concrete recommendations.

## Configuration

Environment variables override `.benchmark-setup`; the marker overrides defaults.

| Purpose | Environment variable | Default |
|---|---|---|
| Jobs directory | `BENCH_JOBS_DIR` | `<repo>/jobs` |
| Trial concurrency | `HARNESS_BENCH_CONCURRENCY` | `1` |
| Harbor source checkout | `HARBOR_DIR` | Harbor from `PATH` |
| Iris binary | `IRIS_BINARY_PATH` | latest release |
| Iris Claude credentials | `IRIS_CLAUDE_CREDENTIALS_PATH` | normal Claude store |
| Iris auth store | `IRIS_AUTH_JSON_PATH` | normal Iris store |
| Codex auth store | `CODEX_AUTH_JSON_PATH` | normal Codex store |
| Claude Code OAuth | `CLAUDE_CODE_OAUTH_TOKEN` | required for Claude Code |

For Claude Code, tell the user to run `claude setup-token` interactively and export the resulting variable. Never ask the user to paste a token into chat.

## Compatibility

- Python 3.12 or newer (Harbor's minimum).
- Harbor 0.13.1 through 0.24.0. `agents/iris_installed.py` imports and constructs against releases across that range (checked 2026-10-17). CI installs the locked Harbor 0.24.0 and import-checks the adapter without running a trial. To install the same version: `python3 -m pip install -r requirements-harbor.txt`.

## Repository map

| Path | Use |
|---|---|
| `run-bench.sh` | Run one Harbor benchmark leg. |
| `agents/iris_installed.py` | Install Iris in Harbor task containers. |
| `analyze_tokens.py` | Produce Markdown and JSON telemetry comparisons. |
| `requirements-harbor.txt` | Locked Harbor version that CI checks the adapter against. |
| `.agents/skills/benchmark-onboarding/` | Configure and preflight a checkout. |
| `.agents/skills/harness-benchmark/` | Design, run, analyze, and retain a comparison. |
| `.agents/skills/harness-telemetry/` | Interpret Iris and Claude Code telemetry. |
| `.agents/skills/benchmark-telemetry-report/` | Produce a rigorous final report. |
| `fixtures/` | Synthetic parser fixtures. |
| `test_*.py` | Toolkit tests. |

## Validate toolkit changes

```bash
python3 -m pip install -r requirements-harbor.txt   # or .agents/setup in an orb
scripts/gate
```

The gate runs the tests, shell syntax checks, an Iris adapter import check, and the history secret scan. CI runs it in the job `gate`. Run one test module with `python3 -m unittest test_analyze_tokens -v`.

Before publishing a toolkit change, inspect `git status`, the staged diff, and the complete tracked path list.

## License

[MIT](LICENSE).
