---
name: harness-benchmark
description: Benchmark coding-agent harnesses (Iris, Claude Code, Codex CLI, and others) against each other on Terminal-Bench through Harbor. Use when asked to benchmark, compare, or evaluate coding-agent harnesses. Interview the user first, then preflight, run, analyze, report, and clean up safely.
---

# Harness benchmark workflow

Compare coding-agent harnesses on identical tasks with Harbor and Terminal-Bench. Read the repository `README.md` first. Resolve the repository root with `git rev-parse --show-toplevel`; use `BENCH_JOBS_DIR` when set and otherwise use its ignored `jobs/` directory. If `.benchmark-setup` is absent, stop and use `benchmark-onboarding` before this workflow.

Never commit or publish jobs, transcripts, credentials, generated reports from real tasks, archives, or binaries.

## Phase 1 — Interview the user

Ask in one batch for anything not already specified. Do not spend tokens until these are pinned down:

1. **Contenders:** Iris uses `agents.iris_installed:Iris`; `claude-code`, `codex`, and others are Harbor built-ins listed by `harbor run --help`.
2. **Comparison type:**
   - *Controlled* (recommended): same provider model on every harness. This measures harness behavior.
   - *Product:* each harness uses its native or preferred model. This measures the package but confounds model and harness.
3. **Iris build:** latest release downloaded by the adapter, or a local build selected with `IRIS_BINARY_PATH`. Report the exact version or commit.
4. **Scope:** task glob or count. Smoke tests find setup defects; they do not support broad capability claims. Prefer at least 20 tasks for a directional comparison and the full set for a publishable benchmark.
5. **Attempts:** `-k 1` or repeated attempts for pass@k and variance. Warn that small `k=1` samples are noisy.
6. **Budget and time:** tasks × contenders × attempts, expected serial duration, and token billing or subscription usage.
7. **Primary metrics:** resolve rate, tokens, API-equivalent cost, wall time, or all of them.
8. **Storage and retention:** private jobs directory, archive location if any, and whether raw trials must remain after analysis.

## Phase 2 — Preflight without token spend

- Confirm Docker is healthy and both Docker storage and `BENCH_JOBS_DIR` have enough free space.
- Confirm `harbor --version`, or set `HARBOR_DIR` to a Harbor source checkout with `uv` installed.
- Confirm authentication for each contender without printing secret values:
  - Iris/Anthropic: `IRIS_CLAUDE_CREDENTIALS_PATH`, defaulting to the normal Claude credential store.
  - Iris/OpenAI or Antigravity: `IRIS_AUTH_JSON_PATH`, defaulting to the normal Iris auth store.
  - Codex: normal Codex auth store or the provider configuration supported by Harbor.
  - Claude Code: `CLAUDE_CODE_OAUTH_TOKEN`, created interactively with `claude setup-token`.
- Record harness versions, model IDs, Harbor version, dataset version or commit, task filters, attempts, concurrency, and run order.
- Run an install-only single-task check for any untested contender when Harbor supports it.

## Phase 3 — Run

Use identical task-selection arguments for every controlled contender:

```bash
./run-bench.sh iris <provider/model> -l <n> -k <k> -y --job-name <name>
./run-bench.sh claude-code <provider/model> -l <n> -k <k> -y --job-name <name>
```

- Run contenders sequentially by default. Shared OAuth credentials can race during refresh, and parallel legs can distort timing.
- Keep concurrency identical. Override the default only with `HARNESS_BENCH_CONCURRENCY` and record the value.
- Monitor `jobs/<name>/result.json` or the configured jobs directory during long runs.
- Retry infrastructure failures according to a predeclared policy. Do not rerun capability failures selectively.
- Never abandon a half-finished comparison silently. Finish every leg or report exactly what ran.

## Phase 4 — Validate and analyze

Use `harness-telemetry` as the source-schema contract and the repository's `analyze_tokens.py` for compatible accounting.

- Match task sets and attempts explicitly.
- Preserve failed attempts and classify capability, timeout, tool misuse, harness, verifier, auth, rate-limit, and infrastructure failures from exact logs.
- Keep missing and unsupported values distinct from zero.
- Surface parser warnings and reconcile per-turn values with totals.
- Report raw outcomes and controlled views. Do not hide outliers.
- For token and cost comparisons, include only tasks solved at least once by both harnesses in the primary efficiency set; keep every excluded attempt visible.
- Aggregate repeated attempts within each task before aggregating across tasks so tasks receive equal weight.
- State sample-size, run-order, cache-state, model, version, and environment caveats.

Deliver an aggregate verdict, per-task results, failure taxonomy, token/cache/cost decomposition where telemetry permits, timing, outliers, and concrete harness-level observations. Use `benchmark-telemetry-report` for a deep report.

## Phase 5 — Retain and clean up safely

- Keep jobs private. Archive only when requested, into a location outside tracked source.
- Record immutable metadata and checksums beside any archive.
- Do not delete raw jobs until the user confirms the report and archive are sufficient.
- Inspect `docker system df`. Docker prune commands delete shared cache and require explicit user confirmation; never run them automatically.
- Confirm tracked files remain source, documentation, synthetic fixtures, and tests only. Run `./scripts/check-no-secrets.sh --history` before publishing.

## Platform notes

- The released Iris archive is an x86_64 GNU/Linux binary. Alpine/musl task images fail installation; classify this as environment incompatibility consistently across contenders.
- Harbor can use cloud environments and other datasets. Preserve the same controlled-design and telemetry rules when changing the execution backend.
