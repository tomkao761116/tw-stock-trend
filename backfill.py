"""歷史回填：重建過去每個交易日「當天早上 8 點」能看到的因子資料，
跑同一套 rules.evaluate，對照當日實際結果，一次產生數百天的回測樣本。

用法：python backfill.py --start 2024-01-01
輸出：backfill/backfill.json（獨立目錄，不與 data/ 的每日檔混用）

as-of 原則（防 look-ahead bias）：預測日 D 只能使用 date < D 的資料——
美股收盤、FinMind 籌碼（T 日晚間公布）、台指期夜盤（D-1 夜盤清晨 5 點收）
在 D 日 8am 全部已知，與 live pipeline 的時序一致。
"""
import os
import json
import math
import argparse
import datetime as dt

import requests

import config
import events
import rules
from data_fetch import _finmind_token

OUT_DIR = os.path.join(os.path.dirname(__file__), "backfill")
YAHOO_BUFFER_DAYS = 130   # 起始日前多抓的緩衝（供前收比較與後續 rolling 分析）
FINMIND_CHUNK_DAYS = 180  # FinMind 分段抓取的天數（避免單次回應過大）


# ── 資料抓取（整段期間一次抓齊，之後純本地查表）─────────────────

def _yahoo_history(ticker, start, end):
    """回傳 {date_iso: {"open": float, "close": float}}，日期為交易所當地日。"""
    import yfinance as yf

    hist = yf.Ticker(ticker).history(start=start.isoformat(),
                                     end=(end + dt.timedelta(days=1)).isoformat())
    out = {}
    for ts, row in hist.iterrows():
        c = float(row["Close"])
        if math.isnan(c):
            continue
        o = float(row["Open"])
        out[ts.date().isoformat()] = {"open": (None if math.isnan(o) else o),
                                      "close": c}
    return out


def _finmind_range(dataset, start, end, extra):
    """分段抓整段期間的 FinMind dataset，回傳合併後的 row list。"""
    token = _finmind_token()
    rows = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + dt.timedelta(days=FINMIND_CHUNK_DAYS), end)
        params = {"dataset": dataset, "start_date": cur.isoformat(),
                  "end_date": chunk_end.isoformat(), "token": token}
        params.update(extra)
        r = requests.get("https://api.finmindtrade.com/api/v4/data",
                         params=params, timeout=60)
        r.raise_for_status()
        rows.extend(r.json().get("data", []))
        cur = chunk_end + dt.timedelta(days=1)
    return rows


def fetch_all_sources(start, end):
    """一次抓齊回填所需的全部原始資料。"""
    buf_start = start - dt.timedelta(days=YAHOO_BUFFER_DAYS)
    src = {"yahoo": {}, "finmind": {}}

    print("抓取 Yahoo 歷史日線 ...")
    for name, ticker in config.TICKERS.items():
        src["yahoo"][name] = _yahoo_history(ticker, buf_start, end)
        print(f"  {name:<10} {len(src['yahoo'][name]):>5} 天")

    print("抓取回測基準 ...")
    src["targets"] = {"twii": _yahoo_history("^TWII", buf_start, end)}
    for key, cat in config.CATEGORIES.items():
        t = cat.get("backtest_ticker")
        if t is None:
            continue
        tickers = t if isinstance(t, (list, tuple)) else [t]
        src["targets"][key] = [
            _yahoo_history(tk, buf_start, end) for tk in tickers]
        print(f"  {key:<12} {'+'.join(tickers)}")

    print("抓取 FinMind 歷史籌碼（分段）...")
    fm_start = start - dt.timedelta(days=15)
    src["finmind"]["inst"] = _finmind_range(
        "TaiwanStockTotalInstitutionalInvestors", fm_start, end, {})
    src["finmind"]["futopt"] = _finmind_range(
        "TaiwanFutOptInstitutionalInvestors", fm_start, end, {"data_id": "TX"})
    src["finmind"]["futures"] = _finmind_range(
        "TaiwanFuturesDaily", fm_start, end, {"data_id": "TX"})
    src["finmind"]["margin"] = _finmind_range(
        "TaiwanStockTotalMarginPurchaseShortSale", fm_start, end, {})
    for k, v in src["finmind"].items():
        print(f"  {k:<10} {len(v):>6} rows")
    return src


