"""回填資料分析：驗證改善假設，產生調參證據。

用法：python analyze.py
輸入：backfill/backfill.json（先跑 backfill.py）

分析項目：
  1. 現行設定的命中率（3 分類，與 backtest.py 同判定）＋方向純度
  2. 預測目標拆解：收收 vs 跳空 vs 盤中——因子到底擅長預測哪一段
  3. 各因子預測力（IC：base 與三種目標的皮爾森 r）
  4. 隔夜因子共線性矩陣 ＋ 變體 A/B（bucket cap / 殘差化）
  5. 標準化 A/B：固定常數 vs 滾動 z-score
  6. 門檻掃描（70/30 train/validation，防過擬合）
  7. 信心指標校準（各信心等級的實際方向命中率）
  8. 各類別命中率
"""
import os
import json
import math
import statistics

import config

BF_PATH = os.path.join(os.path.dirname(__file__), "backfill", "backfill.json")
FLAT_BAND = 0.4          # 與 backtest.py 一致
OVERNIGHT = ["night_futures", "sox", "tsm_adr", "nasdaq"]
ZSCORE_WINDOW = 60       # 滾動標準差視窗（交易日）
ZSCORE_FULL_SIGMA = 2.0  # z-score 標準化：幾個 σ = 滿分
TRAIN_RATIO = 0.7


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


def _clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def _dir3(pct, band):
    if pct > band:
        return "漲"
    if pct < -band:
        return "跌"
    return "平"


def _pred3(score, bull, bear):
    if score >= bull:
        return "漲"
    if score <= bear:
        return "跌"
    return "平"


def _hit_stats(days, score_key, bull, bear, target_key):
    """回傳 (3分類命中率, 方向純度, 喊方向覆蓋率, n)。
    方向純度 = 喊多/空的日子中，目標同號的比例（不管平盤帶）。"""
    total = hits = 0
    dir_total = dir_hits = 0
    for d in days:
        t = d["targets"].get(target_key)
        if t is None:
            continue
        score = d[score_key] if isinstance(score_key, str) else score_key(d)
        p = _pred3(score, bull * d["scale"], bear * d["scale"])
        total += 1
        hits += (p == _dir3(t, FLAT_BAND))
        if p != "平":
            dir_total += 1
            dir_hits += ((p == "漲") == (t > 0))
    hit_rate = hits / total if total else None
    purity = dir_hits / dir_total if dir_total else None
    coverage = dir_total / total if total else None
    return hit_rate, purity, coverage, total


def _fmt_pct(x):
    return f"{x*100:5.1f}%" if x is not None else "  —  "


# ── 1+2. 現行設定 × 三種目標 ───────────────────────────────────

def report_current(days):
    print("=" * 62)
    print("【1+2】現行設定命中率 × 預測目標拆解")
    print("=" * 62)
    print(f"{'目標':<14}{'3分類命中':>10}{'方向純度':>10}{'喊方向覆蓋':>11}")
    for label, tk in (("收盤vs前收", "twii_pct"), ("開盤跳空", "gap_pct"),
                      ("盤中(開→收)", "intraday_pct")):
        h, p, c, n = _hit_stats(days, "score",
                                config.THRESHOLD_BULLISH,
                                config.THRESHOLD_BEARISH, tk)
        print(f"{label:<14}{_fmt_pct(h):>10}{_fmt_pct(p):>10}{_fmt_pct(c):>11}"
              f"  (n={n})")
    print("→ 方向純度 = 喊多/空時目標同號的比例；跳空 vs 盤中的差距"
          "顯示因子真正擅長的預測段。")


# ── 3. 因子 IC ─────────────────────────────────────────────────

