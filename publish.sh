#!/bin/bash
# 把最新快照推到 GitHub Pages。没配 git 就静默跳过，不影响采集。
cd "$(dirname "$0")" || exit 0
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
[ -d .git ] || exit 0
git remote get-url origin >/dev/null 2>&1 || exit 0
git add -A
git diff --cached --quiet && { echo "publish: 无变化"; exit 0; }
git commit -q -m "snapshot $(date +%F)"
git push -q origin main && echo "publish: 已推送"