# ── as-of 查詢：模擬「D 日早上 8 點」看得到什麼 ──────────────────

def _last_two_closes_before(series, date_iso):
    """series: {date: {open, close}}；回傳 date_iso 之前最後兩個收盤 (prev, last)。"""
    dates = sorted(d for d in series if d < date_iso)
    if len(dates) < 2:
        return None
    prev, last = series[dates[-2]]["close"], series[dates[-1]]["close"]
    return prev, last


def _quote_asof(series, date_iso):
    two = _last_two_closes_before(series, date_iso)
    if two is None:
        return None
    prev, last = two
    return {"last": round(last, 2), "pct": round((last / prev - 1) * 100, 2)}


def _night_asof(fut_rows, date_iso):
    """複刻 data_fetch.fetch_night_futures 的邏輯，限定 date <= date_iso。

    FinMind 的 after_market 日期語意 = 夜盤「結束」的那個交易日（D-1 15:00
    開始的夜盤標記為 D，清晨 5 點收盤後即發布），所以 D 日 8am 看得到
    date == D 的夜盤 row——用 < 會整整晚一天（2026-07-03 與 live 逐日核對確認）。"""
    outs = [r for r in fut_rows
            if r["date"] <= date_iso
            and "/" not in str(r.get("contract_date", ""))
            and r.get("close", 0) > 0]
    nights = [r for r in outs if r.get("trading_session") == "after_market"]
    days = [r for r in outs if r.get("trading_session") == "position"]
    if not nights or not days:
        return None
    latest_date = max(r["date"] for r in nights)
    night = min((r for r in nights if r["date"] == latest_date),
                key=lambda r: r["contract_date"])
    contract = night["contract_date"]
    prev = [r for r in days
            if r["contract_date"] == contract and r["date"] < latest_date]
    if not prev:
        return None
    ref = max(prev, key=lambda r: r["date"])
    change_pct = (night["close"] / ref["close"] - 1) * 100
    return {"night_close": night["close"], "change_pct": round(change_pct, 2)}


def _foreign_buy_asof(inst_rows, date_iso):
    rows = [r for r in inst_rows if r["date"] < date_iso]
    if not rows:
        return None
    last_date = max(r["date"] for r in rows)
    net = sum((r.get("buy", 0) - r.get("sell", 0)) for r in rows
              if r["date"] == last_date
              and r.get("name") in ("Foreign_Investor", "Foreign_Dealer_Self"))
    return {"net_yi": round(net / 1e8, 1)}


def _foreign_futures_asof(futopt_rows, date_iso):
    foreign = sorted((r for r in futopt_rows
                      if r["date"] < date_iso
                      and r.get("institutional_investors") == "外資"),
                     key=lambda r: r["date"])
    if len(foreign) < 2:
        return None

    def net_oi(r):
        return (r.get("long_open_interest_balance_volume", 0)
                - r.get("short_open_interest_balance_volume", 0))

    latest, prev = net_oi(foreign[-1]), net_oi(foreign[-2])
    return {"net": latest, "change": latest - prev}


def _margin_asof(margin_rows, date_iso):
    rows = [r for r in margin_rows
            if r["date"] < date_iso and r.get("name") == "MarginPurchaseMoney"]
    if not rows:
        return None
    row = max(rows, key=lambda r: r["date"])
    if not row.get("YesBalance"):
        return None
    change_pct = (row["TodayBalance"] / row["YesBalance"] - 1) * 100
    return {"balance_yi": round(row["TodayBalance"] / 1e8, 0),
            "change_pct": round(change_pct, 2)}


def build_raw_asof(src, date_iso):
    """組出與 data_fetch.fetch_all() 同形狀的 raw dict（D 日 8am 視角）。"""
    raw = {name: _quote_asof(series, date_iso)
           for name, series in src["yahoo"].items()}
    raw["night_futures"] = _night_asof(src["finmind"]["futures"], date_iso)
    raw["foreign_buy"] = _foreign_buy_asof(src["finmind"]["inst"], date_iso)
    raw["foreign_futures"] = _foreign_futures_asof(src["finmind"]["futopt"],
                                                   date_iso)
    raw["margin"] = _margin_asof(src["finmind"]["margin"], date_iso)
    return raw


