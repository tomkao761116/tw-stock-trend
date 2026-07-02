"""回測：抓加權指數(^TWII)當日實際漲跌，填回 data JSON，計算命中率。

用法：python backtest.py         # 只查詢尚缺 actual 的日期（預設，適合每日自動執行）
      python backtest.py --force # 強制重新查詢所有日期（手動核對用）
判定：偏多→當日漲、偏空→當日跌、震盪→當日平（漲跌幅在平盤帶內）。
命中率累積後，可回頭調整 config.py 的權重與門檻。
"""
import os
import glob
import json
import datetime as dt

TWII = "^TWII"          # 台灣加權指數
FLAT_BAND = 0.4         # 漲跌幅在 ±0.4% 內視為「平盤」
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


def _twii_change(date_str):
    """回傳該日加權指數相對前一交易日的漲跌幅(%)；取不到回 None。"""
    import yfinance as yf

    d = dt.date.fromisoformat(date_str)
    start = (d - dt.timedelta(days=7)).isoformat()
    end = (d + dt.timedelta(days=1)).isoformat()
    hist = yf.Ticker(TWII).history(start=start, end=end)
    if hist.empty:
        return None
    hist.index = [t.date().isoformat() for t in hist.index]
    if date_str not in hist.index:
        return None  # 該日非交易日或資料未到
    closes = hist["Close"]
    pos = list(hist.index).index(date_str)
    if pos == 0:
        return None  # 沒有前一日可比
    prev, cur = float(closes.iloc[pos - 1]), float(closes.iloc[pos])
    return (cur / prev - 1) * 100


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
    print(f"{'日期':<12}{'預估':<8}{'實際':<10}{'結果'}")
    print("-" * 44)

    for path in files:
        with open(path, encoding="utf-8") as fp:
            r = json.load(fp)
        date = r["date"]

        if not _eligible(date):
            if r.get("actual_pct") is not None:
                # 曾被誤填入盤中即時價（舊版 bug），清除避免顯示錯誤的命中結果
                r["actual"], r["actual_pct"], r["hit"] = None, None, None
                with open(path, "w", encoding="utf-8") as fp:
                    json.dump(r, fp, ensure_ascii=False, indent=2)
                print(f"{date:<12}{r['direction'][:2]:<8}{'(今天尚未收盤，已清除誤填資料)'}")
            else:
                print(f"{date:<12}{r['direction'][:2]:<8}{'(今天尚未收盤，暫不計入)'}")
            continue

        # 已有結果就沿用，不重複打 API（每日自動執行時大多數日期都屬此情況）
        if not force and r.get("actual_pct") is not None:
            pct, hit = r["actual_pct"], bool(r.get("hit"))
            mark = "✓" if hit else "✗"
            print(f"{date:<12}{r['direction'][:2]:<8}"
                  f"{_actual_dir(pct)} {pct:+.2f}%　 {mark}（沿用既有）")
        else:
            pct = _twii_change(date)
            if pct is None:
                print(f"{date:<12}{r['direction'][:2]:<8}{'(尚無收盤資料)'}")
                continue
            hit = (_predicted_dir(r["direction"]) == _actual_dir(pct))
            mark = "✓" if hit else "✗"
            r["actual"] = f"{_actual_dir(pct)} {pct:+.2f}% {mark}"
            r["actual_pct"] = round(pct, 2)
            r["hit"] = hit
            with open(path, "w", encoding="utf-8") as fp:
                json.dump(r, fp, ensure_ascii=False, indent=2)
            filled += 1
            print(f"{date:<12}{r['direction'][:2]:<8}{_actual_dir(pct)} {pct:+.2f}%　 {mark}")

        total += 1
        hits += hit
        b = by_pred.setdefault(r["direction"][:2], [0, 0])
        b[0] += hit
        b[1] += 1

    print("-" * 44)
    if total:
        print(f"整體命中率：{hits}/{total} = {hits/total*100:.1f}%")
        for pred, (h, n) in by_pred.items():
            print(f"  預測{pred}：{h}/{n} = {h/n*100:.0f}%")
    print(f"\n本次新填入 {filled} 筆（其餘沿用既有結果）。"
          "重跑 webgen.py 可讓網頁歷史顯示實際結果。")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="強制重新查詢所有日期，不沿用既有結果")
    run(force=parser.parse_args().force)
