#!/usr/bin/env bash
# Harness comparison runner (iris vs claude-code vs codex) on terminal-bench 2.0.
#
# Usage:
#   ./run-bench.sh iris        anthropic/claude-fable-5 [extra harbor args...]
#   ./run-bench.sh claude-code anthropic/claude-fable-5 [extra harbor args...]
#   ./run-bench.sh codex       openai/gpt-5.5-codex     [extra harbor args...]
#
# Defaults are tuned for this machine (7 GB RAM): 1 concurrent trial,
# results under /mnt/bench/work/jobs (HDD-backed ext4).
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd "$(dirname "$0")"
export PYTHONPATH="/mnt/bench/work${PYTHONPATH:+:$PYTHONPATH}"

# Durable Claude Code OAuth token (from `claude setup-token`) for repeated
# claude-code legs: sourced from secrets.env unless already set in the env, so
# many legs reuse one token instead of minting per run. secrets.env is local
# benchmark infra (this dir is not a git repo, so it is never committed); iris
# legs do not need it (they auth from ~/.claude/.credentials.json). Explicit
# `if` (not `&& source`) so a missing file does not trip `set -e`.
if [[ -f secrets.env && -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
  source secrets.env
fi

AGENT="${1:?agent (iris|claude-code|codex|...)}"
MODEL="${2:?model (e.g. anthropic/claude-fable-5)}"
shift 2

case "$AGENT" in
  iris) AGENT="agents.iris_installed:Iris" ;;
esac

EXTRA_ENV=()
# Codex CLI: reuse the host's ChatGPT OAuth instead of an API key.
if [[ "$AGENT" == "codex" && -f "$HOME/.codex/auth.json" ]]; then
  EXTRA_ENV+=(--ae "CODEX_AUTH_JSON_PATH=$HOME/.codex/auth.json")
fi
# Claude Code: subscription OAuth token (from `claude setup-token`).
if [[ "$AGENT" == "claude-code" && -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
  EXTRA_ENV+=(--ae "CLAUDE_FORCE_OAUTH=1" --ae "CLAUDE_CODE_OAUTH_TOKEN=$CLAUDE_CODE_OAUTH_TOKEN")
fi

harbor run \
  --dataset terminal-bench@2.0 \
  --agent "$AGENT" \
  --model "$MODEL" \
  --n-concurrent 1 \
  --jobs-dir /mnt/bench/work/jobs \
  "${EXTRA_ENV[@]}" \
  "$@"

echo
echo "Results in /mnt/bench/work/jobs. Reclaim docker space when done comparing:"
echo "  docker system prune -af --volumes"
