"""回測：抓加權指數(^TWII)當日實際漲跌，填回 data JSON，計算命中率。

用法：python backtest.py
判定：偏多→當日漲、偏空→當日跌、震盪→當日平（漲跌幅在平盤帶內）。
命中率累積後，可回頭調整 config.py 的權重與門檻。
"""
import os
import glob
import json
import datetime as dt

TWII = "^TWII"          # 台灣加權指數
FLAT_BAND = 0.4         # 漲跌幅在 ±0.4% 內視為「平盤」
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


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


def run():
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
        pct = _twii_change(date)
        if pct is None:
            print(f"{date:<12}{r['direction'][:2]:<8}{'(尚無收盤資料)'}")
            continue

        actual = _actual_dir(pct)
        pred = _predicted_dir(r["direction"])
        hit = (pred == actual)
        mark = "✓" if hit else "✗"

        r["actual"] = f"{actual} {pct:+.2f}% {mark}"
        r["actual_pct"] = round(pct, 2)
        r["hit"] = hit
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(r, fp, ensure_ascii=False, indent=2)

        total += 1
        filled += 1
        hits += hit
        b = by_pred.setdefault(r["direction"][:2], [0, 0])
        b[0] += hit
        b[1] += 1
        print(f"{date:<12}{r['direction'][:2]:<8}{actual} {pct:+.2f}%　 {mark}")

    print("-" * 44)
    if total:
        print(f"整體命中率：{hits}/{total} = {hits/total*100:.1f}%")
        for pred, (h, n) in by_pred.items():
            print(f"  預測{pred}：{h}/{n} = {h/n*100:.0f}%")
    print(f"\n已更新 {filled} 筆 data JSON（actual 欄位）。"
          "重跑 webgen.py 可讓網頁歷史顯示實際結果。")


if __name__ == "__main__":
    run()
