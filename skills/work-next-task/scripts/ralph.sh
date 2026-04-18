#!/usr/bin/env bash
# ralph.sh — reference shell harness for capital-R Ralph runs of /work-next-task.
#
# Runs /work-next-task in a loop. Fresh claude process per iteration so no conversation
# state is carried across — all state lives in tasks.json + progress.md. Exits on
# completion token, halt token, or iteration cap.
#
# Usage:
#   ./scripts/ralph.sh                    # 50 iterations, standard mode (single-worker)
#   ./scripts/ralph.sh 100                # 100 iterations, standard mode
#   ./scripts/ralph.sh 100 --autonomous   # autonomous mode (push + draft PRs, multi-worker-safe)
#
# Exit codes:
#   0  MILESTONE_COMPLETE
#   1  HALT (drift, retry cap, or no unblocked tasks — human review)
#   2  reached iteration cap without completion

set -euo pipefail

MAX="${1:-50}"
AUTONOMOUS_FLAG=""
if [[ "${2:-}" == "--autonomous" ]]; then
  AUTONOMOUS_FLAG="--autonomous"
fi

for ((i=1; i<=MAX; i++)); do
  echo "=== iteration $i/$MAX ==="

  result=$(claude -p --permission-mode acceptEdits "/work-next-task ${AUTONOMOUS_FLAG}")
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
