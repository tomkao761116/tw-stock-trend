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


# ── FinMind 台股籌碼 ─────────────────────────────────────────
def _finmind_token():
    return os.environ.get("FINMIND_TOKEN") or config.FINMIND_TOKEN


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
        data = _finmind_get("TaiwanStockInstitutionalInvestorsBuySell")
        if not data:
            return None
        last_date = max(row["date"] for row in data)
        rows = [r for r in data if r["date"] == last_date]
        # 外資 = Foreign_Investor（不含自營、投信）
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
        data = _finmind_get("TaiwanFuturesInstitutionalInvestors",
                            extra={"data_id": "TX"})
        if not data:
            return None
        foreign = [r for r in data if r.get("institutional_investors")
                   == "Foreign_Investor"]
        if len(foreign) < 2:
            return None
        foreign.sort(key=lambda r: r["date"])
        key = "long_open_interest_balance_volume"
        latest = foreign[-1].get(key, 0) - foreign[-1].get(
            "short_open_interest_balance_volume", 0)
        prev = foreign[-2].get(key, 0) - foreign[-2].get(
            "short_open_interest_balance_volume", 0)
        return {"date": foreign[-1]["date"],
                "net": latest, "change": latest - prev}
    except Exception as e:
        print(f"  ⚠ 外資期貨擷取失敗：{e}")
        return None


def fetch_all():
    """一次取齊所有因子原始資料。"""
    print("擷取隔夜美股 / 匯率 / VIX ...")
    us = fetch_us_overnight()
    print("擷取台股籌碼（FinMind）...")
    return {
        **us,
        "foreign_buy": fetch_foreign_buy(),
        "foreign_futures": fetch_foreign_futures(),
    }
