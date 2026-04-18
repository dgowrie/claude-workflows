#!/usr/bin/env bash
# ralph.sh — reference shell harness for capital-R Ralph runs of /work-next-task.
#
# Runs /work-next-task in a loop. Fresh claude process per iteration so no conversation
# state is carried across — all state lives in tasks.json + progress.md. Exits on
# completion token, halt token, or iteration cap.
#
# Usage (run from repo root; args accepted in any order):
#   ./skills/work-next-task/scripts/ralph.sh                              # 50 iterations, standard mode
#   ./skills/work-next-task/scripts/ralph.sh 100                          # 100 iterations, standard mode
#   ./skills/work-next-task/scripts/ralph.sh 100 --autonomous             # autonomous mode (push + draft PRs, multi-worker-safe)
#   ./skills/work-next-task/scripts/ralph.sh --autonomous --slug my-ms    # autonomous, explicit slug (required when multiple milestones exist)
#
# Flags:
#   --autonomous        enable push + draft PR discipline; suppresses interactive prompts in the skill
#   --slug <name>       disambiguate which .claude/milestones/<slug>/ to work against (passed through to /work-next-task)
#   <integer>           iteration cap (default 50)
#
# Exit codes:
#   0  MILESTONE_COMPLETE
#   1  HALT (drift, retry cap, or no unblocked tasks; human review)
#   2  reached iteration cap without completion
#   64 usage error

set -euo pipefail

MAX=50
AUTONOMOUS_FLAG=""
SLUG_ARG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --autonomous) AUTONOMOUS_FLAG="--autonomous"; shift ;;
    --slug)
      if [[ -z "${2:-}" ]]; then
        echo "error: --slug requires a value" >&2; exit 64
      fi
      SLUG_ARG="--slug $2"; shift 2 ;;
    [0-9]*) MAX="$1"; shift ;;
    *) echo "error: unknown arg: $1" >&2; exit 64 ;;
  esac
done

# Build the skill invocation, omitting empty flags to avoid trailing whitespace.
CMD="/work-next-task"
[[ -n "$AUTONOMOUS_FLAG" ]] && CMD="$CMD $AUTONOMOUS_FLAG"
[[ -n "$SLUG_ARG" ]] && CMD="$CMD $SLUG_ARG"

for ((i=1; i<=MAX; i++)); do
  echo "=== iteration $i/$MAX ==="

  result=$(claude -p --permission-mode acceptEdits "$CMD")
  echo "$result"

  if [[ "$result" == *"<promise>MILESTONE_COMPLETE</promise>"* ]]; then
    echo "=== milestone complete ==="
    exit 0
  fi

  if [[ "$result" == *"<promise>HALT</promise>"* ]]; then
    echo "=== halted — human review needed ==="
    exit 1
  fi
done

echo "=== reached iteration cap ($MAX) without completion ==="
exit 2
