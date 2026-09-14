#!/bin/zsh
# Loop pytest suites until a run goes red; save that run's full output.
#
# Built while chasing a rare deadline miss in the rollup race suites
# (tests/services/test_rollup_serialization.py, tests/api/test_rollup_deadlock.py):
# one run in ~475 blew the ~5s wait_for deadline (~6s wall vs ~0.7s baseline)
# and never reproduced under capture — soaks under 8-way CPU stress included.
# Attributed to a transient host stall; see the closing comment on #130.
# If it goes red again, this saves the evidence the first sighting lost.
#
# Usage: scripts/race_loop.sh <out_file> <max_runs> <pytest args...>
#   scripts/race_loop.sh red.log 300 tests/services/test_rollup_serialization.py tests/api/test_rollup_deadlock.py

# A flake hunt against a stale lock measures a dependency set CI never runs; the
# Makefile's export holds the reasoning. This script calls uv directly, so it
# cannot inherit that one.
export UV_LOCKED=1

out_file="$1"; max_runs="${2:-80}"; shift 2
for i in $(seq 1 $max_runs); do
  out=$(uv run pytest "$@" -q --tb=long 2>&1)
  tail=$(echo "$out" | tail -1)
  if ! echo "$tail" | grep -q " passed"; then
    echo "RED on run $i ($tail)"
    echo "$out" > "$out_file"
    exit 1
  fi
  [ $((i % 10)) -eq 0 ] && echo "…$i green ($tail)"
done
echo "ALL $max_runs GREEN"
