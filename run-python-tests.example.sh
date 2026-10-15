#!/usr/bin/env bash
# Stand-in for the real VM-mode runner: prints what Conductor passed and exits 0.
# Copy it to run-python-tests.sh (or point PYTHON_TEST_RUNNER_PATH at it) to try VM mode.
set -euo pipefail

echo "Arguments:"
for arg in "$@"; do
  echo "  $arg"
done

[[ -n "${ALLURE_TOKEN:-}" ]] && echo "ALLURE_TOKEN is set" || echo "ALLURE_TOKEN is not set"
[[ -n "${ZEPHYR_TOKEN:-}" ]] && echo "ZEPHYR_TOKEN is set" || echo "ZEPHYR_TOKEN is not set"

for i in 1 2 3 4 5; do
  echo "step $i/5"
  sleep 1
done
echo "done"
