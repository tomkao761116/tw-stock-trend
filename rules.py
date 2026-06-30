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


def _margin_factor(data):
    """反向：融資餘額增加(散戶追高/過熱) → 負分；減少 → 正分。"""
    if data is None:
        return None, None
    base = _clamp(-data["change_pct"] / config.NORMALIZERS["margin_full_pct"])
    return base, f'餘額{data["balance_yi"]:.0f}億 ({data["change_pct"]:+.2f}%)'


# 因子名稱 → (中文標籤, 計算函式)
_FACTOR_FUNCS = {
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
}


def evaluate(raw):
    """主入口：吃 data_fetch.fetch_all() 的結果，回傳預測 dict。"""
    factors = []
    total = 0.0
    for name, (label, fn) in _FACTOR_FUNCS.items():
        base, value = fn(raw)
        weight = config.WEIGHTS[name]
        if base is None:
            factors.append({"name": label, "value": "N/A", "base": None,
                            "weight": weight, "contribution": 0.0,
                            "note": "資料缺漏，未計入"})
            continue
        contribution = base * weight
        total += contribution
        factors.append({"name": label, "value": value, "base": round(base, 2),
                        "weight": weight, "contribution": round(contribution, 2),
                        "note": ""})

    if total >= config.THRESHOLD_BULLISH:
        direction = "偏多 📈"
    elif total <= config.THRESHOLD_BEARISH:
        direction = "偏空 📉"
    else:
        direction = "震盪 ➡️"

    return {"direction": direction, "total_score": round(total, 2),
            "factors": factors}
