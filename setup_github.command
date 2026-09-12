#!/bin/bash
# 双击：建仓库、开 GitHub Pages、首次发布。只需要跑一次。
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"; cd "$DIR"
REPO="mise-park-calendar"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

if ! command -v gh >/dev/null; then
  echo "没装 GitHub CLI。先跑：  brew install gh"
  read -n1 -p "按任意键关闭…"; exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "GitHub 还没登录。先跑：  gh auth login"
  read -n1 -p "按任意键关闭…"; exit 1
fi

cat > .gitignore <<'G'
run.log
__pycache__/
.DS_Store
G

[ -d .git ] || git init -q -b main
git add -A
git diff --cached --quiet || git commit -q -m "Mise Park 场地占用记录"

if git remote get-url origin >/dev/null 2>&1; then
  git push -q -u origin main
else
  gh repo create "$REPO" --public --source=. --remote=origin --push
fi

gh api -X POST "repos/{owner}/$REPO/pages" \
  -f "source[branch]=main" -f "source[path]=/" >/dev/null 2>&1 \
  && echo "已开启 GitHub Pages" || echo "Pages 已经是开着的"

USER=$(gh api user -q .login)
echo
echo "────────────────────────────────────────"
echo "  https://$USER.github.io/$REPO/"
echo "────────────────────────────────────────"
echo "首次部署要等 1–2 分钟。以后每天抓完自动推送。"
read -n1 -p "按任意键关闭…"
