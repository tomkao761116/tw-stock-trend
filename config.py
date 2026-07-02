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
    "night_futures": 2.5,  # 台指期夜盤：隔夜訊號最直接的反映（需 FinMind token）
    "sox": 2.5,        # 費半，連動最強（與夜盤部分重疊，故由 3.0 降至 2.5）
    "tsm_adr": 2.5,    # 台積電 ADR（同上，由 3.0 降至 2.5）
    "nasdaq": 2.0,     # 那斯達克
    "foreign_buy": 2.0,  # 外資前一日買賣超（需 FinMind token）
    "foreign_futures": 2.0,  # 外資期貨未平倉淨額（需 FinMind token）
    "usdtwd": 1.0,     # 台幣匯率
    "vix": 2.0,        # 恐慌指數（只會貢獻負分）
    "margin": 1.0,     # 融資餘額變化（反向：散戶情緒指標）
}

# ── 標準化參數：多少幅度算「滿分 ±1」───────────────────────────
NORMALIZERS = {
    "night_full_pct": 1.5,      # 台指期夜盤相對前一日盤收 1.5% = 滿分
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

# 重大事件日（見 events.py）門檻放大倍數：>1 = 更保守、更傾向「震盪」
THRESHOLD_EVENT_SCALE = 1.5

# 有效因子數低於此值 → 視為資料擷取大規模失敗（如網路未連上），中止並拒絕覆蓋既有資料
MIN_VALID_FACTORS = 3

# ── 因子白話資訊（給不熟股市的人看）────────────────────────────
# nick：口語名稱；why：一句話說明這是什麼、為何影響台股。
FACTOR_INFO = {
    "night_futures": {"nick": "台指期夜盤",
                      "why": "台股期貨在美股盤中即時交易到清晨，是隔夜消息對台股最直接的反映；夜盤漲，今天現貨容易開高",
                      "pos_note": "夜盤買盤積極，市場資金已提前反映樂觀氣氛，通常延續到今天開盤",
                      "neg_note": "夜盤賣壓明顯，市場資金已提前反映保守氣氛，開盤承壓機率較高",
                      "source_url": "https://finmindtrade.com/analysis/#/data/api"},
    "sox": {"nick": "美國半導體股",
            "why": "和台積電、聯發科連動最深；它漲，台股科技股今天容易跟著漲",
            "pos_note": "半導體類股資金動能強，激勵台股科技權值股表現",
            "neg_note": "半導體類股走弱，對台股科技權值股形成壓力",
            "source_url": "https://finance.yahoo.com/quote/%5ESOX"},
    "tsm_adr": {"nick": "台積電美國股價",
                "why": "台積電在美國也掛牌，昨晚的漲跌通常先反映到今天台積電開盤",
                "pos_note": "台積電美股表現強勢，開盤大機率跟漲",
                "neg_note": "台積電美股走弱，開盤承壓機率高",
                "source_url": "https://finance.yahoo.com/quote/TSM"},
    "nasdaq": {"nick": "美國那斯達克",
               "why": "美國科技股大盤，代表整體科技股的氣氛好壞",
               "pos_note": "美國科技股氣氛偏多，有助台股類股連動走升",
               "neg_note": "美國科技股氣氛轉弱，台股類股連動承壓",
               "source_url": "https://finance.yahoo.com/quote/%5EIXIC"},
    "foreign_buy": {"nick": "外資買賣超",
                    "why": "外國機構前一天買多還是賣多；買超代表資金流進台股",
                    "pos_note": "外資資金持續流入現貨市場，籌碼面偏多",
                    "neg_note": "外資賣超，籌碼面轉為保守",
                    "source_url": "https://finmindtrade.com/analysis/#/data/api"},
    "foreign_futures": {"nick": "外資期貨部位",
                        "why": "外資在台股期貨押多還是押空，反映他們對後市的看法",
                        "pos_note": "外資期貨轉為加碼做多，對後市偏樂觀",
                        "neg_note": "外資期貨轉為加碼放空，對後市偏保守",
                        "source_url": "https://finmindtrade.com/analysis/#/data/api"},
    "usdtwd": {"nick": "台幣匯率",
               "why": "台幣升值常代表外資把錢換成台幣、準備進場買股",
               "pos_note": "台幣升值，外資匯兌動能有利進場買股",
               "neg_note": "台幣貶值，外資匯兌動能較不利進場買股",
               "source_url": "https://finance.yahoo.com/quote/USDTWD=X"},
    "vix": {"nick": "美股恐慌指數",
            "why": "數字越高代表市場越緊張；過高對股市不利",
            "neg_note": "市場恐慌情緒升溫，避險氣氛升高，對風險性資產不利",
            "source_url": "https://finance.yahoo.com/quote/%5EVIX"},
    "margin": {"nick": "散戶融資",
               "why": "散戶借錢買股的金額；爆增常是追高過熱的警訊（所以反向看待）",
               "pos_note": "融資餘額縮減，顯示散戶追高動能降溫，籌碼相對健康",
               "neg_note": "融資餘額增加，散戶槓桿轉高，需留意過熱風險",
               "source_url": "https://finmindtrade.com/analysis/#/data/api"},
}

# ── FinMind API（台股籌碼資料，免費註冊取得 token）──────────────
# https://finmindtrade.com/  註冊後把 token 填這裡，或設環境變數 FINMIND_TOKEN
FINMIND_TOKEN = ""
