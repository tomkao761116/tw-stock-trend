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
| 費半 SOX | Yahoo Finance | 3.0 | 與台股半導體連動最強 |
| 台積電 ADR | Yahoo Finance | 3.0 | 直接影響台積電開盤 |
| 那斯達克 | Yahoo Finance | 2.0 | 科技股氣氛 |
| 外資買賣超 | FinMind | 2.0 | 前一交易日，需 token |
| 外資期貨 | FinMind | 2.0 | 未平倉淨額變化，需 token |
| 台幣匯率 | Yahoo Finance | 1.0 | 升值 = 外資進場訊號 |
| VIX 恐慌 | Yahoo Finance | 2.0 | 只貢獻負分 |
| 融資餘額 | FinMind | 1.0 | 反向：散戶槓桿過熱訊號，需 token |

每因子先標準化為 [-1, +1]，乘權重後加總：

```
總分 ≥ +4 → 偏多 ｜ 總分 ≤ -4 → 偏空 ｜ 其餘 → 震盪
```

**調參只改 `config.py`**（權重、門檻、標準化幅度），不動邏輯。

## 專案結構

```
config.py      權重、門檻、代號設定
data_fetch.py  資料擷取（Yahoo Finance + FinMind）
rules.py       規則引擎：因子 → 分數 → 分類
report.py      終端機輸出 + Markdown 報告存檔
main.py        執行入口
reports/        每日報告（含實際結果欄位，供回測命中率）
```

## 每日自動執行（macOS）

用 `cron` 設定每天早上 8 點執行（台股 9 點開盤前）：

```bash
crontab -e
# 加入一行（請改成你的實際路徑與 python）：
0 8 * * 1-5 cd "/path/to/股市趨勢預估" && /opt/anaconda3/bin/python3 main.py
```

## Roadmap

- [x] 規則引擎 v1（隔夜美股 + 籌碼）
- [ ] 回測：累積報告後計算歷史命中率，回頭調權重
- [ ] 新聞情緒因子（NLP）
- [ ] 換 ML 模型（LightGBM）—只需替換 `rules.py`，回傳結構不變
