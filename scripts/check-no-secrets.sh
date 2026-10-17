#!/usr/bin/env bash
# Reject tracked benchmark payloads and common credential forms.
set -euo pipefail

usage() {
  echo "usage: $0 [--history]" >&2
}

SCAN_HISTORY=false
case "${1:-}" in
  "") ;;
  --history) SCAN_HISTORY=true ;;
  *) usage; exit 2 ;;
esac

if [[ -n "${SECRET_SCAN_ROOT:-}" ]]; then
  REPO_ROOT="$SECRET_SCAN_ROOT"
else
  REPO_ROOT="$(git -C "$(dirname -- "$0")" rev-parse --show-toplevel)"
fi
cd "$REPO_ROOT"

FORBIDDEN_PATH='(^|/)(jobs|assets|\.eda-archives|\.benchmark-cache)(/|$)|(^|/)(secrets\.env|\.env|\.benchmark-setup|auth\.json|[^/]*credentials[^/]*\.json)$|\.(tar|tar\.gz|zip)$'

# Split well-known prefixes so the scanner does not match its own source.
CONTENT_PATTERNS=(
  'AK''IA[0-9A-Z]{16}'
  'AS''IA[0-9A-Z]{16}'
  'gh''[oprsu]_[A-Za-z0-9]{20,}'
  'github_pat_''[A-Za-z0-9_]{20,}'
  'sk-ant-''[A-Za-z0-9_-]{20,}'
  'sk-(proj-)?''[A-Za-z0-9_-]{20,}'
  'xox''[aboprs]-[A-Za-z0-9-]{20,}'
  'BEGIN ''(RSA |OPENSSH |EC )?PRIVATE KEY'
)
ASSIGNMENT_NAMES='ANTHROPIC_API_KEY|OPENAI_API_KEY|CLAUDE_CODE_OAUTH_TOKEN'
JSON_NAMES='access''Token|refresh''Token|api''Key'
CONTENT_PATTERNS+=(
  "(${ASSIGNMENT_NAMES})[[:space:]]*=[[:space:]]*['\"]?[A-Za-z0-9][A-Za-z0-9._-]{15,}"
  "\"(${JSON_NAMES})\"[[:space:]]*:[[:space:]]*\"[A-Za-z0-9._-]{16,}\""
)
CONTENT_PATTERN="$(IFS='|'; printf '%s' "${CONTENT_PATTERNS[*]}")"

check_paths() {
  local label="$1"
  local paths="$2"
  local matches
  matches="$(printf '%s\n' "$paths" | grep -E "$FORBIDDEN_PATH" || true)"
  if [[ -n "$matches" ]]; then
    echo "secret scan: forbidden tracked paths in $label:" >&2
    printf '%s\n' "$matches" >&2
    return 1
  fi
}

check_content() {
  local label="$1"
  local tree="$2"
  local matches status=0
  # Report locations and match counts only: printing the line would put a
  # found credential into the (public) CI log.
  if [[ "$tree" == --cached ]]; then
    matches="$(git grep --cached -I -c -E "$CONTENT_PATTERN" -- .)" || status=$?
  else
    matches="$(git grep -I -c -E "$CONTENT_PATTERN" "$tree" -- .)" || status=$?
  fi
  if [[ $status -eq 0 ]]; then
    echo "secret scan: possible credential content in $label (path:matching lines):" >&2
    printf '%s\n' "$matches" >&2
    return 1
  fi
  if [[ $status -ne 1 ]]; then
    echo "secret scan: git grep failed for $label" >&2
    return "$status"
  fi
}

check_paths "index" "$(git ls-files)"
check_content "index" --cached

if [[ "$SCAN_HISTORY" == true ]]; then
  while IFS= read -r revision; do
    check_paths "$revision" "$(git ls-tree -r --name-only "$revision")"
    check_content "$revision" "$revision"
  done < <(git rev-list --all)
fi

echo "secret scan: clean"
