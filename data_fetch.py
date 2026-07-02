"""資料擷取層：從 Yahoo Finance 取隔夜美股，從 FinMind 取台股籌碼。

每個函式回傳簡單 dict，取不到時回傳 None 並印出原因，讓上層優雅降級。
"""
import os
import datetime as dt

import config


def _last_two_closes(ticker):
    """取最近兩個交易日收盤價，回傳 (前值, 最新值, 漲跌幅%)。"""
    import yfinance as yf

    hist = yf.Ticker(ticker).history(period="5d")
    if hist.empty or len(hist) < 2:
        return None
    closes = hist["Close"].dropna()
    prev, last = float(closes.iloc[-2]), float(closes.iloc[-1])
    pct = (last / prev - 1) * 100
    return prev, last, pct


def fetch_market_quote(name):
    """通用：回傳 {name, last, pct} 或 None。"""
    ticker = config.TICKERS[name]
    try:
        res = _last_two_closes(ticker)
        if res is None:
            print(f"  ⚠ {name} ({ticker}) 無足夠資料")
            return None
        _, last, pct = res
        return {"name": name, "last": round(last, 2), "pct": round(pct, 2)}
    except Exception as e:
        print(f"  ⚠ {name} ({ticker}) 擷取失敗：{e}")
        return None


def fetch_us_overnight():
    """隔夜美股 + VIX + 匯率，全部來自 Yahoo Finance。"""
    return {k: fetch_market_quote(k) for k in
            ("sox", "nasdaq", "tsm_adr", "vix", "usdtwd")}


def fetch_sector_signals():
    """金融股/傳產類別用的額外訊號：美股金融類股、美債殖利率、原物料、航運。"""
    return {k: fetch_market_quote(k) for k in
            ("xlf", "tnx", "oil", "copper", "dxy", "bdry")}


# ── FinMind 台股籌碼 ─────────────────────────────────────────
def _finmind_token():
    """讀取順序：環境變數 > 本地 .finmind_token 檔 > config.py。
    本地檔與環境變數皆不進 git，適合 cron 自動執行。"""
    env = os.environ.get("FINMIND_TOKEN")
    if env:
        return env.strip()
    token_file = os.path.join(os.path.dirname(__file__), ".finmind_token")
    if os.path.exists(token_file):
        with open(token_file, encoding="utf-8") as fp:
            t = fp.read().strip()
            if t:
                return t
    return config.FINMIND_TOKEN


def _finmind_get(dataset, extra=None):
    import requests

    token = _finmind_token()
    if not token:
        return None
    end = dt.date.today()
    start = end - dt.timedelta(days=10)
    params = {
        "dataset": dataset,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "token": token,
    }
    if extra:
        params.update(extra)
    r = requests.get("https://api.finmindtrade.com/api/v4/data",
                     params=params, timeout=20)
    r.raise_for_status()
    return r.json().get("data", [])


def fetch_foreign_buy():
    """外資前一交易日對集中市場的買賣超（億元）。需 FinMind token。"""
    if not _finmind_token():
        print("  ⚠ 外資買賣超：未設定 FINMIND_TOKEN，略過")
        return None
    try:
        # 全市場三大法人買賣超（register 等級可用）
        data = _finmind_get("TaiwanStockTotalInstitutionalInvestors")
        if not data:
            return None
        last_date = max(row["date"] for row in data)
        rows = [r for r in data if r["date"] == last_date]
        # 外資 = Foreign_Investor + Foreign_Dealer_Self（外資自營），單位：元
        net = 0.0
        for r in rows:
            if r.get("name") in ("Foreign_Investor", "Foreign_Dealer_Self"):
                net += (r.get("buy", 0) - r.get("sell", 0))
        net_yi = net / 1e8  # 元 → 億元
        return {"date": last_date, "net_yi": round(net_yi, 1)}
    except Exception as e:
        print(f"  ⚠ 外資買賣超擷取失敗：{e}")
        return None


