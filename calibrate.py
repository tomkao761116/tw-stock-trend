"""權重校準：依歷史回測資料，分析各因子與實際漲跌的相關性，建議權重調整。

用法：python calibrate.py
原理：每個因子的標準化分數(base, [-1,1]) 與當日實際漲跌幅(actual_pct) 的
皮爾森相關係數 r，代表該因子的「預測力」。r 高 → 值得提高權重；r 近 0 → 訊號弱。

刻意採透明的相關性分析而非多元迴歸：樣本少時迴歸容易過度擬合。
本腳本只給「建議」，不自動改 config.py——調權重仍由你手動決定。
"""
import os
import glob
import json

import config

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MIN_SAMPLES = 10   # 低於此樣本數不給建議（資料不足）
STRONG, WEAK = 0.30, 0.10  # 相關性強/弱門檻


def _pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / (sxx * syy) ** 0.5


def _load_backtested():
    """載入已回測（有 actual_pct）的每日資料。"""
    items = []
    for path in glob.glob(os.path.join(DATA_DIR, "*.json")):
        with open(path, encoding="utf-8") as fp:
            r = json.load(fp)
        if r.get("actual_pct") is not None:
            items.append(r)
    return items


def _suggest(r, n):
    if n < MIN_SAMPLES:
        return "資料不足"
    if r is None:
        return "—"
    if r < -WEAK:
        return "⚠ 反向，檢視邏輯"
    if r >= STRONG:
        return "↑ 可提高"
    if r < WEAK:
        return "↓ 訊號弱，可降低"
    return "→ 維持"


def run():
    items = _load_backtested()
    n_days = len(items)
    print(f"已回測樣本：{n_days} 天")
    if n_days == 0:
        print("尚無回測資料。先跑 backtest.py 填入實際漲跌再來校準。")
        return
    if n_days < MIN_SAMPLES:
        print(f"⚠ 樣本不足（建議 ≥ {MIN_SAMPLES} 天）。以下相關性僅供參考，"
              "尚不足以據此調整權重。\n")

    # 每個因子蒐集 (base, actual_pct)
    keys = list(config.WEIGHTS.keys())
    print(f"{'因子':<16}{'樣本':>4}{'相關性 r':>10}{'現權重':>8}  建議")
    print("-" * 56)
    for key in keys:
        xs, ys = [], []
        for r in items:
            f = next((x for x in r.get("factors", []) if x.get("key") == key), None)
            if f and f.get("base") is not None:
                xs.append(f["base"])
                ys.append(r["actual_pct"])
        corr = _pearson(xs, ys)
        nick = config.FACTOR_INFO.get(key, {}).get("nick", key)
        w = config.WEIGHTS[key]
        corr_txt = f"{corr:+.2f}" if corr is not None else "—"
        print(f"{nick:<16}{len(xs):>4}{corr_txt:>10}{w:>8.1f}  {_suggest(corr, len(xs))}")

    # 整體命中率
    hits = sum(1 for r in items if r.get("hit"))
    print("-" * 56)
    print(f"整體命中率：{hits}/{n_days} = {hits/n_days*100:.1f}%")
    print("\n調整方式：依建議手動編輯 config.py 的 WEIGHTS，再跑 backtest.py 觀察命中率變化。")


if __name__ == "__main__":
    run()