def report_factor_ic(days):
    print()
    print("=" * 62)
    print("【3】各因子預測力（base 與目標的皮爾森 r）")
    print("=" * 62)
    print(f"{'因子':<20}{'n':>5}{'收收r':>8}{'跳空r':>8}{'盤中r':>8}{'現權重':>7}")
    for key in config.WEIGHTS:
        rows = [(d["factors"].get(key), d["targets"]) for d in days
                if d["factors"].get(key) is not None]
        if not rows:
            continue
        cols = {}
        for tk in ("twii_pct", "gap_pct", "intraday_pct"):
            xs = [b for b, t in rows if t.get(tk) is not None]
            ys = [t[tk] for b, t in rows if t.get(tk) is not None]
            r = _pearson(xs, ys)
            cols[tk] = f"{r:+.2f}" if r is not None else "—"
        nick = config.FACTOR_INFO.get(key, {}).get("nick", key)
        print(f"{nick:<20}{len(rows):>5}{cols['twii_pct']:>8}"
              f"{cols['gap_pct']:>8}{cols['intraday_pct']:>8}"
              f"{config.WEIGHTS[key]:>7.1f}")


# ── 4. 共線性 ＋ 變體 ──────────────────────────────────────────

def report_collinearity(days):
    print()
    print("=" * 62)
    print("【4】隔夜因子共線性（base 相關矩陣）")
    print("=" * 62)
    print(f"{'':<16}" + "".join(f"{k[:9]:>10}" for k in OVERNIGHT))
    for a in OVERNIGHT:
        row = f"{a[:14]:<16}"
        for b in OVERNIGHT:
            xs, ys = [], []
            for d in days:
                fa, fb = d["factors"].get(a), d["factors"].get(b)
                if fa is not None and fb is not None:
                    xs.append(fa)
                    ys.append(fb)
            r = _pearson(xs, ys)
            row += f"{r:+.2f}" .rjust(10) if r is not None else " — ".rjust(10)
        print(row)


def _score_capped(d, cap):
    """變體 A：隔夜四因子合計貢獻夾在 ±cap，其餘因子照舊。"""
    over = other = 0.0
    for k, w in config.WEIGHTS.items():
        b = d["factors"].get(k)
        if b is None:
            continue
        c = b * w
        if k in OVERNIGHT:
            over += c
        else:
            other += c
    return _clamp(over, -cap, cap) + other


def _residual_bases(days):
    """變體 B：sox/tsm_adr/nasdaq 的 raw 改為對夜盤的殘差，重算 base。"""
    n_map = {"sox": "sox_full_pct", "tsm_adr": "tsm_adr_full_pct",
             "nasdaq": "nasdaq_full_pct"}
    out = []
    for d in days:
        night_raw = d["raws"].get("night_futures")
        bases = dict(d["factors"])
        if night_raw is not None:
            for k, nk in n_map.items():
                raw = d["raws"].get(k)
                if raw is not None:
                    bases[k] = _clamp((raw - night_raw)
                                      / config.NORMALIZERS[nk])
        out.append({**d, "factors": bases})
    return out


def _score_from_bases(d):
    return sum((d["factors"].get(k) or 0.0) * w
               for k, w in config.WEIGHTS.items())


def report_variants(days, train, val):
    print()
    print("=" * 62)
    print("【4b】共線性處理變體（train 掃參數 → validation 驗證）")
    print("=" * 62)
    base_h, base_p, base_c, _ = _hit_stats(
        val, "score", config.THRESHOLD_BULLISH, config.THRESHOLD_BEARISH,
        "twii_pct")
    print(f"{'方案':<26}{'val命中':>9}{'val純度':>9}{'val覆蓋':>9}")
    print(f"{'現行（基準）':<26}{_fmt_pct(base_h):>9}{_fmt_pct(base_p):>9}"
          f"{_fmt_pct(base_c):>9}")

    # 變體 A：cap 掃描
    best_cap, best_train = None, -1
    for cap in (4.0, 5.0, 6.0, 7.0):
        h, p, c, _ = _hit_stats(train, lambda d, cap=cap: _score_capped(d, cap),
                                config.THRESHOLD_BULLISH,
                                config.THRESHOLD_BEARISH, "twii_pct")
        if h is not None and h > best_train:
            best_train, best_cap = h, cap
    h, p, c, _ = _hit_stats(val, lambda d: _score_capped(d, best_cap),
                            config.THRESHOLD_BULLISH,
                            config.THRESHOLD_BEARISH, "twii_pct")
    print(f"{'A: 隔夜合計cap=' + str(best_cap):<26}{_fmt_pct(h):>9}"
          f"{_fmt_pct(p):>9}{_fmt_pct(c):>9}")

    # 變體 B：殘差化
    val_res = _residual_bases(val)
    h, p, c, _ = _hit_stats(val_res, _score_from_bases,
                            config.THRESHOLD_BULLISH,
                            config.THRESHOLD_BEARISH, "twii_pct")
    print(f"{'B: 美股因子殘差化':<26}{_fmt_pct(h):>9}{_fmt_pct(p):>9}"
          f"{_fmt_pct(c):>9}")


