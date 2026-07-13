# Harness benchmarking workspace (terminal-bench 2.0 via Harbor)

Compare iris-agent against other harnesses (Claude Code, Codex CLI, ...) on
identical tasks. Everything heavy lives on the HDD-backed ext4 mount
`/mnt/bench` (loop image at `/mnt/Data/iris-bench/bench.img`, in fstab):

- `/mnt/bench/docker` — Docker data-root (images/containers)
- `/mnt/bench/cache/sccache` — sccache (moved off the SSD)
- `/mnt/bench/work` — this workspace (adapter, jobs, assets)

## Layout

- `agents/iris_installed.py` — Harbor installed-agent adapter for iris.
  Uploads `assets/.../iris` + credentials into the task container, writes a
  minimal `~/.iris/settings.json`, runs
  `iris -p <instruction> --approve --dangerously-skip-permissions`.
- `assets/` — iris release binary (refresh: re-download the
  `x86_64-unknown-linux-gnu` tarball from GitHub releases after a new release).
- `run-bench.sh` — runner with machine-tuned defaults (`--n-concurrent 1`).
- `jobs/` — results (one dir per `--job-name`; `result.json` + per-trial logs).

## Auth

- **iris (anthropic/...)**: uploads host `~/.claude/.credentials.json` — iris
  bootstraps its Anthropic OAuth from Claude Code's credentials. No setup.
- **iris (openai-codex/...)**: uploads host `~/.iris/auth.json`. No setup.
- **claude-code**: needs `CLAUDE_CODE_OAUTH_TOKEN` — run `claude setup-token`
  once and export it (the runner then passes `CLAUDE_FORCE_OAUTH=1`).
- **codex**: uses host `~/.codex/auth.json` automatically (ChatGPT OAuth).

Caveat: two harnesses sharing one OAuth credential can race on token refresh.
Run matchups sequentially (the default), not simultaneously.

## Typical matchup (same model, ~5 tasks)

```bash
cd /mnt/bench/work
./run-bench.sh iris        anthropic/claude-fable-5 -l 5 -y --job-name iris-smoke
./run-bench.sh claude-code anthropic/claude-fable-5 -l 5 -y --job-name cc-smoke
harbor view /mnt/bench/work/jobs
```

`-l N` takes the first N tasks (same set for both runs); `-i '<glob>'` /
`-x '<glob>'` include/exclude tasks by name; drop `-l` for the full ~89 tasks.

## Cleanup

- Between runs of one comparison: keep images (they're shared per task).
- After a comparison: `docker system prune -af --volumes` (all on /mnt/bench).
- The loop image is sparse: it only occupies real HDD space for data written.
  To shrink after big deletions: `fstrim /mnt/bench`.
- Old jobs: archive/delete dirs under `jobs/`.

## Resource notes (this machine)

- 7 GB RAM → `--n-concurrent 1` (2 at most). SSD stays untouched by runs.
- For big/parallel runs later: Harbor supports cloud sandboxes
  (`--env daytona|modal|e2b`), zero local Docker.
