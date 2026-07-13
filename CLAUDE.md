# Benchmark tooling — /mnt/bench/work

Versioned tooling for the iris-vs-other-harness benchmark (Harbor + terminal-bench).
This directory deliberately mixes **tooling** (safe to push) with **credentials
and trial data** (must NEVER leave this machine). Read before committing.

## NEVER push (hard rule)

These are gitignored, but the rule holds even if `.gitignore` is edited or bypassed:

- **`secrets.env`** — a live Claude Code OAuth token (`CLAUDE_CODE_OAUTH_TOKEN`).
  A working credential billed to a real Max subscription. Leaking it = account
  compromise.
- **Any credential file** — `*.credentials.json`, `auth.json`, or anything
  carrying a token, key, or bearer.
- **`jobs/`** — per-trial benchmark data. Not just large: trial logs and agent
  transcripts (`iris.txt`, `claude-code.txt`, `agent/iris-sessions/**`) can embed
  uploaded credentials or token fragments. Treat all of it as secret-bearing.
- **`assets/`** — prebuilt iris binaries / tarballs. Not secret, but never in VCS
  (large, regenerable from GitHub releases).

## Safe to track / push

`run-bench.sh`, `analyze_tokens.py`, `agents/iris_installed.py`, `README.md`,
`fixtures/` (synthetic golden fixtures — no real secrets or trial data), this
`CLAUDE.md`, and `.gitignore`.

## Before any push

1. `git status` and `git diff --cached` — confirm NO token, credential, or trial
   data is staged. If in doubt, do not push.
2. Any remote MUST be private.
3. `.gitignore` is fail-safe (whitelist: everything ignored unless explicitly
   allowed). To track a NEW file, add an explicit allow-rule AND verify it holds
   no secrets or data.

## Layout

- Tooling (tracked): adapter `agents/iris_installed.py`, runner `run-bench.sh`,
  analyzer `analyze_tokens.py`, `fixtures/`.
- Data (ignored, machine-local): `jobs/`, `assets/`, `secrets.env`.
- Other benchmark data lives elsewhere on `/mnt/bench` (docker root, sccache,
  `/mnt/bench/archive`) and is never under this repo.
- Method/runbook: the `harness-benchmark` skill; per-run details: `README.md`.
