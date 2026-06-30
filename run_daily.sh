#!/bin/zsh
# 每日盤前自動執行：產生預估 → 更新網頁 → 推送 GitHub Pages
# 搭配 cron 使用（見 README）。token 由 .finmind_token 自動讀取，無需設環境變數。

set -e
PROJECT_DIR="/Users/aidenkaoiii/Google 雲端硬碟/個人AI/股市趨勢預估"
PYTHON="/opt/anaconda3/bin/python3"

cd "$PROJECT_DIR" || { echo "找不到專案目錄"; exit 1; }

echo "===== $(date '+%Y-%m-%d %H:%M') 開始 ====="
"$PYTHON" main.py

# 只在有變更時提交
git add data docs
if git diff --cached --quiet; then
  echo "網頁無變更，跳過推送"
  exit 0
fi
git commit -m "每日更新 $(date +%F)"

# 推送，失敗時指數退避重試（2s/4s/8s/16s）
n=0
until git push; do
  n=$((n + 1))
  if [ "$n" -ge 4 ]; then echo "推送失敗，已重試 4 次"; exit 1; fi
  sleep $((2 ** n))
done
echo "===== 完成，網頁已更新 ====="
