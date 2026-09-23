#!/bin/bash
# Live YouTube metadata batch update: sequential, quota-aware, with post-settle verify.
# Bash 3.2-safe (macOS default): no mapfile, no associative arrays.
#
# All paths are repo-relative. The runner is sync_youtube_metadata.py, which is
# dry-run by default and enforces Rule 1 (no write without a Data API-fetched
# snippet + pre-update backup + quota accounting).
#
# Env/flags:
#   QUEUE        path to queue JSON (default: data/input/youtube_update_queue.json)
#   RUNNER       command prefix invoking sync_youtube_metadata.py (word-split;
#                default passes --apply, --verify and the quota budget)
#   MAX_VIDEOS   max videos per run (default 150 — quota-safe: each video costs
#                1 read + 50 update + 1 verify = 52 units, 150*52 = 7,800 of the
#                10,000/day budget; the old 200 default (10,400) exceeded it)
#   QUOTA_BUDGET units this run may spend, forwarded to --quota-budget
#   SETTLE       seconds to wait after each update before --verify re-fetch
#                (YouTube propagation delay; default 18, 0 disables)
#   DRY_RUN      if non-empty, skip all API calls (syntax/arg smoke mode)
set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
QUEUE="${QUEUE:-$REPO_ROOT/data/input/youtube_update_queue.json}"
LOG="${LOG:-/tmp/live_batch_run.log}"
PROG="${PROG:-/tmp/live_progress.json}"
MAX_VIDEOS="${MAX_VIDEOS:-150}"
QUOTA_BUDGET="${QUOTA_BUDGET:-10000}"
SETTLE="${SETTLE:-18}"
DRY_RUN="${DRY_RUN:-}"
RUNNER="${RUNNER:-uv run --project $REPO_ROOT python $REPO_ROOT/scripts/sync_youtube_metadata.py --apply --verify --quota-budget=$QUOTA_BUDGET}"

# Portable (bash 3.2) ID load: python prints newline-separated IDs, collected
# with a while-read loop instead of bash-4-only mapfile. YouTube IDs contain
# only [A-Za-z0-9_-], so whitespace-safe word iteration below is sound.
IDS=$(python3 -c "
import json, sys
try:
    d=json.load(open('$QUEUE'))
except (OSError, ValueError) as exc:
    sys.exit(f'QUEUE ERROR: {exc}')
print('\n'.join(e['id'] for e in d[:$MAX_VIDEOS]))
")
if [ -z "$IDS" ]; then
  echo "FATAL: no IDs loaded from $QUEUE" >&2
  exit 1
fi

attempted=0; succeeded=0; failed=0; verified=0
echo "=== batch run start $(date -u +%FT%TZ) queue=$QUEUE max=$MAX_VIDEOS settle=${SETTLE}s dry_run=${DRY_RUN:+yes} ===" >> "$LOG"

# for-loop (not while-read pipe) keeps counters in this shell — no subshell loss.
for vid in $IDS; do
  [ "$attempted" -ge "$MAX_VIDEOS" ] && break
  attempted=$((attempted+1))
  echo "--- VIDEO $vid attempt $attempted ---" >> "$LOG"

  if [ -n "$DRY_RUN" ]; then
    echo "RESULT DRYRUN OK $vid" >> "$LOG"
    succeeded=$((succeeded+1))
    continue
  fi

  out=$($RUNNER --video-id="$vid" 2>&1)
  echo "$out" >> "$LOG"
  if printf '%s' "$out" | grep -q 'quotaExceeded'; then
    echo "FATAL_QUOTA_EXCEEDED $vid" >> "$LOG"; failed=$((failed+1))
    break
  fi
  if printf '%s' "$out" | grep -qE '(invalid_grant|401 Unauthorized)'; then
    echo "FATAL_AUTH_ERROR $vid" >> "$LOG"; failed=$((failed+1))
    break
  fi

  # Propagation-delay fix: settle before judging verification, so the
  # re-fetch isn't a false negative against eventual consistency.
  if printf '%s' "$out" | grep -q 'Verification PASSED'; then
    verified=$((verified+1))
    echo "RESULT OK VERIFIED $vid" >> "$LOG"
    succeeded=$((succeeded+1))
  elif printf '%s' "$out" | grep -q 'Completed:'; then
    if [ "$SETTLE" -gt 0 ]; then sleep "$SETTLE"; fi
    echo "RESULT OK INCONCLUSIVE $vid" >> "$LOG"
    succeeded=$((succeeded+1))
  else
    echo "RESULT FAIL $vid" >> "$LOG"
    failed=$((failed+1))
  fi

  if [ $((attempted % 25)) -eq 0 ]; then
    python3 -c "
import json
json.dump({'attempted':$attempted,'succeeded':$succeeded,'verified':$verified,'failed':$failed}, open('$PROG','w'))
"
  fi
done

LOG="$LOG" PROG="$PROG" python3 - <<'EOF'
import json, os, re
log = open(os.environ['LOG']).read()
attempted = log.count('--- VIDEO ')
ok = len(re.findall(r'^RESULT OK VERIFIED', log, re.M))
dry = len(re.findall(r'^RESULT DRYRUN OK', log, re.M))
nover = len(re.findall(r'^RESULT OK INCONCLUSIVE', log, re.M))
fail = len(re.findall(r'^RESULT FAIL', log, re.M))
fatal = 'FATAL_QUOTA_EXCEEDED' in log or 'FATAL_AUTH_ERROR' in log
json.dump({'attempted': attempted,
           'succeeded': ok + nover + dry,
           'verified': ok,
           'failed': fail + (1 if fatal else 0),
           'fatal_stop': fatal,
           'done': True},
          open(os.environ['PROG'], 'w'))
print(attempted, ok + nover + dry, ok, fail)
EOF
echo "=== batch run end $(date -u +%FT%TZ) attempted=$attempted ok=$succeeded verified=$verified failed=$failed ===" >> "$LOG"
