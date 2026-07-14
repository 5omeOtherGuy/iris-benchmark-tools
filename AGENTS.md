# Repository guidance

This repository contains publishable benchmark tooling, not benchmark data.

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

Before committing:

```bash
python3 -m unittest -v
bash -n run-bench.sh scripts/check-no-secrets.sh
./scripts/check-no-secrets.sh --history
```

Before publishing, inspect `git status`, `git diff --cached`, and the complete tracked path list.
