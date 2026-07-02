"""規則引擎：原始資料 → 各因子標準化分數 → 加權總分 → 方向分類。

輸出格式固定，未來要換成 ML 只需替換本層、保持回傳結構不變：
    {"direction", "total_score", "factors": [{name, value, base, weight, contribution, note}]}
"""
import config


def _clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def _pct_factor(quote, full_pct):
    """漲跌幅型因子：回傳 (base[-1,1], 顯示值)。"""
    if quote is None:
        return None, None
    base = _clamp(quote["pct"] / full_pct)
    return base, f'{quote["pct"]:+.2f}%'


def _vix_factor(quote):
    """VIX：只貢獻負分。越高（恐慌）越扣分。"""
    if quote is None:
        return None, None
    n = config.NORMALIZERS
    over = quote["last"] - n["vix_base"]
    base = -_clamp(max(over, 0) / n["vix_range"], 0, 1)
    return base, f'{quote["last"]:.1f}'


def _usdtwd_factor(quote):
    """台幣：USDTWD 下跌=台幣升值=利多（外資進場訊號），故取負號。"""
    if quote is None:
        return None, None
    base = _clamp(-quote["pct"] / config.NORMALIZERS["usdtwd_full_pct"])
    return base, f'{quote["pct"]:+.2f}%'


def _foreign_buy_factor(data):
    if data is None:
        return None, None
    base = _clamp(data["net_yi"] / config.NORMALIZERS["foreign_buy_full_yi"])
    return base, f'{data["net_yi"]:+.1f} 億'


def _foreign_futures_factor(data):
    if data is None:
        return None, None
    base = _clamp(data["change"] / config.NORMALIZERS["foreign_futures_full"])
    return base, f'淨{data["net"]:+d} 口 (Δ{data["change"]:+d})'


def _night_factor(data):
    """台指期夜盤漲跌幅型因子。"""
    if data is None:
        return None, None
    base = _clamp(data["change_pct"] / config.NORMALIZERS["night_full_pct"])
    return base, f'{data["change_pct"]:+.2f}% (夜盤{data["night_close"]:.0f})'


def _margin_factor(data):
    """反向：融資餘額增加(散戶追高/過熱) → 負分；減少 → 正分。"""
    if data is None:
        return None, None
    base = _clamp(-data["change_pct"] / config.NORMALIZERS["margin_full_pct"])
    return base, f'餘額{data["balance_yi"]:.0f}億 ({data["change_pct"]:+.2f}%)'


def _dxy_factor(quote):
    """美元指數：走強對原物料價格通常是逆風，故取負號。"""
    if quote is None:
        return None, None
    base = _clamp(-quote["pct"] / config.NORMALIZERS["dxy_full_pct"])
    return base, f'{quote["pct"]:+.2f}%'


def _tnx_inv_factor(quote):
    """殖利率反向版：走升對高股息股/債券是壓力（債券替代效應），故取負號。
    與 _pct_factor 算出的「tnx」正向版是同一份原始資料，服務不同類別的相反語意。"""
    if quote is None:
        return None, None
    base = _clamp(-quote["pct"] / config.NORMALIZERS["tnx_full_pct"])
    return base, f'{quote["pct"]:+.2f}%'


def _vix_bond_factor(quote):
    """VIX 避險版：恐慌升溫資金轉向公債避險，故取正號（與股票類別的 VIX 因子方向相反）。"""
    if quote is None:
        return None, None
    n = config.NORMALIZERS
    over = quote["last"] - n["vix_base"]
    base = _clamp(max(over, 0) / n["vix_range"], 0, 1)
    return base, f'{quote["last"]:.1f}'


