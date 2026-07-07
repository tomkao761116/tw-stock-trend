"""回測：抓加權指數(^TWII)當日實際漲跌，填回 data JSON，計算命中率。

用法：python backtest.py         # 只查詢尚缺 actual 的日期（預設，適合每日自動執行）
      python backtest.py --force # 強制重新查詢所有日期（手動核對用）
判定：偏多→當日漲、偏空→當日跌、震盪→當日平（漲跌幅在平盤帶內）。
命中率累積後，可回頭調整 config.py 的權重與門檻。
"""
import os
import glob
import json
import math
import datetime as dt

import config

TWII = "^TWII"          # 台灣加權指數
FLAT_BAND = 0.4         # 漲跌幅在 ±0.4% 內視為「平盤」
GAP_FLAT_BAND = 0.2     # 跳空在 ±0.2% 內視為「平開」（603 天回測 |gap| 中位數 0.33%）
MARKET_CLOSE = dt.time(13, 30)  # 台股收盤時間；今天收盤前不採計「實際」結果
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def _eligible(date_str):
    """是否已收盤、可計入實際結果。今天盤中的即時價不算數（yfinance 會回傳未收盤的
    當日暫定價，誤判會導致當天收盤前就出現錯誤的命中/不中結果）。"""
    d = dt.date.fromisoformat(date_str)
    now = dt.datetime.now()
    if d < now.date():
        return True
    if d == now.date():
        return now.time() >= MARKET_CLOSE
    return False  # 未來日期，不應發生


def _ticker_change(ticker, date_str):
    """回傳該日某標的相對前一交易日的漲跌幅(%)；取不到回 None。
    market(大盤)用 ^TWII，各類別用各自的 backtest_ticker（見 config.CATEGORIES）。
    ticker 可以是單一字串，或字串 list——list 時做等權重平均，用於沒有乾淨單一 ETF
    的類別（如傳產：長榮/中鋼/台塑等權重組合代理這個異質產業籃子）。"""
    if isinstance(ticker, (list, tuple)):
        changes = [c for c in (_single_ticker_change(t, date_str) for t in ticker)
                  if c is not None]
        return sum(changes) / len(changes) if changes else None
    return _single_ticker_change(ticker, date_str)


def _finmind_code(ticker):
    """yfinance 代號 → FinMind data_id：^TWII=加權指數，其餘去掉 .TW/.TWO 後綴。"""
    if ticker == TWII:
        return "TAIEX"
    return ticker.replace(".TWO", "").replace(".TW", "")


def _finmind_bars(ticker, date_str):
    """從 FinMind 取該日 {prev_close, open, close}；取不到回 None。
    FinMind 是台股在地源、收盤後即時更新，避開 Yahoo 對台股指數/ETF 約一天的延遲
    （隔日回填抓不到昨日收盤的主因，見 _fetch_bars）。"""
    import requests
    from data_fetch import _finmind_token

    token = _finmind_token()
    if not token:
        return None
    d = dt.date.fromisoformat(date_str)
    try:
        r = requests.get("https://api.finmindtrade.com/api/v4/data", params={
            "dataset": "TaiwanStockPrice", "data_id": _finmind_code(ticker),
            "start_date": (d - dt.timedelta(days=12)).isoformat(),
            "end_date": date_str, "token": token}, timeout=30)
        r.raise_for_status()
        rows = r.json().get("data", [])
    except Exception:
        return None
    rows = [x for x in rows if x.get("close")]  # 濾掉收盤缺值
    dates = sorted(x["date"] for x in rows)
    if date_str not in dates:
        return None  # 該日非交易日或 FinMind 尚未更新
    pos = dates.index(date_str)
    if pos == 0:
        return None  # 沒有前一交易日可比
    by_date = {x["date"]: x for x in rows}
    cur, prev = by_date[date_str], by_date[dates[pos - 1]]
    return {"prev_close": float(prev["close"]),
            "open": float(cur["open"]) if cur.get("open") else None,
            "close": float(cur["close"])}


