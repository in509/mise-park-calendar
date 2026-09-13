#!/bin/bash
# 双击：把这个目录建成 GitHub 仓库并推上去。之后在 Railway 里接上它，
# 每次 git push 就会自动部署。只需要跑一次。
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

[ -d .git ] || git init -q -b main
git add -A
git diff --cached --quiet || git commit -q -m "Mise Park 场地占用记录"

if git remote get-url origin >/dev/null 2>&1; then
  git push -q -u origin main
  echo "已推送到 $(git remote get-url origin)"
else
  gh repo create "$REPO" --private --source=. --remote=origin --push
  echo "已创建 $(gh api user -q .login)/$REPO 并推送"
fi

echo
echo "下一步：Railway → 你的服务 → Settings → Source → Connect Repo，选这个仓库和 main 分支。"
echo "接上之后，以后改完代码只要：  git add -A && git commit -m '...' && git push"
read -n1 -p "按任意键关闭…"
