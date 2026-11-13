#!/usr/bin/env bash
# SessionStart hook: run both test suites; stdout is added to Claude's context.
cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}" || exit 0

run() { # run <label> <dir> <command...>
  local label=$1 dir=$2 out status
  shift 2
  out=$(cd "$dir" && "$@" 2>&1)
  status=$?
  if [ "$status" -eq 0 ]; then
    echo "$label: PASS ($(echo "$out" | grep -E '[0-9]+ passed' | tail -1 | xargs))"
  else
    echo "$label: FAIL (exit $status), last 30 lines:"
    echo "$out" | tail -30
  fi
}

echo "Baseline test run at session start:"
run backend backend uv run pytest -q
run frontend frontend npm test --silent
exit 0
