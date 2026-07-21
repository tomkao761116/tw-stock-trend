# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案是什麼

台股盤前趨勢預估：每日盤前以「隔夜美股＋台股籌碼」規則引擎產生方向預估（開盤方向＋盤中展望），
輸出靜態網站到 GitHub Pages（https://tomkao761116.github.io/tw-stock-trend/）。
純 Python、無框架、無資料庫。

## 常用指令

```bash
PY=/opt/anaconda3/bin/python3        # launchd 排程用的直譯器，開發時保持一致

$PY main.py          # 每日完整流程：抓資料 → 評分 → 報告 → 存 data/ → 產網頁
$PY backtest.py      # 回填實際漲跌與命中判定（--force 全部重查）
$PY webgen.py        # 只重新產生 docs/ 網頁（不重抓資料）
$PY backfill.py --start 2024-01-01   # 歷史回填：重建過去每日 8am 視角 → backfill/backfill.json
$PY analyze.py       # 讀回填檔，輸出因子 IC / 共線性 / 門檻掃描 / train-val 驗證
$PY calibrate.py     # 輕量版：只用 data/ 累積的實盤資料算因子相關性
```

沒有測試套件、沒有 linter；驗證方式 = 跑上述腳本看輸出。每日自動執行由 `run_daily.sh` +
launchd（`launchd/com.twstock.daily.plist`，平日 08:20/08:30 雙觸發）驅動，流程末自動
commit + push（觸發 Pages 部署）。**注意**：手動跑 `main.py`/`run_daily.sh` 在非交易日
會產生永遠沒有實際結果的孤兒資料檔——launchd 只排平日，但週六/國定假日手動執行前先想一下。

兩份檔案寫死專案絕對路徑：`run_daily.sh` 的 `PROJECT_DIR` 與 launchd plist 的
`ProgramArguments`。搬移專案時要同步改，並 `cp` 到 `~/Library/LaunchAgents/` 後
`launchctl unload && load` 重新載入。

FinMind token 放 `.finmind_token`（不進 git）或環境變數 `FINMIND_TOKEN`；缺 token 時
籌碼類因子優雅降級為 N/A，不會中斷。

## 資料流架構

```
data_fetch.py → rules.py → report.py → data/*.json → webgen.py → docs/
 (取數，失敗回None) (純函數評分)  (三種輸出+存檔)  (唯一真相來源)   (靜態站)
                                        ↑
                backtest.py 隔日回填 actual/hit（收盤 13:30 後才採計）
```

- **config.py 是唯一調參面**：權重、標準化常數、門檻、類別定義全在這裡，改參數不動邏輯。
- **rules.py 是純函數層**：`_evaluate_core` 為大盤與五個類別（tech/financial/traditional/
  dividend/bond）共用；回傳 dict 結構固定，未來換 ML 只需替換此層。大盤與各類別都有
  兩段式預測 `open_call`/`intraday_call`（見下），由 `_two_part_call` 帶各自門檻算出：
  大盤用 `config.THRESHOLD_BULLISH`/`THRESHOLD_INTRADAY`，類別用各自的
  `threshold_bullish`/`threshold_intraday`。