def fetch_foreign_futures():
    """外資台指期未平倉淨額（口數）變化。需 FinMind token。"""
    if not _finmind_token():
        print("  ⚠ 外資期貨：未設定 FINMIND_TOKEN，略過")
        return None
    try:
        # 期權三大法人（register 等級可用；TaiwanFuturesInstitutionalInvestors 需付費）
        data = _finmind_get("TaiwanFutOptInstitutionalInvestors",
                            extra={"data_id": "TX"})
        if not data:
            return None
        # 此 dataset 投資人名稱為中文
        foreign = [r for r in data if r.get("institutional_investors") == "外資"]
        if len(foreign) < 2:
            return None
        foreign.sort(key=lambda r: r["date"])

        def net_oi(r):  # 淨未平倉口數 = 多方餘額 - 空方餘額
            return (r.get("long_open_interest_balance_volume", 0)
                    - r.get("short_open_interest_balance_volume", 0))

        latest, prev = net_oi(foreign[-1]), net_oi(foreign[-2])
        return {"date": foreign[-1]["date"],
                "net": latest, "change": latest - prev}
    except Exception as e:
        print(f"  ⚠ 外資期貨擷取失敗：{e}")
        return None


def fetch_night_futures():
    """台指期夜盤收盤相對前一交易日盤收的漲跌幅(%)。需 FinMind token。

    夜盤(after_market)跑到清晨 05:00，盤前即可取得；用同一近月合約比較，
    避開換月跳價。是隔夜訊息對台股開盤最直接的反映。
    """
    if not _finmind_token():
        print("  ⚠ 台指期夜盤：未設定 FINMIND_TOKEN，略過")
        return None
    try:
        data = _finmind_get("TaiwanFuturesDaily", extra={"data_id": "TX"})
        if not data:
            return None
        # 只留近月單一合約（contract_date 無 '/'）、收盤 > 0
        outs = [r for r in data
                if "/" not in str(r.get("contract_date", "")) and r.get("close", 0) > 0]
        nights = [r for r in outs if r.get("trading_session") == "after_market"]
        days = [r for r in outs if r.get("trading_session") == "position"]
        if not nights or not days:
            return None
        # 最新夜盤（取最近月）
        latest_date = max(r["date"] for r in nights)
        night = min((r for r in nights if r["date"] == latest_date),
                    key=lambda r: r["contract_date"])
        contract = night["contract_date"]
        # 同合約、前一交易日的日盤收盤
        prev = [r for r in days
                if r["contract_date"] == contract and r["date"] < latest_date]
        if not prev:
            return None
        ref = max(prev, key=lambda r: r["date"])
        change_pct = (night["close"] / ref["close"] - 1) * 100
        return {"date": latest_date, "ref_date": ref["date"],
                "night_close": night["close"], "change_pct": round(change_pct, 2)}
    except Exception as e:
        print(f"  ⚠ 台指期夜盤擷取失敗：{e}")
        return None


def fetch_margin():
    """整體市場融資餘額單日變化（%）。需 FinMind token。
    融資餘額代表散戶槓桿；作為反向情緒指標（增 → 過熱）。"""
    if not _finmind_token():
        print("  ⚠ 融資融券：未設定 FINMIND_TOKEN，略過")
        return None
    try:
        data = _finmind_get("TaiwanStockTotalMarginPurchaseShortSale")
        if not data:
            return None
        last_date = max(r["date"] for r in data)
        # MarginPurchaseMoney = 融資餘額（元）
        row = next((r for r in data if r["date"] == last_date
                    and r.get("name") == "MarginPurchaseMoney"), None)
        if not row or not row.get("YesBalance"):
            return None
        today, yes = row["TodayBalance"], row["YesBalance"]
        change_pct = (today / yes - 1) * 100
        return {"date": last_date, "balance_yi": round(today / 1e8, 0),
                "change_pct": round(change_pct, 2)}
    except Exception as e:
        print(f"  ⚠ 融資融券擷取失敗：{e}")
        return None


def fetch_all():
    """一次取齊所有因子原始資料（大盤 + 科技股/金融股/傳產類別）。"""
    print("擷取隔夜美股 / 匯率 / VIX ...")
    us = fetch_us_overnight()
    print("擷取類別訊號（金融股/傳產）...")
    sector = fetch_sector_signals()
    print("擷取台股籌碼（FinMind）...")
    return {
        **us,
        **sector,
        "night_futures": fetch_night_futures(),
        "foreign_buy": fetch_foreign_buy(),
        "foreign_futures": fetch_foreign_futures(),
        "margin": fetch_margin(),
    }
