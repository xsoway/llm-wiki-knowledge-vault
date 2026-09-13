#!/bin/zsh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$REPO_ROOT/71-03-output"
LOG_FILE="$LOG_DIR/github-sync.log"

mkdir -p "$LOG_DIR"
exec >>"$LOG_FILE" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始同步公开仓库"
git -C "$REPO_ROOT" add -A

if git -C "$REPO_ROOT" diff --cached --quiet; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] 没有可公开的变更"
  exit 0
fi

git -C "$REPO_ROOT" diff --cached --check
git -C "$REPO_ROOT" commit -m "docs: sync public wiki workspace"
git -C "$REPO_ROOT" push origin main
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 同步完成"
