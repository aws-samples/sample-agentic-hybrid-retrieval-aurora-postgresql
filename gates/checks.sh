#!/usr/bin/env bash
#
# gates/checks.sh - DAT410 gate orchestrator.
#
# Runs each implemented gate, prints its captured output verbatim, and collects a
# PASS / FAIL / BLOCKED verdict from the gate's exit code:
#
#   0 PASS    - the gate ran and its assertions held.
#   1 FAIL    - the gate ran and an assertion failed (a real defect).
#   2 BLOCKED - the subject under test does not exist yet (honest, not a pass).
#
# The orchestrator exits nonzero only when at least one gate FAILs. BLOCKED gates
# are reported but do not fail the run: they mark work the build order has not
# reached. This lets the harness ship before the code it tests (SPEC-session
# Section 10: build the gate harness early).
#
# Usage:
#   gates/checks.sh            # run every implemented gate
#   gates/checks.sh G-11 G-21  # run a subset by gate id
#
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATES_DIR="$ROOT_DIR/gates"

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON="$ROOT_DIR/.venv/bin/python"
else
  PYTHON="$(command -v python3 || command -v python)"
fi

# Gate registry: "G-ID|script|one-line title". Order is build-order, not id-order.
GATES=(
  "G-11|noun_lint.py|Law 1 noun lint"
  "G-13|verify_sql_golden.py|Verify-SQL golden test"
  "G-14|empty_db_ui_test.py|Empty-database UI test"
  "G-17|registry_drift.py|Registry drift"
  "G-21|fixture_arithmetic.py|Fixture arithmetic (D14) on the engine"
  "G-23|route_contract.py|Route contract (D16)"
  "G-25|admission_determinism.py|Admission determinism (D21)"
  "G-27|rls_enforcement.py|RLS enforcement (D24)"
  "G-29|masking_determinism.py|Column masking + Law-2 determinism"
  "G-30|participant_ceremony.py|Participant zero-ceremony identity (A1)"
  "G-31|persona_equivalence.py|Persona equivalence after the A7 collapse"
)

WANT=("$@")

want_gate() {
  local id="$1"
  [[ ${#WANT[@]} -eq 0 ]] && return 0
  local w
  for w in "${WANT[@]}"; do
    [[ "$w" == "$id" ]] && return 0
  done
  return 1
}

declare -a PASS_IDS=() FAIL_IDS=() BLOCKED_IDS=()

for entry in "${GATES[@]}"; do
  IFS='|' read -r id script title <<<"$entry"
  want_gate "$id" || continue

  echo "############################################################"
  echo "# $id  $title"
  echo "# gates/$script"
  echo "############################################################"

  "$PYTHON" "$GATES_DIR/$script"
  code=$?

  case "$code" in
    0) PASS_IDS+=("$id") ;;
    2) BLOCKED_IDS+=("$id") ;;
    *) FAIL_IDS+=("$id") ;;
  esac
  echo
done

echo "############################################################"
echo "# SUMMARY"
echo "############################################################"
echo "PASS   (${#PASS_IDS[@]}): ${PASS_IDS[*]:-none}"
echo "FAIL   (${#FAIL_IDS[@]}): ${FAIL_IDS[*]:-none}"
echo "BLOCKED(${#BLOCKED_IDS[@]}): ${BLOCKED_IDS[*]:-none}"
echo
if [[ ${#FAIL_IDS[@]} -gt 0 ]]; then
  echo "RESULT: RED - ${#FAIL_IDS[@]} gate(s) failing: ${FAIL_IDS[*]}"
  exit 1
fi
if [[ ${#BLOCKED_IDS[@]} -gt 0 ]]; then
  echo "RESULT: no failures; ${#BLOCKED_IDS[@]} gate(s) blocked on unbuilt deps"
  exit 0
fi
echo "RESULT: GREEN - all requested gates pass"
exit 0