def _yahoo_bars(ticker, date_str):
    """從 Yahoo 取該日 {prev_close, open, close}；取不到回 None。FinMind 失敗時的備援。"""
    import yfinance as yf

    d = dt.date.fromisoformat(date_str)
    hist = yf.Ticker(ticker).history(start=(d - dt.timedelta(days=12)).isoformat(),
                                     end=(d + dt.timedelta(days=1)).isoformat())
    if hist.empty:
        return None
    hist.index = [t.date().isoformat() for t in hist.index]
    if date_str not in hist.index:
        return None
    pos = list(hist.index).index(date_str)
    if pos == 0:
        return None
    prev = float(hist["Close"].iloc[pos - 1])
    o = float(hist["Open"].iloc[pos])
    c = float(hist["Close"].iloc[pos])
    if math.isnan(prev) or math.isnan(c):
        return None  # 收盤缺值（Yahoo 對成交量低的台股 ETF 偶見），視為尚無資料
    return {"prev_close": prev, "open": (None if math.isnan(o) else o), "close": c}


def _fetch_bars(ticker, date_str):
    """該日 {prev_close, open, close}：FinMind 優先（台股在地源、即時），Yahoo 備援。
    設計原因：Yahoo 對台股指數(^TWII)與 ETF 日線有約一天延遲，隔日早上回測抓不到
    昨日收盤——換 FinMind 為主源即可當日回填，Yahoo 僅在 FinMind 無 token/故障時墊底。"""
    return _finmind_bars(ticker, date_str) or _yahoo_bars(ticker, date_str)


def _single_ticker_change(ticker, date_str):
    b = _fetch_bars(ticker, date_str)
    if b is None:
        return None
    return (b["close"] / b["prev_close"] - 1) * 100


def _single_gap_intraday(ticker, date_str):
    """單一標的當日 (跳空%, 盤中%)；取不到（含當日無開盤價）回 None。
    跳空 = 開盤 vs 前一日收盤、盤中 = 收盤 vs 開盤。來源同 _fetch_bars（FinMind 優先）。"""
    b = _fetch_bars(ticker, date_str)
    if b is None or b["open"] is None:
        return None
    return (b["open"] / b["prev_close"] - 1) * 100, (b["close"] / b["open"] - 1) * 100


def _gap_intraday(ticker, date_str):
    """該日 (跳空%, 盤中%)；ticker 可為單一字串或字串 list（籃子取等權平均）。
    與 _ticker_change 一致，用於傳產這種以個股組合代理的類別。"""
    if isinstance(ticker, (list, tuple)):
        pairs = [gi for gi in (_single_gap_intraday(t, date_str) for t in ticker)
                 if gi is not None]
        if not pairs:
            return None
        return (sum(g for g, _ in pairs) / len(pairs),
                sum(i for _, i in pairs) / len(pairs))
    return _single_gap_intraday(ticker, date_str)


def _fill_two_part(rec, gap, intra):
    """把 (跳空, 盤中) 實際值寫進含 open_call/intraday_call 的 dict（大盤或類別共用）。
    開盤 vs 跳空（±GAP_FLAT_BAND 平開帶）、盤中展望 vs 開→收（±FLAT_BAND 平盤帶）。"""
    open_pred = ("漲" if "開高" in rec["open_call"]["direction"]
                 else "跌" if "開低" in rec["open_call"]["direction"] else "平")
    intra_pred = ("漲" if "偏多" in rec["intraday_call"]["direction"]
                  else "跌" if "偏空" in rec["intraday_call"]["direction"] else "平")
    open_act = ("開高" if gap > GAP_FLAT_BAND
                else "開低" if gap < -GAP_FLAT_BAND else "平開")
    intra_act = _actual_dir(intra)
    open_hit = ({"開高": "漲", "開低": "跌", "平開": "平"}[open_act] == open_pred)
    intra_hit = (intra_act == intra_pred)
    rec["open_actual"] = f"{open_act} {gap:+.2f}% {'✓' if open_hit else '✗'}"
    rec["open_hit"] = open_hit
    rec["intraday_actual"] = f"{intra_act} {intra:+.2f}% {'✓' if intra_hit else '✗'}"
    rec["intraday_hit"] = intra_hit


def _backtest_two_part(r, date, force):
    """大盤開盤方向/盤中展望的實際結果回填（僅含 open_call 的新格式資料）。回傳是否有變動。"""
    if not r.get("open_call") or not _eligible(date):
        return False
    if not force and r.get("open_actual") is not None:
        return False
    gi = _gap_intraday(TWII, date)
    if gi is None:
        return False
    _fill_two_part(r, *gi)
    return True


