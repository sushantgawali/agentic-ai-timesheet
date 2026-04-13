#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_local.sh — Run audit pipeline locally and push report to GitHub Pages
#
# Usage:
#   ./run_local.sh [data_version]
#
# Examples:
#   ./run_local.sh              # uses v5 (default), full run
#   ./run_local.sh v3           # uses v3 data
#   RESUME=1 ./run_local.sh     # skip agents whose state files already exist
#   STAGGER_DELAY=3 ./run_local.sh   # wait 3s between parallel agent starts
#
# Requirements:
#   - python3.11 in PATH (mcp package requires >=3.10)
#   - claude CLI installed and authenticated via: claude login
#   - git SSH access to the remote
# ---------------------------------------------------------------------------
set -euo pipefail

# Ensure we use Claude Code subscription auth, not an API key
unset ANTHROPIC_API_KEY

# Verify claude CLI is authenticated
if ! claude auth status 2>/dev/null | grep -q '"loggedIn": true'; then
  echo "ERROR: Claude Code is not logged in. Run: claude login"
  exit 1
fi

DATA_VERSION="${1:-v5}"
DATA_DIR="data/${DATA_VERSION}"
OUT_DIR="output"
SITE_DIR="site"

echo "========================================"
echo " Agentic AI Timesheet — Local Run"
echo " Data: ${DATA_DIR}  |  Output: ${OUT_DIR}"
echo "========================================"

# --- Step 1: Run the audit pipeline ---
echo ""
echo "[1/4] Running audit pipeline..."
DATA_DIR="${DATA_DIR}" OUT_DIR="${OUT_DIR}" \
  RESUME="${RESUME:-0}" \
  STAGGER_DELAY="${STAGGER_DELAY:-0}" \
  python3.11 audit_agent_sdk.py

# --- Step 2: Check a report was generated ---
REPORT=$(ls "${OUT_DIR}"/audit_*.html 2>/dev/null | sort | tail -1)
if [[ -z "${REPORT}" ]]; then
  echo "ERROR: No report found in ${OUT_DIR}/. Pipeline may have failed."
  exit 1
fi
REPORT_FILE=$(basename "${REPORT}")
echo ""
echo "Report generated: ${REPORT}"

# --- Step 3: Clone gh-pages into a temp dir so we preserve history ---
echo ""
echo "[2/4] Fetching existing reports from gh-pages..."
WORK_DIR=$(mktemp -d)
trap 'rm -rf "${WORK_DIR}"' EXIT

REMOTE_URL=$(git remote get-url origin)

if git ls-remote --exit-code origin gh-pages > /dev/null 2>&1; then
  git clone --depth=1 --branch gh-pages "${REMOTE_URL}" "${WORK_DIR}" 2>/dev/null
  echo "  Previous reports cloned to ${WORK_DIR}/"
else
  echo "  No existing gh-pages branch — starting fresh."
  git init -b gh-pages "${WORK_DIR}"
  git -C "${WORK_DIR}" remote add origin "${REMOTE_URL}"
fi

# --- Step 4: Copy only the new report and regenerate index ---
echo ""
echo "[3/4] Adding new report and regenerating index..."
cp "${REPORT}" "${WORK_DIR}/${REPORT_FILE}"
python3.11 generate_index.py "${WORK_DIR}"
echo "  Copied: ${REPORT_FILE}"
echo "  index.html updated."

# --- Step 5: Push to gh-pages ---
echo ""
echo "[4/4] Pushing to gh-pages..."
git -C "${WORK_DIR}" config user.name "$(git config user.name 2>/dev/null || echo 'Local Run')"
git -C "${WORK_DIR}" config user.email "$(git config user.email 2>/dev/null || echo 'local@run')"
git -C "${WORK_DIR}" add "${REPORT_FILE}" index.html
git -C "${WORK_DIR}" commit -m "audit: add ${REPORT_FILE}"
git -C "${WORK_DIR}" push origin gh-pages

echo ""
echo "========================================"
echo " Done! Report live at GitHub Pages."
echo " https://sushantgawali.github.io/agentic-ai-timesheet/"
echo "========================================"
