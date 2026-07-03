#!/bin/zsh
# 每日盤前自動執行：等網路 → 產生預估 → 回測回填 → 更新網頁 → 推送 GitHub Pages
# 搭配 launchd 使用（見 README）。token 由 .finmind_token 自動讀取，無需設環境變數。

set -e
PROJECT_DIR="/Users/aidenkaoiii/Projects/tw-stock-trend"
PYTHON="/opt/anaconda3/bin/python3"
NETWORK_WAIT_MAX=180   # 等待網路的上限秒數（電腦剛喚醒、Wi-Fi 重連用）
NETWORK_CHECK_INTERVAL=10

cd "$PROJECT_DIR" || { echo "找不到專案目錄"; exit 1; }

echo "===== $(date '+%Y-%m-%d %H:%M') 開始 ====="

# 等網路就緒：電腦剛喚醒時 Wi-Fi 常需要幾秒到幾分鐘才重新連上，
# main.py 與 backtest.py 都需要網路，先在這裡統一等待。
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

# 冪等性：今天已成功產生過就跳過重新擷取。launchd 設有備援觸發時段(08:20/08:30)，
# 避免前一次已成功時，備援時段又重跑一次、重複耗用 FinMind API 額度。
TODAY_FILE="data/$(date +%F).json"
if [ -f "$TODAY_FILE" ]; then
  echo "今天已成功產生過預估（$TODAY_FILE 存在），略過重新擷取"
else
  "$PYTHON" main.py
fi

# 回測自動化：補回先前幾天欠缺的實際結果。已有結果的日期會自動跳過（不重複打 API），
# 只有 actual 仍缺的日期（通常是最近 1-2 天，收盤資料延遲到位）才會查詢。
"$PYTHON" backtest.py || echo "回測失敗（可能網路不穩），略過本次回測"

# 回測可能更新了歷史資料，重新產生網頁確保「實際」欄位同步
"$PYTHON" -c "import webgen; webgen.build_site()" || echo "網頁重建失敗"

# 只在有變更時提交
git add data docs
if git diff --cached --quiet; then
  echo "無變更，跳過推送"
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