def _is_filled(pct):
    """判斷 actual_pct 是否為「已有效填入」。NaN 視為未填入（自我修復：
    萬一資料源曾回傳 NaN 被存下來，下次執行會當作缺資料重新查詢，而不是永遠卡住）。"""
    return pct is not None and not (isinstance(pct, float) and math.isnan(pct))


def _actual_dir(pct):
    if pct > FLAT_BAND:
        return "漲"
    if pct < -FLAT_BAND:
        return "跌"
    return "平"


def _predicted_dir(direction):
    if "偏多" in direction:
        return "漲"
    if "偏空" in direction:
        return "跌"
    return "平"


def run(force=False):
    files = sorted(glob.glob(os.path.join(DATA_DIR, "*.json")))
    if not files:
        print("data/ 無資料")
        return

    total = hits = filled = 0
    by_pred = {}  # 預測方向 → [命中數, 總數]
    stale = []    # 已收盤但仍抓不到收盤資料的日期（資料源異常的警訊）
    print(f"{'日期':<12}{'預估':<8}{'實際':<10}{'結果'}")
    print("-" * 44)

    for path in files:
        with open(path, encoding="utf-8") as fp:
            r = json.load(fp)
        date = r["date"]
        changed = False

        if not _eligible(date):
            if _is_filled(r.get("actual_pct")):
                # 曾被誤填入盤中即時價（舊版 bug），清除避免顯示錯誤的命中結果
                r["actual"], r["actual_pct"], r["hit"] = None, None, None
                changed = True
                print(f"{date:<12}{r['direction'][:2]:<8}{'(今天尚未收盤，已清除誤填資料)'}")
            else:
                print(f"{date:<12}{r['direction'][:2]:<8}{'(今天尚未收盤，暫不計入)'}")
            changed = _backtest_categories(r, date, force) or changed
            if changed:
                with open(path, "w", encoding="utf-8") as fp:
                    json.dump(r, fp, ensure_ascii=False, indent=2)
            continue

        # 已有結果就沿用，不重複打 API（每日自動執行時大多數日期都屬此情況）
        if not force and _is_filled(r.get("actual_pct")):
            pct, hit = r["actual_pct"], bool(r.get("hit"))
            mark = "✓" if hit else "✗"
            print(f"{date:<12}{r['direction'][:2]:<8}"
                  f"{_actual_dir(pct)} {pct:+.2f}%　 {mark}（沿用既有）")
        else:
            pct = _ticker_change(TWII, date)
            if pct is None:
                stale.append(date)
                print(f"{date:<12}{r['direction'][:2]:<8}{'(尚無收盤資料)'}")
                if r.get("actual_pct") is not None:  # 清掉可能殘留的 NaN 垃圾資料
                    r["actual"], r["actual_pct"], r["hit"] = None, None, None
                    changed = True
                changed = _backtest_categories(r, date, force) or changed
                if changed:
                    with open(path, "w", encoding="utf-8") as fp:
                        json.dump(r, fp, ensure_ascii=False, indent=2)
                continue
            hit = (_predicted_dir(r["direction"]) == _actual_dir(pct))
            mark = "✓" if hit else "✗"
            r["actual"] = f"{_actual_dir(pct)} {pct:+.2f}% {mark}"
            r["actual_pct"] = round(pct, 2)
            r["hit"] = hit
            filled += 1
            changed = True
            print(f"{date:<12}{r['direction'][:2]:<8}{_actual_dir(pct)} {pct:+.2f}%　 {mark}")

        total += 1
        hits += hit
        b = by_pred.setdefault(r["direction"][:2], [0, 0])
        b[0] += hit
        b[1] += 1

        changed = _backtest_two_part(r, date, force) or changed
        changed = _backtest_categories(r, date, force) or changed
        if changed:
            with open(path, "w", encoding="utf-8") as fp:
                json.dump(r, fp, ensure_ascii=False, indent=2)

    print("-" * 44)
    if total:
        print(f"整體命中率：{hits}/{total} = {hits/total*100:.1f}%")
        for pred, (h, n) in by_pred.items():
            print(f"  預測{pred}：{h}/{n} = {h/n*100:.0f}%")
    _print_two_part_summary(files)
    print(f"\n本次新填入 {filled} 筆（其餘沿用既有結果）。"
          "重跑 webgen.py 可讓網頁歷史顯示實際結果。")

    if stale:
        # 已收盤卻抓不到收盤價：兩個資料源(FinMind→Yahoo)都失敗，屬異常需人工留意。
        # 下次執行會自動再試（自我修復），但連續多天出現代表資料源或 token 有問題。
        print(f"\n⚠️  警告：{len(stale)} 個已收盤日期仍抓不到收盤資料："
              f"{'、'.join(stale)}")
        print("    FinMind + Yahoo 皆失敗——請檢查 .finmind_token 是否有效、網路或 API 狀態。")

    _print_category_summary(files)


