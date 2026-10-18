# Repository guidance

## Profile
- Purpose: Harbor adapter, runner, analyzer and agent skills for controlled Iris versus coding-agent harness benchmarks on Terminal-Bench.
- Stage: prototype (repository standard 2026-10-18)
- Gate: `scripts/gate` (CI job `gate`)
- Landing: direct to main after a green gate; agents land: yes
- Release: none; agents release: no
- Outside issues and PRs: agents triage; outside PRs merge: owner approves
- Sensitive paths: `agents/iris_installed.py` and `run-bench.sh` (credential upload and forwarding; public interface), `analyze_tokens.py` (public Markdown and JSON output), `.agents/` (orb setup, onboarding credential inventory, skills), `.claude/skills/`, `AGENTS.md` (`CLAUDE.md` links to it), `.github/`, `scripts/`, `requirements-harbor.txt`, `.gitignore` (fail-safe allowlist), `test_repository_security.py`, `SECURITY.md`, `README.md` (agent run rules and authentication steps)
- Deliberate deviations: the Safety rules (no credentials, trial data or binaries in Git; `jobs/` private; fail-safe root allowlist), the onboarding marker before any token spend, sequential contenders with missing telemetry never turned into zero, and the history secret scan before every commit.

This repository contains publishable benchmark tooling, not benchmark data.

## Map

- `run-bench.sh`: runs one Harbor benchmark leg.
- `agents/iris_installed.py`: Harbor adapter that installs and runs Iris in task containers; supported Harbor range in the README.
- `analyze_tokens.py`: Markdown and JSON token, cache and cost comparison.
- `.agents/skills/`: the canonical benchmark skills; `.claude/skills/` links to them.
- `fixtures/`: synthetic parser fixtures only.
- `requirements-harbor.txt`: uv lock of the Harbor version CI checks against.
- `scripts/gate`, `scripts/check-no-secrets.sh`: the gate and its secret scan.
- `.agents/setup`: orb setup (Python 3.12 `.venv` with the locked Harbor).

## Landing

Commit small Conventional Commits straight to `main`, run `scripts/gate`, and push at the end of every session. Try risky ideas on `spike/<slug>`; merge it, or tag it `archive/<slug>` and delete it. Commit by explicit path. Use the author's GitHub noreply address. A change to a sensitive path gets an independent review (another agent or the owner) of the diff before it is pushed, with the verdict in the commit body.

## Safety

- Never commit credentials, environment files, real trial logs, transcripts, generated reports, downloaded binaries, archives, or task assets.
- Treat every `jobs/` tree as private; model and tool output can contain credentials or sensitive task content.
- Keep generated data in the ignored `jobs/` directory or an external directory selected with `BENCH_JOBS_DIR`.
- Do not source credential files from repository scripts. Accept secrets only through the process environment or explicit paths.
- Preserve the fail-safe root allowlist in `.gitignore`. Review every new tracked path.

## Workflow

- Before any benchmark setup or run, check for `.benchmark-setup`. If it is absent, use `benchmark-onboarding` and do not spend model tokens until its preflight succeeds. Never run that skill when the marker exists.
- Use the `harness-benchmark` skill to design and run comparisons after onboarding.
- Use `harness-telemetry` as the source-schema contract.
- Use `benchmark-telemetry-report` for deep analysis and report generation.
- Run contenders sequentially by default. Use identical task filters and model IDs for controlled comparisons.
- Keep failures and parser warnings visible; never turn missing telemetry into zero.

## Verification

Before committing, run the gate. CI runs the same command in the job `gate`:

```bash
scripts/gate
```

It runs the unit tests, `bash -n` on each shell script, an import check of the Iris adapter against the locked Harbor, and `./scripts/check-no-secrets.sh --history`. It needs Harbor from `requirements-harbor.txt`; `.agents/setup` installs it in `.venv`, which the gate uses when present.

Run one test module with `python3 -m unittest test_analyze_tokens -v`, or one test with `python3 -m unittest test_analyze_tokens.TokenAnalyzerTests.test_base_netting`.

Before publishing, inspect `git status`, `git diff --cached`, and the complete tracked path list.