# ── 5. 滾動 z-score 標準化 A/B ─────────────────────────────────

_PCT_FACTORS = {  # key: (raw取負號?, normalizer key)
    "night_futures": (False, "night_full_pct"),
    "sox": (False, "sox_full_pct"), "tsm_adr": (False, "tsm_adr_full_pct"),
    "nasdaq": (False, "nasdaq_full_pct"), "usdtwd": (True, "usdtwd_full_pct"),
    "margin": (True, "margin_full_pct"),
}


def _zscore_days(days):
    """對漲跌幅型因子改用滾動 σ 標準化，重算大盤 base；其餘因子沿用原 base。"""
    hist = {k: [] for k in _PCT_FACTORS}
    out = []
    for d in days:
        bases = dict(d["factors"])
        ok = True
        for k, (inv, _) in _PCT_FACTORS.items():
            raw = d["raws"].get(k)
            series = hist[k]
            if raw is not None:
                if len(series) >= ZSCORE_WINDOW:
                    sd = statistics.pstdev(series[-ZSCORE_WINDOW:])
                    if sd > 0:
                        z = raw / (ZSCORE_FULL_SIGMA * sd)
                        bases[k] = _clamp(-z if inv else z)
                else:
                    ok = False
                series.append(raw)
            # raw 缺漏日不更新序列，base 沿用原值
        out.append({**d, "factors": bases, "_z_ok": ok})
    return [d for d in out if d["_z_ok"]]


def report_zscore(days, split_date):
    print()
    print("=" * 62)
    print(f"【5】標準化 A/B：固定常數 vs 滾動{ZSCORE_WINDOW}日σ"
          f"（{ZSCORE_FULL_SIGMA}σ=滿分）")
    print("=" * 62)
    z_days = _zscore_days(days)
    z_dates = {d["date"] for d in z_days}
    same = [d for d in days if d["date"] in z_dates]  # 同一比較母體
    print(f"{'方案':<26}{'命中':>9}{'純度':>9}{'覆蓋':>9}  (n={len(same)})")
    for label, ds, sk in (("固定常數（現行）", same, "score"),
                          ("滾動z-score", z_days, _score_from_bases)):
        h, p, c, _ = _hit_stats(ds, sk, config.THRESHOLD_BULLISH,
                                config.THRESHOLD_BEARISH, "twii_pct")
        print(f"{label:<26}{_fmt_pct(h):>9}{_fmt_pct(p):>9}{_fmt_pct(c):>9}")


# ── 6. 門檻掃描 ────────────────────────────────────────────────

