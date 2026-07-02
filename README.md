# 台股盤前趨勢預估

每日盤前跑一次，依「隔夜美股 + 台股籌碼」規則引擎，預估當日台股方向（**偏多 / 偏空 / 震盪**）。

> ⚠️ 本工具為決策輔助，輸出為機率性方向預估，**非投資建議**。市場有大量隨機性與突發事件。

## 快速開始

```bash
pip install -r requirements.txt
python main.py
```

不需任何設定即可跑（使用免費的 Yahoo Finance 美股資料）。
要納入台股籌碼因子（外資買賣超、外資期貨），到 [FinMind](https://finmindtrade.com/) 免費註冊取得 token，擇一設定（皆不進 git）：

```bash
# 方法 A：環境變數
export FINMIND_TOKEN="你的token"

# 方法 B：放在專案目錄的 .finmind_token 檔（cron 自動執行較方便）
echo "你的token" > .finmind_token
```

> FinMind 免費（register）等級可用的籌碼 dataset：
> `TaiwanStockTotalInstitutionalInvestors`（三大法人買賣超）、
> `TaiwanFutOptInstitutionalInvestors`（期權法人未平倉）。
> 純期貨 `TaiwanFuturesInstitutionalInvestors` 需付費等級，本工具未使用。

## 因子與權重

| 因子 | 來源 | 權重 | 說明 |
|------|------|------|------|
| 台指期夜盤 | FinMind | 2.5 | 隔夜訊息對台股最直接的反映，需 token |
| 費半 SOX | Yahoo Finance | 2.5 | 與台股半導體連動最強 |
| 台積電 ADR | Yahoo Finance | 2.5 | 直接影響台積電開盤 |
| 那斯達克 | Yahoo Finance | 2.0 | 科技股氣氛 |
| 外資買賣超 | FinMind | 2.0 | 前一交易日，需 token |
| 外資期貨 | FinMind | 2.0 | 未平倉淨額變化，需 token |
| 台幣匯率 | Yahoo Finance | 1.0 | 升值 = 外資進場訊號 |
| VIX 恐慌 | Yahoo Finance | 2.0 | 只貢獻負分 |
| 融資餘額 | FinMind | 1.0 | 反向：散戶槓桿過熱訊號，需 token |

## 細分類別（大盤以外）

除了大盤，同一套引擎會額外算出三個子類別的獨立方向預估，各自有專屬因子組、權重與門檻：

| 類別 | 因子 | 回測對照標的 |
|------|------|------|
| **科技股/半導體** | 台指期夜盤、SOX、台積電ADR、那斯達克（沿用大盤因子，零額外成本） | 0052.TW（富邦科技） |
| **金融股** | 美股金融類股(XLF)、美債10年殖利率、台幣匯率、外資買賣超 | 0055.TW（元大MSCI金融） |
| **傳產/原物料/航運** | WTI原油、銅期貨、美元指數、航運ETF(BDRY) | 無乾淨單一標的，暫不自動回測 |

> ⚠️ **已知限制**：金融股、傳產類別沒有台股本地籌碼資料可用（FinMind 產業別法人買賣超需付費等級），
> 只能靠美股對應類股與大宗商品做隔夜訊號，準確度天生比大盤/科技股（有夜盤直接反映）弱，門檻也設得較保守。

每因子先標準化為 [-1, +1]，乘權重後加總：

```
總分 ≥ +4 → 偏多 ｜ 總分 ≤ -4 → 偏空 ｜ 其餘 → 震盪
```

**調參只改 `config.py`**（權重、門檻、標準化幅度），不動邏輯。

## 輸出說明

報告分三段，新手只看前兩段即可：

1. **今天的預估**：方向 + 信心程度（●○ 五格）+ 一段白話解釋
2. **影響今天的因素**：每個因子用口語名稱、利多/利空、★ 強度、一句話說明
3. **數據明細（進階）**：多空力道、總分、原始因子表（給想深入的人）

## 事件層（財經行事曆）

重大事件日（Fed、CPI、非農、台積電法說、結算日）市場常觀望，美股強弱未必反映到當日。
事件日**不改因子分數**，而是把分類門檻放大（`config.THRESHOLD_EVENT_SCALE`，預設 1.5×），
要求更強訊號才敢喊方向，並在報告示警。

- **結算日**（每月第三個週三）：自動偵測，免維護。
- **Fed / CPI / 非農 / 法說**：在 `events.py` 的 `MANUAL_EVENTS` 自行填日期（date = 影響的台股交易日）。

## 專案結構

```
config.py      權重、門檻、代號設定
data_fetch.py  資料擷取（Yahoo Finance + FinMind）
rules.py       規則引擎：因子 → 分數 → 分類
events.py      財經行事曆事件層（事件日放大門檻）
report.py      終端機輸出 + Markdown 報告 + JSON 存檔
webgen.py      靜態網頁產生器（docs/index.html）
main.py        執行入口
run_daily.sh   每日自動化：跑預估 → 更新網頁 → 推送
backtest.py    回測：抓實際漲跌、算命中率
calibrate.py   權重校準建議
launchd/       launchd 排程設定（每交易日 08:20，喚醒補跑）
data/          每日結果 JSON（歷史與回測資料來源）
docs/          產出的網頁（GitHub Pages 由此出站）
reports/        每日報告（含實際結果欄位，供回測命中率）
```

## 每日自動執行（macOS）

`run_daily.sh` 會跑預估 → 更新網頁 → 推送 GitHub Pages。用 macOS **`launchd`** 在每個交易日早上 8:20 執行（相較 cron，**電腦喚醒後會補跑錯過的排程**，適合不一定準時開機的桌機/筆電）：

```bash
# 安裝（plist 已含在 repo 的 launchd/）
cp launchd/com.twstock.daily.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.twstock.daily.plist

# 確認已註冊
launchctl list | grep twstock

# 手動觸發一次測試
launchctl start com.twstock.daily

# 解除安裝
launchctl unload -w ~/Library/LaunchAgents/com.twstock.daily.plist
```

排程設定在 `launchd/com.twstock.daily.plist`（週一～五 08:20）；log 輸出到 `/tmp/tw-stock.log`。
改時間就編輯 plist 的 `StartCalendarInterval` 後重新 `unload` → `load`。

> macOS 注意：實測 cron 可正常存取 Google Drive 目錄並執行。若日後遇到權限問題，到「系統設定 → 隱私權與安全性 → 完整磁碟取用權限」把 `cron`（/usr/sbin/cron）加入授權。

### cron 推送認證設定（必要，只需一次）

cron 沒有終端機，拿不到 keychain 裡的 git 認證，`git push` 會失敗
（`could not read Username for 'https://github.com'`）。解法是建立一個認證儲存檔，
用 GitHub token 讓 cron 免 keychain 即可推送：

```bash
# 1. 用 gh token 建立認證檔（放家目錄、權限 600、不在 repo 內、不會被提交）
CREDFILE="$HOME/.tw-stock-git-credentials"
printf 'https://x-access-token:%s@github.com\n' "$(gh auth token)" > "$CREDFILE"
chmod 600 "$CREDFILE"

# 2. 設定本 repo 用此檔當認證來源
cd "/Users/aidenkaoiii/Google 雲端硬碟/個人AI/股市趨勢預估"
git config credential.helper "store --file=$CREDFILE"

# 3. 驗證（模擬 cron 的最小環境）
env -i HOME="$HOME" PATH=/usr/bin:/bin /usr/bin/git -C "$(pwd)" push
```

> 檔案存的是 GitHub token（明文，600 權限）。gh token 通常長期有效；
> 若某天 push 突然失敗（token 失效），重跑步驟 1 重新產生即可。

## 回測（驗證準確率）

**已自動化**：`run_daily.sh` 每次執行都會跑一次回測，自動回填先前幾天欠缺的
「實際」結果——當天資料通常要等收盤後才會到位，所以是隔一兩天自動補上，不用手動想起來跑。

```bash
python backtest.py          # 只查詢尚缺 actual 的日期（預設，已有結果沿用、不重打 API）
python backtest.py --force  # 強制重新查詢所有日期（手動核對用）
```

抓加權指數(^TWII)當日實際漲跌，填回 `data/*.json` 的 `actual` 欄位，計算命中率：
偏多→當日漲、偏空→當日跌、震盪→當日平（±0.4% 平盤帶，可在 `backtest.py` 調整）。
手動執行完重建網頁，歷史表的「實際」欄就會顯示結果與 ✓/✗（自動流程已內含此步驟）。
累積數據後，依命中率回頭調整 `config.py` 的權重與門檻。

## 權重校準（累積資料後）

```bash
python calibrate.py
```

分析各因子標準化分數與當日實際漲跌的**相關性 r**，建議權重調整方向
（r 高→可提高、r 近 0→訊號弱可降低、r 負→反向需檢視）。
- 需 **≥ 10 天**回測資料才給建議，否則僅顯示參考相關性。
- 刻意用透明的相關性分析而非多元迴歸（樣本少時迴歸易過度擬合）。
- 只給建議，**不自動改 config**；調權重後重跑 `backtest.py` 觀察命中率變化。

## 線上網址

GitHub Pages：https://tomkao761116.github.io/tw-stock-trend/

## Roadmap

- [x] 規則引擎 v1（隔夜美股 + 籌碼）
- [x] 事件層（財經行事曆，事件日趨保守）
- [x] 靜態網頁（今日 + 歷史，手機可看、連結可分享）
- [x] 部署到 GitHub Pages（公開網址）
- [x] 自動化腳本（run_daily.sh + launchd，喚醒補跑 + 等網路 + 冪等性）
- [x] 回測腳本（抓 ^TWII 實際漲跌、算命中率，已整合進每日自動流程）
- [x] 台指期夜盤因子
- [x] 權重校準腳本（calibrate.py，依相關性建議調整）
- [x] 因子加動態解讀文字與外部資料連結
- [x] 細分類別預估（科技股/金融股/傳產，各自獨立方向+回測）
- [ ] ETF 類別（分類方式待評估）
- [ ] 累積 ≥ 10 天資料後校準權重
- [ ] 新聞情緒因子（NLP，第二層）

## 網頁

`python main.py` 會自動產生 `docs/index.html`（也可單獨 `python webgen.py` 重建）。
本機直接用瀏覽器打開即可預覽；要做成公開連結（手機看、貼進 LINE 群組分享），
部署到 GitHub Pages：repo 設定 → Pages → Source 選 `main` 分支的 `/docs` 資料夾。
台股慣例配色：紅=漲（偏多）、綠=跌（偏空）。
- [ ] 換 ML 模型（LightGBM）—只需替換 `rules.py`，回傳結構不變
