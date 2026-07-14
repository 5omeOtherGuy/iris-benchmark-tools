---
name: benchmark-onboarding
description: Configure a fresh iris-benchmark-tools checkout before its first benchmark. Use automatically before benchmark work when the repository has no `.benchmark-setup` marker, or when the user explicitly asks to onboard, configure, or preflight benchmark tooling. Inventory Iris, Claude Code, Codex, pi, Harbor, Docker, credentials, and local Iris source builds; ask only unresolved setup choices; perform no-token checks; then write the non-secret marker. Do not use after the marker exists.
---

# Benchmark onboarding

Prepare this checkout for benchmark runs without spending model tokens, exposing credentials, or installing system software.

## Guard

1. Resolve the repository root with `git rev-parse --show-toplevel`.
2. If `<root>/.benchmark-setup` exists, stop. Report that onboarding is complete and hand benchmark work to `harness-benchmark`. Do not rewrite or delete the marker.
3. Never store tokens, credential contents, or shell code in the marker.

## Inspect first

Run from the repository root:

```bash
python3 .agents/skills/benchmark-onboarding/scripts/setup.py inspect --repo .
```

The JSON reports command paths and versions, Docker daemon availability, four Harbor contenders (`iris`, `claude-code`, `codex`, `pi`), credential-file presence as booleans, and bounded local Iris source candidates. It does not read credential contents.

Also run these read-only checks when their commands exist:

```bash
df -h .
docker info --format '{{.ServerVersion}}'
harbor --version
harbor run --help
```

Do not infer that a missing host harness CLI makes Harbor's built-in adapter unavailable. Harbor installs built-in agents in task containers. Host command detection provides version and authentication context only.

## Ask only unresolved choices

Summarize detected facts before asking. Use a structured question tool when available; otherwise ask one concise batch. Do not ask for values already established by the user or inspection.

Ask for:

1. **Contenders:** any of Iris, Claude Code, Codex, and pi. Show detected host versions and distinguish Harbor built-ins from Iris's repository adapter.
2. **Iris build, when Iris is selected:**
   - **Latest published release:** no host path; the adapter downloads the current x86_64 GNU/Linux release in the task container.
   - **Detected local source:** show path, full commit, dirty state, and whether `target/release/iris` exists. Build the selected checkout with `cargo build --release` when needed. If no checkout is found and the user chooses a developer build, ask for a destination, then clone `https://github.com/5omeOtherGuy/iris-agent.git` only after confirmation and build its current default branch; never replace or reset an existing checkout.
   - **Installed binary:** show `command -v iris` and `iris --version`.
   - **Custom binary:** ask for an absolute path and verify it with `<path> --version`.
   Never silently substitute one build source for another. Record the exact version or commit in the eventual run report.
3. **Private jobs directory and concurrency:** default to `<root>/jobs` and `1`. Warn before choosing concurrency above one because shared OAuth refresh and resource contention can invalidate timing.
4. **Harbor location, only when `harbor` is absent:** ask for an existing source checkout to use as `HARBOR_DIR`. This onboarding mode does not install Harbor, Docker, harness CLIs, or package managers.

Leave model, task scope, attempts, comparison type, and budget to the per-run `harness-benchmark` interview; those are experiment choices, not machine setup.

## Resolve blockers

Require these before creating the marker:

- Docker CLI exists and the daemon responds.
- Harbor runs from `PATH`, or an existing `HARBOR_DIR` works through `uv run harbor`.
- The jobs directory can be created and written.
- A selected non-release Iris binary exists and `--version` succeeds.
- Authentication material is present for the intended provider without displaying it:
  - Iris/Anthropic: Claude credential store or explicit `IRIS_CLAUDE_CREDENTIALS_PATH`.
  - Iris/OpenAI or Antigravity: Iris auth store or explicit `IRIS_AUTH_JSON_PATH`.
  - Claude Code: `CLAUDE_CODE_OAUTH_TOKEN`; if absent, the user must run `claude setup-token` interactively and export it.
  - Codex: normal Codex auth store or provider credentials supported by Harbor.
  - pi: provider credentials appropriate to the model chosen later; mark this as a manual check if no provider has been selected.

Never ask the user to paste a token into chat. Never open auth files. Explain missing prerequisites and wait for the user rather than writing a partial marker.

## No-token compatibility check

After prerequisites pass, run one install-only trial for each selected contender with a placeholder model accepted by that adapter and identical single-task scope:

```bash
./run-bench.sh <contender> <provider/model> --install-only -l 1 -y --job-name setup__<contender>
```

State that this can download container images and agent packages but does not make a model request. If the installed Harbor version does not accept these arguments, inspect `harbor run --help` and adapt to its implemented CLI rather than guessing.

Classify failures as Docker, Harbor, adapter, binary compatibility, authentication, or network setup. Do not create the marker while a selected contender's install-only check fails.

## Persist setup

Use only validated choices:

```bash
python3 .agents/skills/benchmark-onboarding/scripts/setup.py configure \
  --repo . \
  --harness <name> [--harness <name> ...] \
  --iris-build <latest-release|installed|local-source|custom> \
  --jobs-dir <private-path> \
  --concurrency <n> \
  [--harbor-dir <path>] \
  [--iris-binary <path>]
```

The script writes `.benchmark-setup` atomically with mode `0600`. The file contains paths and selections only, is ignored by Git, and is consumed by `run-bench.sh`. Environment variables continue to override marker values.

Finish with detected versions, selected harnesses, Iris build identity, jobs path, concurrency, authentication readiness by boolean status, and the exact first smoke-run commands. Then hand off to `harness-benchmark`.
