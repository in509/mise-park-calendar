#!/bin/bash
# Double-click this file to install the daily Mise Park snapshot job.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.yi.mise-calendar"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "找不到 python3。请先运行:  xcode-select --install"
  echo "装完之后再双击一次这个文件。"
  read -n1 -p "按任意键关闭…"; exit 1
fi
echo "python3: $PY"

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$DIR/run_daily.sh</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartCalendarInterval</key>
  <array><dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>30</integer></dict></array>
  <key>StandardOutPath</key><string>$DIR/run.log</string>
  <key>StandardErrorPath</key><string>$DIR/run.log</string>
</dict></plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "已安装定时任务：每天 07:30 自动抓取（Mac 睡着的话，醒来后补跑）"
echo
echo "现在先跑一次…"
bash "$DIR/run_daily.sh"
open "$DIR/index.html"
echo
echo "完成。以后每天自动更新，直接打开 index.html 就行。"
read -n1 -p "按任意键关闭…"
