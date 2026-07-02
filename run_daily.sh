#!/bin/zsh
# 每日盤前自動執行：產生預估 → 更新網頁 → 推送 GitHub Pages
# 搭配 cron 使用（見 README）。token 由 .finmind_token 自動讀取，無需設環境變數。

set -e
PROJECT_DIR="/Users/aidenkaoiii/Google 雲端硬碟/個人AI/股市趨勢預估"
PYTHON="/opt/anaconda3/bin/python3"
NETWORK_WAIT_MAX=180   # 等待網路的上限秒數（電腦剛喚醒、Wi-Fi 重連用）
NETWORK_CHECK_INTERVAL=10

cd "$PROJECT_DIR" || { echo "找不到專案目錄"; exit 1; }

echo "===== $(date '+%Y-%m-%d %H:%M') 開始 ====="

# 冪等性：今天已成功產生過就跳過。launchd 設有多個觸發時段(08:20/08:45)當備援，
# 避免前一次已成功時，備援時段又重跑一次、重複耗用 API 額度與 commit。
TODAY_FILE="data/$(date +%F).json"
if [ -f "$TODAY_FILE" ]; then
  echo "今天已成功產生過預估（$TODAY_FILE 存在），略過本次執行"
  exit 0
fi

# 等網路就緒：電腦剛喚醒時 Wi-Fi 常需要幾秒到幾分鐘才重新連上，
# 若此時直接擷取資料會全部失敗；main.py 雖有守門不會存壞資料，但仍浪費一次機會。
waited=0
until curl -s -m 5 -o /dev/null https://api.github.com; do
  waited=$((waited + NETWORK_CHECK_INTERVAL))
  if [ "$waited" -ge "$NETWORK_WAIT_MAX" ]; then
    echo "等待網路 ${NETWORK_WAIT_MAX} 秒仍未連上，本次放棄（備援排程時段會再試一次）"
    exit 1
  fi
  echo "網路尚未就緒，${NETWORK_CHECK_INTERVAL}s 後重試...（已等待 ${waited}s）"
  sleep "$NETWORK_CHECK_INTERVAL"
done
echo "網路已就緒"

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
