"""準確度改善研究（不改 config，只產生證據）。跑：python research_accuracy.py

在 604 天回填上以 70/30 train/validation 實測幾個假設，回報哪些真能改善 out-of-sample。
研究性質——結論寫進 decisions.md，實際調參另案。
"""
import json
import os

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

import config

BF = os.path.join(os.path.dirname(__file__), "backfill", "backfill.json")
FLAT = 0.4
FACTORS = list(config.WEIGHTS.keys())


def load():
    days = json.load(open(BF, encoding="utf-8"))["days"]
    split = int(len(days) * 0.7)
    return days, days[:split], days[split:]


def dir3(p, band=FLAT):
    return 1 if p > band else (-1 if p < -band else 0)


def linear_pred(d, bull):
    s = d["score"]
    t = bull * d["scale"]
    return 1 if s >= t else (-1 if s <= -t else 0)


def hit_rate(days, predfn, tkey="twii_pct"):
    tot = hit = 0
    for d in days:
        t = d["targets"].get(tkey)
        if t is None:
            continue
        tot += 1
        hit += (predfn(d) == dir3(t))
    return hit / tot if tot else None, tot


def purity(days, predfn, tkey="twii_pct"):
    ok = tot = 0
    for d in days:
        t = d["targets"].get(tkey)
        if t is None:
            continue
        p = predfn(d)
        if p == 0:
            continue
        tot += 1
        ok += ((p > 0) == (t > 0))
    return (ok / tot if tot else None), tot


def hdr(t):
    print("\n" + "=" * 66 + f"\n{t}\n" + "=" * 66)


# ── 0. 基準 ────────────────────────────────────────────────────
def baseline(train, val):
    hdr("0. 基準（現行線性規則，門檻 ±3）")
    for name, ds in (("train", train), ("val", val)):
        h, n = hit_rate(ds, lambda d: linear_pred(d, config.THRESHOLD_BULLISH))
        p, pn = purity(ds, lambda d: linear_pred(d, config.THRESHOLD_BULLISH))
        print(f"  {name}: 3分類命中 {h*100:.1f}% (n={n})　方向純度 {p*100:.1f}% (n={pn})")


# ── 1. 誤差分解：錯在哪 ────────────────────────────────────────
def error_decomp(days):
    hdr("1. 誤差分解（全樣本，看命中/失誤集中在哪類預測）")
    cells = {}
    for d in days:
        t = d["targets"].get("twii_pct")
        if t is None:
            continue
        p = linear_pred(d, config.THRESHOLD_BULLISH)
        a = dir3(t)
        cells.setdefault(p, {"n": 0, "hit": 0, "adir": {}})
        cells[p]["n"] += 1
        cells[p]["hit"] += (p == a)
        cells[p]["adir"][a] = cells[p]["adir"].get(a, 0) + 1
    names = {1: "預測漲", -1: "預測跌", 0: "預測平/震盪"}
    for p in (1, -1, 0):
        c = cells.get(p)
        if not c:
            continue
        adir = {(-1 if k < 0 else 1 if k > 0 else 0): v for k, v in c["adir"].items()}
        print(f"  {names[p]}: n={c['n']:>3} 命中 {c['hit']/c['n']*100:4.0f}%  "
              f"（實際 漲{adir.get(1,0)}/平{adir.get(0,0)}/跌{adir.get(-1,0)}）")
    print("  → 若『預測平』命中率特別低，代表 flat 帶或門檻設定是主要失分點。")