# 因子名稱 → (中文標籤, 計算函式)
_FACTOR_FUNCS = {
    "night_futures": ("台指期夜盤", lambda d: _night_factor(d["night_futures"])),
    "sox": ("費半 SOX",
            lambda d: _pct_factor(d["sox"], config.NORMALIZERS["sox_full_pct"])),
    "tsm_adr": ("台積電 ADR",
                lambda d: _pct_factor(d["tsm_adr"], config.NORMALIZERS["tsm_adr_full_pct"])),
    "nasdaq": ("那斯達克",
               lambda d: _pct_factor(d["nasdaq"], config.NORMALIZERS["nasdaq_full_pct"])),
    "foreign_buy": ("外資買賣超", lambda d: _foreign_buy_factor(d["foreign_buy"])),
    "foreign_futures": ("外資期貨", lambda d: _foreign_futures_factor(d["foreign_futures"])),
    "usdtwd": ("台幣匯率", lambda d: _usdtwd_factor(d["usdtwd"])),
    "vix": ("VIX 恐慌", lambda d: _vix_factor(d["vix"])),
    "margin": ("融資餘額(反向)", lambda d: _margin_factor(d["margin"])),
    "xlf": ("美股金融類股",
            lambda d: _pct_factor(d["xlf"], config.NORMALIZERS["xlf_full_pct"])),
    "tnx": ("美債10年殖利率",
            lambda d: _pct_factor(d["tnx"], config.NORMALIZERS["tnx_full_pct"])),
    "oil": ("WTI原油",
            lambda d: _pct_factor(d["oil"], config.NORMALIZERS["oil_full_pct"])),
    "copper": ("銅期貨",
               lambda d: _pct_factor(d["copper"], config.NORMALIZERS["copper_full_pct"])),
    "dxy": ("美元指數", lambda d: _dxy_factor(d["dxy"])),
    "bdry": ("航運指數(BDI代理)",
             lambda d: _pct_factor(d["bdry"], config.NORMALIZERS["bdry_full_pct"])),
    "tnx_inv": ("美債10年殖利率(債券效應)", lambda d: _tnx_inv_factor(d["tnx"])),
    "tlt": ("美國20年期公債ETF",
            lambda d: _pct_factor(d["tlt"], config.NORMALIZERS["tlt_full_pct"])),
    "vix_bond": ("VIX 恐慌(避險效應)", lambda d: _vix_bond_factor(d["vix"])),
}


def _strength_tier(base):
    """依標準化分數(|base|∈[0,1])判斷這次數值離滿格強度多遠。"""
    a = abs(base)
    if a >= 0.8:
        return "力道非常強"
    if a >= 0.5:
        return "力道明顯"
    if a >= 0.25:
        return "力道溫和"
    if a > 0.05:
        return "力道輕微"
    return "幾乎中性"


def _factor_analysis(key, base):
    """依這次實際數值動態生成一句解讀，而非固定說明文字。"""
    info = config.FACTOR_INFO.get(key, {})
    note = info.get("pos_note") if base >= 0 else info.get("neg_note")
    tier = _strength_tier(base)
    if abs(base) <= 0.05 or not note:
        return tier
    return f"{tier}，{note}"


def _evaluate_core(raw, factor_keys, weights, threshold_bullish, threshold_bearish,
                   threshold_scale=1.0):
    """評分核心：因子清單 + 各自權重 + 門檻 → 完整預測 dict。
    大盤(evaluate)與各類別(evaluate_category)共用此核心，只是餵不同的因子組合。
    """
    factors = []
    total = 0.0
    for name in factor_keys:
        label, fn = _FACTOR_FUNCS[name]
        base, value = fn(raw)
        weight = weights[name]
        if base is None:
            factors.append({"key": name, "name": label, "value": "N/A",
                            "base": None, "weight": weight,
                            "contribution": 0.0, "note": "資料缺漏，未計入"})
            continue
        contribution = base * weight
        total += contribution
        factors.append({"key": name, "name": label, "value": value,
                        "base": round(base, 2), "weight": weight,
                        "contribution": round(contribution, 2), "note": "",
                        "analysis": _factor_analysis(name, base)})

    bull = threshold_bullish * threshold_scale
    bear = threshold_bearish * threshold_scale
    if total >= bull:
        direction = "偏多 📈"
    elif total <= bear:
        direction = "偏空 📉"
    else:
        direction = "震盪 ➡️"

    attribution = _attribution(factors)
    reasoning = _reasoning(direction, attribution, total, threshold_scale, threshold_bullish)
    confidence = _confidence(total, direction, bull)
    plain_summary = _plain_summary(direction, attribution)

    return {"direction": direction, "total_score": round(total, 2),
            "factors": factors, "threshold_scale": threshold_scale,
            "thresholds": (round(bull, 1), round(bear, 1)),
            "attribution": attribution, "reasoning": reasoning,
            "confidence": confidence, "plain_summary": plain_summary}


def evaluate(raw, threshold_scale=1.0):
    """大盤預測：吃 data_fetch.fetch_all() 的結果，回傳預測 dict。

    threshold_scale：事件日可傳 >1 放大門檻，使分類更保守（見 events.py）。
    """
    return _evaluate_core(raw, list(config.WEIGHTS.keys()), config.WEIGHTS,
                          config.THRESHOLD_BULLISH, config.THRESHOLD_BEARISH,
                          threshold_scale)


def evaluate_category(raw, category_key, threshold_scale=1.0):
    """科技股/金融股/傳產等細分類別預測，見 config.CATEGORIES。"""
    cat = config.CATEGORIES[category_key]
    result = _evaluate_core(raw, cat["factors"], cat["weights"],
                            cat["threshold_bullish"], cat["threshold_bearish"],
                            threshold_scale)
    result["label"] = cat["label"]
    return result