def _backtest_categories(r, date, force):
    """對 r["categories"] 底下每個有 backtest_ticker 的類別回填實際結果。回傳是否有變動。"""
    changed = False
    for key, cat_cfg in config.CATEGORIES.items():
        cr = r.get("categories", {}).get(key)
        ticker = cat_cfg.get("backtest_ticker")
        if cr is None or ticker is None:
            continue  # 無此類別資料，或該類別無乾淨的回測標的（如傳產）

        if not _eligible(date):
            if _is_filled(cr.get("actual_pct")):
                cr["actual"], cr["actual_pct"], cr["hit"] = None, None, None
                changed = True
            continue

        if not force and _is_filled(cr.get("actual_pct")):
            continue  # 沿用既有，不重打 API

        pct = _ticker_change(ticker, date)
        if pct is None:
            if cr.get("actual_pct") is not None:  # 清掉可能殘留的 NaN 垃圾資料
                cr["actual"], cr["actual_pct"], cr["hit"] = None, None, None
                changed = True
            continue
        hit = (_predicted_dir(cr["direction"]) == _actual_dir(pct))
        cr["actual"] = f"{_actual_dir(pct)} {pct:+.2f}% {'✓' if hit else '✗'}"
        cr["actual_pct"] = round(pct, 2)
        cr["hit"] = hit
        changed = True

        # 兩段式（開盤/盤中）實際結果——類別與大盤共用同一套判定
        if cr.get("open_call") and (force or cr.get("open_actual") is None):
            gi = _gap_intraday(ticker, date)
            if gi is not None:
                _fill_two_part(cr, *gi)
    return changed


def _print_two_part_summary(files):
    """開盤方向/盤中展望的累積命中率（僅新格式資料，舊資料無此欄位自動跳過）。"""
    oh = on = ih = in_ = 0
    for path in files:
        with open(path, encoding="utf-8") as fp:
            r = json.load(fp)
        if r.get("open_hit") is not None:
            on += 1
            oh += bool(r["open_hit"])
        if r.get("intraday_hit") is not None:
            in_ += 1
            ih += bool(r["intraday_hit"])
    if on:
        print(f"開盤方向命中率：{oh}/{on} = {oh/on*100:.0f}%　｜　"
              f"盤中展望命中率：{ih}/{in_} = {ih/in_*100:.0f}%")


def _print_category_summary(files):
    """各類別累積命中率摘要（獨立於大盤表格之後印出）。"""
    stats = {}
    for path in files:
        with open(path, encoding="utf-8") as fp:
            r = json.load(fp)
        for key, cat_cfg in config.CATEGORIES.items():
            cr = r.get("categories", {}).get(key)
            if not cr:
                continue
            if cat_cfg.get("backtest_ticker") is None:
                stats.setdefault(key, {"label": cat_cfg["label"], "no_ticker": True})
                continue
            if cr.get("hit") is None:
                continue
            s = stats.setdefault(key, {"label": cat_cfg["label"], "hit": 0, "total": 0})
            s["total"] += 1
            s["hit"] += bool(cr["hit"])

    if not stats:
        return
    print("\n各類別命中率：")
    for key in config.CATEGORIES:
        s = stats.get(key)
        if not s:
            continue
        if s.get("no_ticker"):
            print(f"  {s['label']}：無乾淨的單一回測標的，暫不計算命中率")
        elif s["total"]:
            print(f"  {s['label']}：{s['hit']}/{s['total']} = {s['hit']/s['total']*100:.0f}%")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="強制重新查詢所有日期，不沿用既有結果")
    run(force=parser.parse_args().force)