def report_threshold_sweep(train, val):
    print()
    print("=" * 62)
    print("【6】門檻掃描（對稱 ±T；train 選 → val 驗證）")
    print("=" * 62)
    print(f"{'T':>5}{'train命中':>11}{'train覆蓋':>11}{'val命中':>9}{'val覆蓋':>9}")
    best_t, best_score = None, -1
    for t10 in range(20, 85, 5):
        t = t10 / 10
        th, _, tc, _ = _hit_stats(train, "score", t, -t, "twii_pct")
        vh, _, vc, _ = _hit_stats(val, "score", t, -t, "twii_pct")
        mark = ""
        if th is not None and th > best_score:
            best_score, best_t = th, t
            mark = " ←train最佳"
        print(f"{t:>5.1f}{_fmt_pct(th):>11}{_fmt_pct(tc):>11}"
              f"{_fmt_pct(vh):>9}{_fmt_pct(vc):>9}{mark}")
    print(f"→ train 最佳 T={best_t}（現行 {config.THRESHOLD_BULLISH}）；"
          "以 val 欄位判斷是否真的較優，命中率差距 <2pp 視為雜訊。")


# ── 7. 信心校準 ────────────────────────────────────────────────

def report_confidence(days):
    print()
    print("=" * 62)
    print("【7】信心指標校準（喊方向日，依 |總分|/門檻 分桶）")
    print("=" * 62)
    buckets = [("偏低 <1.25", 1.0, 1.25), ("中等 1.25-1.5", 1.25, 1.5),
               ("高 1.5-2.0", 1.5, 2.0), ("很高 ≥2.0", 2.0, 99.0)]
    print(f"{'信心桶':<16}{'n':>5}{'方向純度':>10}{'3分類命中':>11}")
    for label, lo, hi in buckets:
        n = ok = hit3 = 0
        for d in days:
            t = d["targets"].get("twii_pct")
            if t is None:
                continue
            bull = config.THRESHOLD_BULLISH * d["scale"]
            ratio = abs(d["score"]) / bull
            p = _pred3(d["score"], bull, -bull)
            if p == "平" or not (lo <= ratio < hi):
                continue
            n += 1
            ok += ((p == "漲") == (t > 0))
            hit3 += (p == _dir3(t, FLAT_BAND))
        print(f"{label:<16}{n:>5}{_fmt_pct(ok/n if n else None):>10}"
              f"{_fmt_pct(hit3/n if n else None):>11}")
    print("→ 純度應隨信心桶單調上升；若否，_confidence 的門檻要調。")


# ── 8. 類別命中率 ──────────────────────────────────────────────

def report_categories(days):
    print()
    print("=" * 62)
    print("【8】各類別命中率（現行設定）")
    print("=" * 62)
    print(f"{'類別':<16}{'n':>5}{'3分類命中':>11}{'方向純度':>10}{'覆蓋':>8}")
    for key, cat in config.CATEGORIES.items():
        total = hits = dt_ = dh = 0
        for d in days:
            c = d["categories"].get(key)
            if not c or c.get("target_pct") is None:
                continue
            p = c["dir"][:1]  # 偏/震 → 用分數重判更穩
            bull = cat["threshold_bullish"] * d["scale"]
            p = _pred3(c["score"], bull, -bull)
            t = c["target_pct"]
            total += 1
            hits += (p == _dir3(t, FLAT_BAND))
            if p != "平":
                dt_ += 1
                dh += ((p == "漲") == (t > 0))
        print(f"{cat['label']:<16}{total:>5}"
              f"{_fmt_pct(hits/total if total else None):>11}"
              f"{_fmt_pct(dh/dt_ if dt_ else None):>10}"
              f"{_fmt_pct(dt_/total if total else None):>8}")


def main():
    with open(BF_PATH, encoding="utf-8") as fp:
        data = json.load(fp)
    days = data["days"]
    split = int(len(days) * TRAIN_RATIO)
    train, val = days[:split], days[split:]
    print(f"樣本 {data['n_days']} 天（{data['start']} → {data['end']}）；"
          f"train {len(train)} / val {len(val)}（切點 {days[split]['date']}）\n")

    report_current(days)
    report_factor_ic(days)
    report_collinearity(days)
    report_variants(days, train, val)
    report_zscore(days, days[split]["date"])
    report_threshold_sweep(train, val)
    report_confidence(days)
    report_categories(days)


if __name__ == "__main__":
    main()