# ── 歸因分析：把總分拆回各因子的多空力道 ──────────────────────
_NOISE = 0.05  # 貢獻絕對值低於此視為中性，不列入主導因子


def _attribution(factors):
    """回傳 {bull_force, bear_force, push(偏多排序), drag(偏空排序), neutral}。"""
    scored = [f for f in factors if f["base"] is not None]
    push = sorted([f for f in scored if f["contribution"] > _NOISE],
                  key=lambda f: -f["contribution"])
    drag = sorted([f for f in scored if f["contribution"] < -_NOISE],
                  key=lambda f: f["contribution"])
    neutral = [f for f in scored if abs(f["contribution"]) <= _NOISE]
    return {
        "bull_force": round(sum(f["contribution"] for f in push), 2),
        "bear_force": round(sum(f["contribution"] for f in drag), 2),
        "push": push, "drag": drag, "neutral": neutral,
    }


def _names(items, n=3):
    return "、".join(f["name"] for f in items[:n])


def _reasoning(direction, attr, total, scale, base_bull):
    """自動生成「為何是這個結論」的理由句。base_bull：未經事件日放大的原始偏多門檻。"""
    push, drag = attr["push"], attr["drag"]
    bf, df = attr["bull_force"], attr["bear_force"]

    if "偏多" in direction:
        s = f"主由「{_names(push)}」推升（合計 {bf:+.1f}）"
        s += (f"；「{_names(drag, 2)}」形成拖累（{df:+.1f}），但不足以扭轉方向。"
              if drag else "，且無明顯拖累因子。")
    elif "偏空" in direction:
        s = f"主由「{_names(drag)}」壓低（合計 {df:+.1f}）"
        s += (f"；「{_names(push, 2)}」提供支撐（{bf:+.1f}），但不足以扭轉方向。"
              if push else "，且無明顯支撐因子。")
    else:  # 震盪
        # 若分數本可定方向、僅因事件日門檻提高而轉觀望，特別點明
        if scale > 1.0 and abs(total) >= base_bull:
            side = "偏多" if total > 0 else "偏空"
            s = (f"總分 {total:+.1f} 原達{side}標準，但今日為事件日、門檻提高，"
                 f"轉為觀望。主要力道來自「{_names(push if total>0 else drag)}」。")
        elif push and drag:
            s = (f"多空力道接近（推升 {bf:+.1f}、拖累 {df:+.1f}）；"
                 f"「{push[0]['name']}」偏多與「{drag[0]['name']}」偏空相互抵銷，方向不明。")
        else:
            s = f"訊號偏弱（推升 {bf:+.1f}、拖累 {df:+.1f}），方向不明。"
    return s


def _confidence(total, direction, ref_threshold):
    """訊號強度 → 信心程度（給新手的直覺指標）。
    用「總分 ÷ 該類別自己的門檻」的比例判斷，而非絕對分數——
    這樣大盤(門檻4.0)和金融股(門檻2.2)這種量級不同的類別才能公平比較信心程度。
    """
    if "震盪" in direction:
        return {"label": "方向不明", "dots": "○○○○○",
                "note": "多空力道相當，建議觀望"}
    ratio = abs(total) / abs(ref_threshold) if ref_threshold else 1.0
    if ratio >= 2.0:
        lvl, dots = "很高", "●●●●●"
    elif ratio >= 1.5:
        lvl, dots = "高", "●●●●○"
    elif ratio >= 1.25:
        lvl, dots = "中等", "●●●○○"
    else:
        lvl, dots = "偏低", "●●○○○"
    return {"label": lvl, "dots": dots, "note": ""}


def _nick(factor):
    return config.FACTOR_INFO.get(factor["key"], {}).get("nick", factor["name"])


def _plain_summary(direction, attr):
    """完全口語的一段話，不熟股市也看得懂。"""
    push, drag = attr["push"], attr["drag"]

    def nicks(items, n=2):
        return "、".join(_nick(f) for f in items[:n]) if items else ""

    if "偏多" in direction:
        s = f"昨晚{nicks(push)}表現強勢，通常會帶動今天台股偏向上漲。"
        if drag:
            s += f"雖然{nicks(drag)}帶來一些反向壓力，但力道不足以扭轉方向。"
    elif "偏空" in direction:
        s = f"昨晚{nicks(drag)}表現疲弱，可能拖累今天台股偏向下跌。"
        if push:
            s += f"雖然{nicks(push)}提供一些支撐，但力道不足以扭轉方向。"
    else:
        s = "今天偏多與偏空的力道差不多，方向不明確，建議先觀望，不宜追高或殺低。"
    return s