# ── 2. 邏輯迴歸 vs 線性規則 ────────────────────────────────────
def logistic_bench(train, val):
    hdr("2. 邏輯迴歸（多空二分類）vs 現行線性規則 — out-of-sample")

    def build(ds):
        X, y, keep = [], [], []
        for d in ds:
            t = d["targets"].get("twii_pct")
            if t is None or abs(t) <= FLAT:
                continue  # 只訓練有明確方向的日子
            row = [d["factors"].get(k) if d["factors"].get(k) is not None else 0.0
                   for k in FACTORS]
            X.append(row)
            y.append(1 if t > 0 else 0)
            keep.append(d)
        return np.array(X), np.array(y), keep

    Xtr, ytr, _ = build(train)
    Xva, yva, keep = build(val)
    sc = StandardScaler().fit(Xtr)
    clf = LogisticRegression(max_iter=1000, C=0.5).fit(sc.transform(Xtr), ytr)

    # val 上：邏輯迴歸方向純度 vs 現行規則方向純度（同一批「有方向」日）
    pred = clf.predict(sc.transform(Xva))
    lr_acc = (pred == yva).mean()
    # 現行規則在同一批日子的純度
    ok = tot = 0
    for d in keep:
        p = linear_pred(d, config.THRESHOLD_BULLISH)
        if p == 0:
            continue
        tot += 1
        ok += ((p > 0) == (d["targets"]["twii_pct"] > 0))
    rule_p = ok / tot if tot else 0
    print(f"  邏輯迴歸 val 方向準確 {lr_acc*100:.1f}%（全喊方向，n={len(yva)}）")
    print(f"  現行規則 val 方向純度 {rule_p*100:.1f}%（僅過門檻，n={tot}）")
    coef = sorted(zip(FACTORS, clf.coef_[0]), key=lambda x: -abs(x[1]))
    print("  迴歸權重（標準化後，絕對值排序）：")
    for k, w in coef:
        print(f"    {config.FACTOR_INFO.get(k,{}).get('nick',k):<14} {w:+.2f}")


# ── 3. 多空不對稱 ──────────────────────────────────────────────
def asymmetry(days):
    hdr("3. 多空不對稱（喊漲 vs 喊跌，各自純度）")
    for side, lab in ((1, "喊漲"), (-1, "喊跌")):
        ok = tot = 0
        for d in days:
            t = d["targets"].get("twii_pct")
            if t is None:
                continue
            p = linear_pred(d, config.THRESHOLD_BULLISH)
            if p != side:
                continue
            tot += 1
            ok += ((p > 0) == (t > 0))
        print(f"  {lab}: 純度 {ok/tot*100:.1f}% (n={tot})" if tot else f"  {lab}: n=0")
    print("  → 若兩者差距大，偏多/偏空門檻可設不對稱。")


# ── 4. 波動 regime 依賴 ────────────────────────────────────────
def regime(days):
    hdr("4. VIX regime 依賴（低波動 vs 高波動日的命中率）")
    vals = [(d, d["raws"].get("vix")) for d in days]
    vals = [(d, v) for d, v in vals if v is not None]
    med = np.median([v for _, v in vals])
    for lab, cond in (("低VIX (<%.0f)" % med, lambda v: v < med),
                      ("高VIX (>=%.0f)" % med, lambda v: v >= med)):
        tot = hit = 0
        for d, v in vals:
            if not cond(v):
                continue
            t = d["targets"].get("twii_pct")
            if t is None:
                continue
            tot += 1
            hit += (linear_pred(d, config.THRESHOLD_BULLISH) == dir3(t))
        print(f"  {lab}: 命中 {hit/tot*100:.1f}% (n={tot})" if tot else lab)
    print("  → 若高低波動命中率差距大，門檻可依 VIX 動態調整。")


# ── 5. 跳空回補（盤中 = 跳空的反向？）──────────────────────────
def gap_fade(days):
    hdr("5. 跳空回補傾向（大跳空日的盤中反向強度）")
    pairs = [(d["targets"].get("gap_pct"), d["targets"].get("intraday_pct"))
             for d in days]
    pairs = [(g, i) for g, i in pairs if g is not None and i is not None]
    g = np.array([x[0] for x in pairs])
    i = np.array([x[1] for x in pairs])
    print(f"  全體 corr(跳空, 盤中) = {np.corrcoef(g, i)[0,1]:+.2f}")
    big = np.abs(g) >= 1.0
    if big.sum() > 10:
        print(f"  大跳空日(|gap|>=1%, n={big.sum()}): corr = "
              f"{np.corrcoef(g[big], i[big])[0,1]:+.2f}　"
              f"平均盤中/跳空比 = {(i[big]/g[big]).mean():+.2f}")
    print("  → 負相關代表『開高走低/開低走高』回補；可設計『跳空後盤中反向』的展望。")


def main():
    days, train, val = load()
    print(f"樣本 {len(days)} 天，train {len(train)} / val {len(val)}")
    baseline(train, val)
    error_decomp(days)
    logistic_bench(train, val)
    asymmetry(days)
    regime(days)
    gap_fade(days)


if __name__ == "__main__":
    main()
