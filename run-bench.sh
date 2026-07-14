#!/usr/bin/env bash
# Run one Harbor benchmark leg. Run competing harnesses sequentially with the
# same model and task-selection arguments for a controlled comparison.
#
# Usage:
#   ./run-bench.sh iris        anthropic/claude-sonnet-5 [harbor args...]
#   ./run-bench.sh claude-code anthropic/claude-sonnet-5 [harbor args...]
#   ./run-bench.sh codex       openai/gpt-5.5-codex     [harbor args...]
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
JOBS_DIR="${BENCH_JOBS_DIR:-$ROOT_DIR/jobs}"
CONCURRENCY="${HARNESS_BENCH_CONCURRENCY:-1}"
export PATH="$HOME/.local/bin:$PATH"
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <agent> <model> [harbor args...]" >&2
  exit 2
fi
if [[ ! "$CONCURRENCY" =~ ^[1-9][0-9]*$ ]]; then
  echo "HARNESS_BENCH_CONCURRENCY must be a positive integer" >&2
  exit 2
fi

AGENT="$1"
MODEL="$2"
shift 2

case "$AGENT" in
  iris) AGENT="agents.iris_installed:Iris" ;;
esac

EXTRA_ENV=()
if [[ "$AGENT" == "codex" && -f "$HOME/.codex/auth.json" ]]; then
  EXTRA_ENV+=(--ae "CODEX_AUTH_JSON_PATH=$HOME/.codex/auth.json")
fi
if [[ "$AGENT" == "claude-code" ]]; then
  if [[ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
    echo "CLAUDE_CODE_OAUTH_TOKEN is required; create it with 'claude setup-token'" >&2
    exit 2
  fi
  EXTRA_ENV+=(
    --ae "CLAUDE_FORCE_OAUTH=1"
    --ae "CLAUDE_CODE_OAUTH_TOKEN=$CLAUDE_CODE_OAUTH_TOKEN"
  )
fi

mkdir -p "$JOBS_DIR"

if [[ -n "${HARBOR_DIR:-}" ]]; then
  if [[ ! -d "$HARBOR_DIR" ]]; then
    echo "HARBOR_DIR is not a directory: $HARBOR_DIR" >&2
    exit 2
  fi
  cd "$HARBOR_DIR"
  if command -v uv >/dev/null 2>&1; then
    HARBOR=(uv run harbor)
  elif command -v harbor >/dev/null 2>&1; then
    HARBOR=(harbor)
  else
    echo "Harbor is unavailable; install it or install uv for HARBOR_DIR" >&2
    exit 127
  fi
elif command -v harbor >/dev/null 2>&1; then
  HARBOR=(harbor)
else
  echo "Harbor is unavailable; put 'harbor' on PATH or set HARBOR_DIR" >&2
  exit 127
fi

"${HARBOR[@]}" run \
  --dataset terminal-bench@2.0 \
  --agent "$AGENT" \
  --model "$MODEL" \
  --n-concurrent "$CONCURRENCY" \
  --jobs-dir "$JOBS_DIR" \
  "${EXTRA_ENV[@]}" \
  "$@"

printf '\nResults: %s\n' "$JOBS_DIR"