# ── 目標值：當日實際結果（收收、跳空、盤中）────────────────────

def _targets_for(src, date_iso):
    twii = src["targets"]["twii"]
    if date_iso not in twii:
        return None  # 非台股交易日
    two = _last_two_closes_before(twii, date_iso)
    if two is None:
        return None
    prev_close = two[1]  # date_iso 之前的最後一個收盤
    bar = twii[date_iso]
    out = {"twii_pct": round((bar["close"] / prev_close - 1) * 100, 3)}
    if bar["open"]:
        out["gap_pct"] = round((bar["open"] / prev_close - 1) * 100, 3)
        out["intraday_pct"] = round((bar["close"] / bar["open"] - 1) * 100, 3)
    return out


def _category_target(src, key, date_iso):
    series_list = src["targets"].get(key)
    if series_list is None:
        return None
    pcts = []
    for series in series_list:
        if date_iso not in series:
            continue
        two = _last_two_closes_before(series, date_iso)
        if two is None:
            continue
        pcts.append((series[date_iso]["close"] / two[1] - 1) * 100)
    return round(sum(pcts) / len(pcts), 3) if pcts else None


# ── 每因子原始值（供後續 rolling z-score 等分析用）──────────────

def _factor_raws(raw):
    """抽出各因子的『轉換前』原始數值，鍵名對齊 rules 的因子 key。"""
    out = {}
    for k in ("sox", "nasdaq", "tsm_adr", "usdtwd", "xlf", "tnx", "oil",
              "copper", "dxy", "bdry", "tlt", "nvda", "move", "xlu"):
        q = raw.get(k)
        out[k] = q["pct"] if q else None
    out["vix"] = raw["vix"]["last"] if raw.get("vix") else None
    out["night_futures"] = (raw["night_futures"]["change_pct"]
                            if raw.get("night_futures") else None)
    out["foreign_buy"] = (raw["foreign_buy"]["net_yi"]
                          if raw.get("foreign_buy") else None)
    out["foreign_futures"] = (raw["foreign_futures"]["change"]
                              if raw.get("foreign_futures") else None)
    out["margin"] = (raw["margin"]["change_pct"]
                     if raw.get("margin") else None)
    return out


# ── 主流程 ─────────────────────────────────────────────────────

def run(start, end):
    src = fetch_all_sources(start, end)
    trading_days = sorted(d for d in src["targets"]["twii"]
                          if start.isoformat() <= d <= end.isoformat())
    print(f"\n回填 {len(trading_days)} 個台股交易日 "
          f"({trading_days[0]} → {trading_days[-1]}) ...")

    days = []
    for date_iso in trading_days:
        targets = _targets_for(src, date_iso)
        if targets is None:
            continue
        raw = build_raw_asof(src, date_iso)
        day_events = events.events_on(dt.date.fromisoformat(date_iso))
        scale = config.THRESHOLD_EVENT_SCALE if day_events else 1.0
        result = rules.evaluate(raw, threshold_scale=scale)

        cats = {}
        for key in config.CATEGORIES:
            cr = rules.evaluate_category(raw, key, threshold_scale=scale)
            cats[key] = {"score": cr["total_score"],
                         "dir": cr["direction"][:2],
                         "target_pct": _category_target(src, key, date_iso)}

        days.append({
            "date": date_iso,
            "scale": scale,
            "score": result["total_score"],
            "dir": result["direction"][:2],
            "factors": {f["key"]: f["base"] for f in result["factors"]},
            "raws": _factor_raws(raw),
            "targets": targets,
            "categories": cats,
        })
        if len(days) % 100 == 0:
            print(f"  ... {len(days)} 天完成（至 {date_iso}）")

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "backfill.json")
    payload = {"generated": dt.datetime.now().isoformat(timespec="seconds"),
               "start": trading_days[0], "end": trading_days[-1],
               "n_days": len(days), "days": days}
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False)
    print(f"\n完成：{len(days)} 天 → {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-01-01",
                        help="回填起始日 (YYYY-MM-DD)")
    parser.add_argument("--end", default=None,
                        help="回填結束日，預設昨天")
    args = parser.parse_args()
    end = (dt.date.fromisoformat(args.end) if args.end
           else dt.date.today() - dt.timedelta(days=1))
    run(dt.date.fromisoformat(args.start), end)
