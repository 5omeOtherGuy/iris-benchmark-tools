# Iris Benchmark Tools

Run controlled coding-agent comparisons with [Harbor](https://github.com/laude-institute/harbor), Terminal-Bench 2.0, Iris, and Harbor's built-in harnesses.

The repository contains the runner, Iris Harbor adapter, token-efficiency analyzer, synthetic fixtures, tests, and four agent skills. It deliberately excludes benchmark jobs, transcripts, reports, credentials, archives, and binaries.

## What this measures

Use the same provider model and task set across harnesses to isolate harness behavior. Product comparisons with different models are also possible, but model and harness effects are then confounded.

The analyzer reports:

- task success and failures;
- provider turns and tool calls;
- fresh, cache-read, cache-write, full-input, output, and reasoning tokens;
- observed and cold-normalized API-equivalent cost;
- fixed-prefix-netted input where supported;
- per-attempt and task-balanced aggregates;
- parser warnings and telemetry exclusions.

## Prerequisites

- Linux with Docker
- Python 3.10 or newer
- [Harbor](https://github.com/laude-institute/harbor) with `harbor` on `PATH`, or a Harbor source checkout selected with `HARBOR_DIR`
- Credentials for each harness you run

The Iris adapter uploads a local glibc binary when `IRIS_BINARY_PATH` is set. Otherwise it downloads the latest x86_64 GNU/Linux Iris release inside each task container. All Terminal-Bench 2.0 agent containers at the pinned dataset revision are glibc-based; a musl binary is needed only for other Alpine-based datasets.

## First-run onboarding

Open the cloned repository with Iris, Claude Code, Codex, or pi and ask to start a benchmark. When the ignored `.benchmark-setup` marker is absent, repository guidance invokes `benchmark-onboarding` before any token-spending run.

The onboarding skill:

- inventories Docker, Harbor, Iris, Claude Code, Codex, pi, authentication presence, and local Iris source builds;
- asks which harnesses and which Iris build to use: latest published release, detected local developer checkout, installed binary, or custom binary;
- validates private storage and concurrency;
- runs install-only compatibility checks;
- writes `.benchmark-setup` only after selected prerequisites pass.

Invoke it explicitly with `$benchmark-onboarding` if your agent supports skill mentions. The marker contains paths and selections, never credentials, and `run-bench.sh` consumes it automatically. Environment variables still take precedence.

## Authentication

Keep credentials outside this repository. Export only the variables needed for the current shell:

```bash
# Claude Code harness: value created interactively by `claude setup-token`
export CLAUDE_CODE_OAUTH_TOKEN="<token>"

# Optional Iris credential overrides; these default to the normal user paths.
export IRIS_CLAUDE_CREDENTIALS_PATH="$HOME/.claude/.credentials.json"
export IRIS_AUTH_JSON_PATH="$HOME/.iris/auth.json"

# Optional local Iris build instead of the latest release.
export IRIS_BINARY_PATH="$HOME/src/iris-agent/target/release/iris"
```

Never put token values, credential JSON, or shell files containing secrets in this checkout. Benchmark transcripts can also capture sensitive tool output; treat the complete `jobs/` tree as private.

## Run a comparison

From the repository root:

```bash
# Controlled comparison: same model, same tasks, sequential legs.
./run-bench.sh iris anthropic/claude-sonnet-5 \
  -i '<task-glob>' -k 2 -y --job-name iris__pilot

./run-bench.sh claude-code anthropic/claude-sonnet-5 \
  -i '<task-glob>' -k 2 -y --job-name cc__pilot
```

The runner defaults to:

- dataset `terminal-bench@2.0`;
- one concurrent trial;
- output under `./jobs`.

Override these without editing the script:

```bash
export BENCH_JOBS_DIR=/data/private-bench/jobs
export HARNESS_BENCH_CONCURRENCY=2
export HARBOR_DIR=$HOME/src/harbor   # only needed for a source checkout
```

Run contenders sequentially when they share credentials or the host is memory-constrained. Record exact harness, model, Harbor, and dataset versions with every result.

## Analyze token efficiency

```bash
python3 analyze_tokens.py \
  "$BENCH_JOBS_DIR/iris__pilot" \
  "$BENCH_JOBS_DIR/cc__pilot" \
  -o comparison.md \
  --json comparison.json
```

If `BENCH_JOBS_DIR` is unset, replace it with `jobs`. The comparison includes token/cost aggregates only for tasks solved at least once by both harnesses; failed attempts and exclusions remain visible. Read parser warnings before drawing conclusions.

Pricing is time-sensitive. The analyzer states its pricing date and refuses to price unknown models rather than guessing.

## Agent skills

Repository-scoped skills live under `.agents/skills/`:

- `benchmark-onboarding`: inventory and configure a fresh checkout without model-token spend;
- `harness-benchmark`: design, execute, analyze, and clean up a comparison;
- `harness-telemetry`: source schemas and collection semantics;
- `benchmark-telemetry-report`: rigorous analysis and self-contained reporting.

Claude Code discovers the same canonical files through relative links in `.claude/skills/`. Agents that support `.agents/skills/` discover them directly. There is only one copy of each skill.

## Validate changes

```bash
python3 -m unittest -v
bash -n run-bench.sh scripts/check-no-secrets.sh
./scripts/check-no-secrets.sh --history
```

The repository uses a fail-safe `.gitignore`: root files are ignored unless explicitly reviewed and allowlisted. Add an exception only for source, documentation, synthetic fixtures, or tests that are safe to publish.

## Data policy

Safe to publish:

- source code and documentation;
- synthetic telemetry fixtures;
- tests and empty configuration examples.

Do not publish:

- `jobs/`, session transcripts, agent logs, or generated reports derived from real tasks;
- OAuth tokens, API keys, credential stores, or environment files;
- downloaded binaries, archives, container state, or private task assets.

See [SECURITY.md](SECURITY.md) for reporting and response guidance.

## License

Licensed under either the Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE)) or the MIT License ([LICENSE](LICENSE)), at your option.