- **data/*.json 被 backtest/calibrate/webgen glob 掃描**——不要放其他 JSON 進 data/；
  回填產物固定放 `backfill/`。webgen 不會刪孤兒頁面，刪 data 檔後要順手刪對應的 docs/*.html。
- **webgen 向後相容**：舊資料無 `open_call` 欄位時自動回退單一方向渲染，改卡片結構時必須保留這條路徑。

## 校準紀律（重要）

所有權重/門檻調整必須有證據：跑 `backfill.py` + `analyze.py`，以 70/30 train/validation
驗證後才改 config.py，並在 `decisions.md` 記一行（日期｜決策｜理由｜替代方案）。
2026-07-03 已用 603 天回填完成一輪校準，已驗證並**否決**的假設（不要重提，除非有新證據）：
滾動 z-score 標準化、美股因子對夜盤殘差化、前日動能因子。

模型本質是**隔夜訊號 → 開盤預測器**：開盤方向略強於收盤/盤中，但**別再引用「94%」**——
那是 sign-only（忽略平盤帶）灌水數字。**可交易命中**（喊方向日、需超過平盤帶、與實盤計分
一致）大盤開盤約 70%、收盤約 66%、盤中約 50-60%。度量務必用 `analyze._band()`（開盤 0.2、
其餘 0.4）——2026-07-21 前 analyze/文件混用 sign-only 與含平盤帶兩套算法，曾誤把開盤報成
94%。這是兩段式呈現的由來，盤中門檻一律高於開盤門檻，訊號弱時顯示「方向不明」而非硬喊。
校準用 backfill 的 `categories[k].target`（含 gap/intraday 拆解），調門檻時重跑分析勿憑感覺。

## 已知陷阱

- **資料源是雙源互補架構，方向相反，不要「統一」**：(a) 回測抓台股收盤 = FinMind 主、
  Yahoo 備（`backtest._fetch_bars`）——Yahoo 對台股日線延遲約一天；(b) 預測因子抓美股 =
  Yahoo 主（含重試）、FinMind `USStockPrice` 備（`data_fetch._finmind_fallback_last_two`，
  同樣的 Yahoo 式代號）——2026-07-10 ^SOX 瞬時失敗曾致當日缺重要因子。無備援的殘餘：
  ^TNX/CL=F/HG=F/DX-Y.NYB/^MOVE（FinMind 無期貨/殖利率）與 usdtwd（台銀牌價時間基準
  不同，刻意不備援）。已收盤仍抓不到時 backtest 會印 ⚠️ 警告；缺權重≥2 因子時網頁卡片警告。
- **FinMind 夜盤日期語意**：`TaiwanFuturesDaily` 的 `after_market` 日期 = 夜盤「結束」的
  交易日（D-1 15:00 開始的夜盤標記為 D）。backfill 的 as-of 過濾對夜盤用 `<= D`、
  其他資料源用 `< D`——改動時別「統一」它們，那是修過的 bug。
- **report.save_data 的沿用邏輯**：重跑 main.py 時只在「方向與上次一致」才保留已回測的
  actual/hit；改了 config 導致方向變化時舊命中判定會被清掉重算，是刻意設計。
- **backtest 平盤帶不同**：收收判定 `FLAT_BAND=0.4%`、開盤跳空 `GAP_FLAT_BAND=0.2%`
  （跳空幅度天生較小）。
- **今日盤中不採計**：`_eligible` 擋掉 13:30 收盤前的當日資料，避免把盤中暫定價當實際結果。

## 部署（歷史教訓，勿回退）

- Pages 用 **GitHub Actions workflow 模式**（`.github/workflows/pages.yml`，
  `build_type=workflow`）。**不要改回 branch/legacy Jekyll build**——2026-07-03 舊 repo
  因 legacy 管線後端卡死整個砍掉重建過。
- deploy-pages 回「Deployment failed, try again later」且同一 commit 重跑仍失敗時：
  Pages deployment ID = commit SHA，失敗殘留會擋同 SHA 重部署，**推一個空 commit 換 SHA 即解**。

## 風格慣例

- 本 repo 的註解與 docstring 一律**繁體中文**（既有慣例，優先於個人偏好的英文註解規則）。
  註解重點寫「為什麼」與資料語意（尤其時序/as-of 相關），不寫「做了什麼」。
- 本 repo 有每日自動 commit+push 流程，手動改完程式碼也應 commit+push（會順帶觸發部署）。
- **commit 訊息只描述 repo 內容的變更**，不寫本機環境細節（目錄搬移、launchd 重載、
  個人資料夾結構等）——這是公開 repo，那些資訊屬於個人操作紀錄，不屬於版本歷史。
