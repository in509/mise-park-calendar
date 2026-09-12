#!/bin/bash
# launchd 每天调用这个：先抓取，再发布。
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="
python3 fetch_mise.py || { echo "抓取失败"; exit 1; }
./publish.sh
