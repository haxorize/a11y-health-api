#!/usr/bin/env bash
# Loop pytest suites until a run goes red; save that run's full output.
#
# Built for a rare deadline miss in the rollup race suites that never reproduced
# under capture; the sighting is in 8837266's message and the closing comment on
# #130. If it goes red again, this saves the evidence the first sighting lost.
#
# Usage: scripts/race_loop.sh <out_file> <max_runs> <pytest args...>
#   scripts/race_loop.sh red.log 300 tests/services/test_rollup_serialization.py tests/api/test_rollup_deadlock.py

set -euo pipefail

# All three arguments are required and max_runs is checked. Defaulted and
# unvalidated, a non-numeric count made `seq` fail, the loop body never ran,
# and the script closed with its all-clear banner having hunted nothing; a
# missing one made `shift 2` fail without stopping, leaving the log path in
# $@ for pytest to collect and then overwriting it with the collection error.
if [ $# -lt 3 ]; then
  echo "usage: scripts/race_loop.sh <out_file> <max_runs> <pytest args...>" >&2
  exit 2
fi
out_file="$1"; max_runs="$2"; shift 2
case "$max_runs" in
  "" | *[!0-9]*) echo "race_loop: max_runs must be a positive integer, got '$max_runs'" >&2; exit 2 ;;
esac
[ "$max_runs" -gt 0 ] || { echo "race_loop: max_runs must be greater than 0" >&2; exit 2; }
if [ -d "$out_file" ]; then echo "race_loop: out_file '$out_file' is a directory" >&2; exit 2; fi
# Refused rather than truncated: an all-green hunt must not leave the last red
# log for someone to read as this run's evidence, and a rerun must not wipe it.
if [ -s "$out_file" ]; then echo "race_loop: out_file '$out_file' already holds a log; move it first" >&2; exit 2; fi

# A flake hunt against a stale lock measures a dependency set CI never runs; the
# Makefile's export holds the reasoning. This script calls uv directly, so it
# cannot inherit that one.
export UV_LOCKED=1

for i in $(seq 1 "$max_runs"); do
  # The verdict is pytest's exit status, not a substring of its summary line.
  # A mixed run prints "1 failed, 1 passed in 0.02s", which contains " passed"
  # — so the substring test scored every partial failure green and dropped the
  # output. A partial failure is precisely what this hunt is for: one of the
  # two suites blowing its wait_for deadline while its sibling passes.
  if out=$(uv run pytest "$@" -q --tb=long 2>&1); then
    rc=0
  else
    rc=$?
  fi
  tail=$(printf '%s\n' "$out" | tail -1)
  if [ "$rc" -ne 0 ]; then
    echo "RED on run $i ($tail)"
    printf '%s\n' "$out" > "$out_file"
    exit 1
  fi
  if [ $((i % 10)) -eq 0 ]; then
    echo "…$i green ($tail)"
  fi
done
echo "ALL $max_runs GREEN"
