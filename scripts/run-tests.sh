#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p reports

echo "== Shared AI-Mode (agentic loop) =="
python -m pytest ai-services/ai-mode/tests -v --junitxml=reports/ai-mode-tests.xml

echo
echo "== Student 1 - Product Catalogue =="
python -m pytest student-1/tests -v --junitxml=reports/student-1-tests.xml

for n in 2 3 4 5; do
  if [ -f "student-${n}/backend/requirements.txt" ]; then
    echo
    echo "== Student ${n} =="
    python -m pytest "student-${n}/tests" -v --junitxml="reports/student-${n}-tests.xml"
  else
    echo "(student-${n} not implemented yet - skipped)"
  fi
done

echo
echo "JUnit reports written to reports/ - attach them to the technical report."
