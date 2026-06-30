"""集中管理：股票代號、因子權重、分類門檻。調參只改這裡，不動邏輯。"""

# ── 資料來源代號（Yahoo Finance）──────────────────────────────
TICKERS = {
    "sox": "^SOX",        # 費城半導體指數
    "nasdaq": "^IXIC",    # 那斯達克綜合指數
    "tsm_adr": "TSM",     # 台積電 ADR
    "vix": "^VIX",        # 恐慌指數
    "usdtwd": "USDTWD=X", # 美元兌台幣
}

# ── 因子權重（數字越大影響越大；可自由調整）────────────────────
# 每個因子先算出 [-1, +1] 的標準化方向分數，再乘以此權重。
WEIGHTS = {
    "sox": 3.0,        # 費半，連動最強
    "tsm_adr": 3.0,    # 台積電 ADR
    "nasdaq": 2.0,     # 那斯達克
    "foreign_buy": 2.0,  # 外資前一日買賣超（需 FinMind token）
    "foreign_futures": 2.0,  # 外資期貨未平倉淨額（需 FinMind token）
    "usdtwd": 1.0,     # 台幣匯率
    "vix": 2.0,        # 恐慌指數（只會貢獻負分）
    "margin": 1.0,     # 融資餘額變化（反向：散戶情緒指標）
}

# ── 標準化參數：多少幅度算「滿分 ±1」───────────────────────────
NORMALIZERS = {
    "sox_full_pct": 2.0,        # SOX 漲跌 2% = 滿分
    "tsm_adr_full_pct": 2.0,    # ADR 漲跌 2% = 滿分
    "nasdaq_full_pct": 1.5,     # 那斯達克 1.5% = 滿分
    "foreign_buy_full_yi": 150.0,    # 外資買賣超 150 億 = 滿分
    "foreign_futures_full": 8000.0,  # 外資期貨淨額變化 8000 口 = 滿分
    "usdtwd_full_pct": 0.5,     # 台幣升/貶 0.5% = 滿分
    "vix_base": 20.0,           # VIX 高於此值開始扣分
    "vix_range": 15.0,          # VIX 超出 base 多少 = 滿分扣分
    "margin_full_pct": 1.5,     # 融資餘額單日變化 1.5% = 滿分（反向）
}

# ── 分類門檻 ──────────────────────────────────────────────────
THRESHOLD_BULLISH = 4.0   # 總分 ≥ 此值 → 偏多
THRESHOLD_BEARISH = -4.0  # 總分 ≤ 此值 → 偏空
# 介於兩者之間 → 震盪

# ── FinMind API（台股籌碼資料，免費註冊取得 token）──────────────
# https://finmindtrade.com/  註冊後把 token 填這裡，或設環境變數 FINMIND_TOKEN
FINMIND_TOKEN = ""
