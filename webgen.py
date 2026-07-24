"""靜態網頁產生器：讀 data/*.json → 產出 docs/index.html。

手機友善、單一檔案（CSS 內嵌、無外部相依）。
台股慣例：紅 = 漲（偏多）、綠 = 跌（偏空）。
"""
import os
import json
import glob
import html
import datetime as dt

import config

BASE = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE, "data")
DOCS_DIR = os.path.join(BASE, "docs")

DIR_CLASS = {"偏多": "bull", "偏空": "bear", "震盪": "flat"}


def _load_all():
    """讀所有每日 JSON，依日期新→舊排序。"""
    items = []
    for path in glob.glob(os.path.join(DATA_DIR, "*.json")):
        with open(path, encoding="utf-8") as fp:
            items.append(json.load(fp))
    items.sort(key=lambda r: r.get("date", ""), reverse=True)
    return items


def _dir_class(direction):
    for key, cls in DIR_CLASS.items():
        if key in direction:
            return cls
    return "flat"


HIST_PAGE_SIZE = 20     # 歷史表每頁列數（超過才出現分頁控制）
RECENT_WINDOW = 30       # 命中率統計視窗（交易日）
REGIME_ALERT_HITS = 0.45  # 近期命中率低於此 → 顯示劇烈震盪脈絡提示
# 613 天回測「可交易命中」基準（含平盤帶，見 analyze.py／decisions.md 2026-07-21）。
# 近期小樣本（尤其開盤在小跳空盤）常大幅偏離此值，故摘要並列基準供對照、防誤讀。
BASELINE_OPEN = 0.70
BASELINE_CLOSE = 0.66


def _perf_stats(records, window=RECENT_WINDOW):
    """統計近 window 個已回測日的命中率。records 為已抽出的每日結果 dict list
    （大盤傳 items，類別傳各自的 cr），依日期新→舊。回傳 {close, open, intraday}，
    各為 (命中數, 總數)；休市/未回測日自動排除。"""
    out = {"close": [0, 0], "open": [0, 0], "intraday": [0, 0]}
    seen = 0
    for r in records:
        if r is None or r.get("no_trading"):
            continue
        if r.get("hit") is None and r.get("open_hit") is None:
            continue  # 尚未回測（如今日）
        seen += 1
        if seen > window:
            break
        for key, hk in (("close", "hit"), ("open", "open_hit"),
                        ("intraday", "intraday_hit")):
            if r.get(hk) is not None:
                out[key][0] += bool(r[hk])
                out[key][1] += 1
    return out


def _rate(pair):
    h, n = pair
    return h / n if n else None


def _perf_summary_html(records, window=RECENT_WINDOW, is_market=False):
    """績效摘要區塊（A2+A3）：開盤方向與收盤各自的近期命中率＋誠實註記。
    無足夠回測資料時回空字串。is_market：只有大盤附具體 613 天基準數字
    （BASELINE_* 是大盤值，類別各自不同，故類別只給通用防誤讀說明）。"""
    s = _perf_stats(records, window)
    op, cl = s["open"], s["close"]
    if op[1] == 0 and cl[1] == 0:
        return ""
    parts = []
    if op[1]:
        parts.append(f'開盤方向 <b>{op[0]}/{op[1]}</b>（{_rate(op)*100:.0f}%）')
    if cl[1]:
        parts.append(f'收盤方向 <b>{cl[0]}/{cl[1]}</b>（{_rate(cl)*100:.0f}%）')
    n = max(op[1], cl[1])
    if is_market:
        note = (f'613 天歷史基準：開盤約 {BASELINE_OPEN*100:.0f}%、'
                f'收盤約 {BASELINE_CLOSE*100:.0f}%。近期若明顯偏低，多為極端震盪或'
                f'「平開後盤中大動」的小跳空盤所致，屬短期現象。')
    else:
        note = '近期為小樣本、波動大，僅供參考；此類別長期基準見大盤分頁說明。'
    return (f'<div class="perf"><div class="perf-nums">近{n}個交易日：'
            f'{"　｜　".join(parts)}</div>'
            f'<div class="perf-note">{note}方向性預估、非穩賺，'
            f'歷史命中僅供信任校準、不代表未來。</div></div>')


def _info(key, field):
    return config.FACTOR_INFO.get(key, {}).get(field, "")


def _stars(c):
    a = abs(c)
    return "★★★" if a >= 2 else "★★☆" if a >= 1 else "★☆☆" if a > 0.05 else "－"


def _gen_at(r):
    """卡片日期行後接「當日更新時間」。"""
    ts = r.get("generated_at")
    return f'　·　更新 {html.escape(ts)}' if ts else ""


def _factor_rows(items, tag):
    rows = []
    for f in items:
        nick = html.escape(_info(f["key"], "nick") or f["name"])
        why = html.escape(_info(f["key"], "why"))
        val = html.escape(str(f["value"]))
        url = _info(f["key"], "source_url")
        link_html = (f'<a class="srclink" href="{html.escape(url)}" '
                    f'target="_blank" rel="noopener">查看原始資料 ↗</a>') if url else ""
        analysis_html = (f'<div class="analysis">解讀：{html.escape(f["analysis"])}</div>'
                         if f.get("analysis") else "")
        rows.append(
            f'<div class="factor"><div class="frow">'
            f'<span class="fname">{nick}</span>'
            f'<span class="fval">{val}</span>'
            f'<span class="stars">{_stars(f["contribution"])}</span></div>'
            f'<div class="why">{why}</div>'
            f'{analysis_html}'
            f'{link_html}</div>')
    return "\n".join(rows)


def _actual_mark(r, key):
    """回測已填實際結果時，附在預測旁邊的小字（如「實際 開高 +0.8% ✓」）。"""
    a = r.get(key)
    return f'<span class="actualmark">實際 {html.escape(str(a))}</span>' if a else ""


_CHART_NOISE = 0.005  # 貢獻絕對值低於此不畫（畫出來也是看不見的一條線）


def _diverging_chart_html(factors):
    """因子影響力發散長條圖：長度＝|貢獻|、右紅=推升、左綠=拖累，依強度降冪排序。

    取代星等作為主視覺——星等只分三級（★★★ 涵蓋貢獻 2 以上），同級內的強度差
    完全看不出來；長條圖能一眼分辨誰主導。純 CSS 寬度百分比，零外部相依；
    方向由左右位置編碼（不只靠顏色），符合無障礙要求。"""
    scored = [f for f in factors if f.get("base") is not None
              and abs(f.get("contribution", 0)) > _CHART_NOISE]
    if not scored:
        return ""
    scored.sort(key=lambda f: -abs(f["contribution"]))
    mx = max(abs(f["contribution"]) for f in scored)
    rows = []
    for f in scored:
        c = f["contribution"]
        nick = html.escape(_info(f["key"], "nick") or f["name"])
        side = "pos" if c > 0 else "neg"
        bar = f'<i class="db {side}" style="width:{abs(c) / mx * 100:.1f}%"></i>'
        rows.append(
            f'<div class="drow"><span class="dn">{nick}</span>'
            f'<span class="dt"><span class="dh l">{bar if c < 0 else ""}</span>'
            f'<span class="dx"></span>'
            f'<span class="dh r">{bar if c > 0 else ""}</span></span>'
            f'<span class="dv {side}">{c:+.2f}</span></div>')
    return (f'<div class="dchart">{"".join(rows)}</div>'
            f'<p class="dleg">← 偏空　偏多 →　長度＝影響力大小，依強度排序</p>')


def _headline_html(r):
    """卡片頭：有 open_call（大盤與各類別）拆成開盤方向＋盤中展望兩行；
    舊資料無 open_call 時回退單一方向。開盤方向是強訊號、盤中展望是弱訊號，
    附小字提醒可靠度差異（大盤盤中約 7 成、類別多更弱，故用定性描述不寫死數字）。"""
    oc = r.get("open_call")
    if not oc:
        return f'<div class="direction">{html.escape(r["direction"])}</div>'
    ic = r.get("intraday_call", {})
    return (
        f'<div class="predlabel">開盤方向</div>'
        f'<div class="direction">{html.escape(oc["direction"])}'
        f'{_actual_mark(r, "open_actual")}</div>'
        f'<div class="intraday">盤中展望：'
        f'<span class="{ic.get("cls","flat")}">{html.escape(ic.get("direction",""))}</span>'
        f'{_actual_mark(r, "intraday_actual")}</div>'
        f'<div class="callnote">開盤方向為主要依據（歷史較可靠）；'
        f'盤中展望為較弱訊號、僅供參考，訊號不足時顯示「方向不明」</div>')


def _full_card(title, r, events=None, regime_note=""):
    """完整卡片渲染：大盤與各類別分頁共用同一大小/結構，只差標題與資料來源。
    regime_note：近期命中率偏低時的脈絡提示（C2），只在首頁最新大盤卡片傳入。"""
    cls = (r["open_call"]["cls"] if r.get("open_call")
           else _dir_class(r["direction"]))
    conf = r.get("confidence", {})
    attr = r.get("attribution", {})
    ev_html = "".join(
        f'<div class="event">⚠️ 今天是{html.escape(e["type"])}：'
        f'{html.escape(e["note"])}（預估趨保守）</div>' for e in (events or []))
    if regime_note:
        ev_html += regime_note

    # 缺重要因子（權重 ≥ 2）時顯眼警告——缺失會系統性低估總分強度，
    # 使用者需知道當日預估可信度打折（2026-07-10 缺 SOX 的教訓）
    missing_big = [f for f in r["factors"]
                   if f.get("note") and f.get("weight", 0) >= 2.0]
    if missing_big:
        names = "、".join(html.escape(_info(f["key"], "nick") or f["name"])
                         for f in missing_big)
        ev_html += (f'<div class="event">⚠️ 本日「{names}」資料缺漏未計入，'
                    f'總分被低估、預估可信度打折</div>')

    # 訊號分歧軟提示（僅大盤有 signals_conflict）：夜盤與美股方向相反，
    # 歷史上這類日子命中率明顯較低——定性提醒，不改變方向判斷
    if r.get("signals_conflict"):
        ev_html += ('<div class="event">⚠️ 台指期夜盤與美股方向分歧，'
                    '此類日子歷史命中率較低，當日預估可信度打折</div>')

    push = attr.get("push", [])
    drag = attr.get("drag", [])
    neutral = attr.get("neutral", [])
    neutral_html = ""
    if neutral:
        names = "、".join(html.escape(_info(f["key"], "nick") or f["name"])
                         for f in neutral)
        neutral_html = f'<p class="neutral">影響不大：{names}</p>'

    # 進階數據表
    table_rows = "".join(
        f'<tr><td>{html.escape(f["name"])}</td><td>{html.escape(str(f["value"]))}</td>'
        f'<td>{f["weight"]}</td><td>{f["contribution"]:+.2f}</td></tr>'
        for f in r["factors"])
    bull, bear = r.get("thresholds", [4.0, -4.0])

    return f'''
  <div class="card today {cls}">
    <div class="date">{html.escape(title)}</div>
    {_headline_html(r)}
    <div class="conf">信心 <span class="dots">{conf.get("dots","")}</span> {html.escape(conf.get("label",""))}</div>
    {ev_html}
    <p class="summary">{html.escape(r.get("plain_summary",""))}</p>

    {_diverging_chart_html(r["factors"])}
    <button class="det-btn" onclick="var d=this.nextElementSibling;
      var open=d.hasAttribute('hidden');
      if(open){{d.removeAttribute('hidden');this.textContent='－ 收合因子細節';}}
      else{{d.setAttribute('hidden','');this.textContent='＋ 顯示因子細節';}}"
    >＋ 顯示因子細節</button>
    <div class="fdetail" hidden>
      <h3 class="up">▲ 偏向上漲的因素</h3>
      {_factor_rows(push, "利多") or '<p class="none">（無）</p>'}
      <h3 class="down">▼ 偏向下跌的因素</h3>
      {_factor_rows(drag, "利空") or '<p class="none">（無）</p>'}
      {neutral_html}
    </div>

    <details>
      <summary>數據明細（進階）</summary>
      <p class="force">偏多力道 {attr.get("bull_force",0):+.2f}｜偏空力道 {attr.get("bear_force",0):+.2f}｜
      總分 {r.get("total_score",0):+.2f}（多≥{bull:+.1f} / 空≤{bear:+.1f}）</p>
      <table><tr><th>因子</th><th>數值</th><th>權重</th><th>貢獻</th></tr>{table_rows}</table>
      <p class="tech">{html.escape(r.get("reasoning",""))}</p>
    </details>
  </div>'''


# 類別顯示順序：與 config.CATEGORIES 定義順序一致（tech/financial/traditional）
_CATEGORY_ORDER = ["tech", "financial", "traditional"]


def _hist_cell(actual):
    """歷史表實際欄：依「方向」上色，與「預估」欄同一標準（紅=漲/開高、綠=跌/開低、
    黃=平盤，台股慣例）。命中與否由文字裡的 ✓/✗ 表示，不影響顏色——顏色一律代表方向。
    休市/未回測顯示 —。"""
    if not actual:
        return '<td>—</td>'
    txt = html.escape(str(actual))
    if "開高" in txt or "漲" in txt:
        cls = "bull"
    elif "開低" in txt or "跌" in txt:
        cls = "bear"
    elif "平" in txt:      # 平開 / 平
        cls = "flat"
    else:                  # 休市等
        cls = ""
    return f'<td class="{cls}">{txt}</td>'


def _history_table_html(items, extractor, tab_id):
    """通用歷史表：extractor(r) 回傳該日「這個分頁」的結果 dict（無資料回 None，跳過該列）。
    tab_id：連結要帶去的分頁錨點，讓點「查看」直接開到同一個分頁（大盤不需要錨點）。
    B1：實際欄改顯示「開盤」與「收盤」兩段結果，對齊卡片的兩段式預測；
    B2：移除「總分」欄（內部分數，對使用者無意義，移到單日進階明細）。"""
    anchor = "" if tab_id == "market" else f"#{tab_id}"
    rows = []
    for i, r in enumerate(items):
        cr = extractor(r)
        if cr is None:
            continue
        cls = _dir_class(cr["direction"])
        date = html.escape(r["date"])
        href = f"{date}.html{anchor}"
        # data-i：這一列是第幾筆（跳過無資料的日期後重新編號），供分頁 JS 使用
        rows.append(
            f'<tr data-i="{len(rows)}"><td><a href="{href}">{date}</a></td>'
            f'<td class="{cls}">{html.escape(cr["direction"])}</td>'
            f'{_hist_cell(cr.get("open_actual"))}'
            f'{_hist_cell(cr.get("actual"))}'
            f'<td><a class="view" href="{href}">查看 →</a></td></tr>')
    if not rows:
        return ""
    pager = ""
    if len(rows) > HIST_PAGE_SIZE:
        # 分頁在 client 端切換（靜態站無後端）；只是隱藏列、不減少下載量，
        # 但捲動長度才是實際痛點，且 gzip 後重量多年內都可接受。
        pager = ('<div class="pgbar"><button class="pg-prev" disabled>← 上一頁</button>'
                 '<span class="pg-label"></span>'
                 '<button class="pg-next">下一頁 →</button></div>')
    return f'''<table class="hist" data-paged="{HIST_PAGE_SIZE}">
      <tr><th>日期</th><th>預估</th><th>開盤</th><th>收盤</th><th></th></tr>
      {"".join(rows)}
    </table>{pager}'''


# 頂層分頁定義：(分頁id, 標籤, 類別key)。cat_key="__etf__" 是特殊標記，
# 代表這個分頁底下不是單一類別卡片，而是巢狀子分頁（見 _ETF_SUBTABS）。
_TAB_DEFS = [("market", "大盤", None)] + [
    (key, config.CATEGORIES[key]["label"], key) for key in _CATEGORY_ORDER
] + [("etf", "ETF", "__etf__")]

# ETF 分頁底下的子分頁：(子分頁id, 標籤, 類別key)。
# "growth"（成長型）不是獨立算出來的類別——它是既有 tech(科技股/半導體) 的別名，
# 直接借用同一份預測結果展示，避免跟科技股分頁算出兩份可能不一致的重複因子。
_ETF_SUBTABS = [
    ("dividend", config.CATEGORIES["dividend"]["label"], "dividend"),
    ("growth", "成長型", "tech"),
    ("bond", config.CATEGORIES["bond"]["label"], "bond"),
]
_ETF_ALIAS_NOTE = '<p class="alias-note">＊本分頁與「科技股/半導體」分頁共用同一份預測結果</p>'


def _tab_button(tab_id, label, active):
    cls = "tab-btn active" if active else "tab-btn"
    return f'<button class="{cls}" data-tab="{tab_id}">{html.escape(label)}</button>'


def _tab_panel(tab_id, active, inner_html):
    cls = "tab-panel active" if active else "tab-panel"
    return f'<div class="{cls}" id="tab-{tab_id}">{inner_html}</div>'


def _subtab_button(sub_id, label, active):
    cls = "subtab-btn active" if active else "subtab-btn"
    return f'<button class="{cls}" data-subtab="{sub_id}">{html.escape(label)}</button>'


def _subtab_panel(sub_id, active, inner_html):
    cls = "subtab-panel active" if active else "subtab-panel"
    return f'<div class="{cls}" id="subtab-{sub_id}">{inner_html}</div>'


def _category_panel(tab_id, label, cat_key, latest, items=None, note=""):
    """類別分頁內容（卡片 + 選填的歷史表），供頂層類別分頁與 ETF 子分頁共用——
    兩者結構相同，都是讀 latest["categories"][cat_key]。
    items=None（單日封存頁）→ 只顯示卡片；有給 items（首頁）→ 卡片後附這個類別的歷史表。
    """
    cr = latest.get("categories", {}).get(cat_key)
    if cr is None:
        return (f'<div class="card"><p class="none">'
               f'尚無{html.escape(label)}資料（此功能較新，舊資料未涵蓋）</p></div>')
    card_html = note + _full_card(label, cr, events=latest.get("events", []))
    if not items or len(items) <= 1:
        return card_html
    extractor = lambda r, k=cat_key: r.get("categories", {}).get(k)
    history_html = _history_table_html(items, extractor, tab_id)
    if not history_html:
        return card_html
    perf = _perf_summary_html([extractor(r) for r in items])
    hist_block = f'<div class="card"><h2>歷史紀錄</h2>{perf}{history_html}</div>'
    return card_html + hist_block


def _build_etf_subtabs(items):
    """ETF 分頁底下的子分頁：股息型/成長型(別名)/債券型，各自完整卡片 + 各自歷史表。"""
    latest = items[0]
    buttons, panels = [], []
    for i, (sub_id, label, cat_key) in enumerate(_ETF_SUBTABS):
        active = (i == 0)
        buttons.append(_subtab_button(sub_id, label, active))
        note = _ETF_ALIAS_NOTE if sub_id == "growth" else ""
        inner = _category_panel(f"etf-{sub_id}", label, cat_key, latest, items, note=note)
        panels.append(_subtab_panel(sub_id, active, inner))
    return f'<div class="subtabs">{"".join(buttons)}</div>{"".join(panels)}'


def _build_etf_day_subtabs(r):
    """ETF 分頁底下的子分頁（單日封存頁版，不含歷史表）。"""
    buttons, panels = [], []
    for i, (sub_id, label, cat_key) in enumerate(_ETF_SUBTABS):
        active = (i == 0)
        buttons.append(_subtab_button(sub_id, label, active))
        note = _ETF_ALIAS_NOTE if sub_id == "growth" else ""
        inner = _category_panel(f"etf-{sub_id}", label, cat_key, r, note=note)
        panels.append(_subtab_panel(sub_id, active, inner))
    return f'<div class="subtabs">{"".join(buttons)}</div>{"".join(panels)}'


def _regime_note(items):
    """C2：近期命中率偏低時的脈絡提示——管理連錯期間的信任，說明短期低迷屬正常。
    以最近 10 個已回測日的收盤命中率為準；樣本不足或命中正常則不顯示。"""
    stats = _perf_stats(items, window=10)
    close = stats["close"]
    if close[1] >= 6 and _rate(close) < REGIME_ALERT_HITS:
        return ('<div class="event">⚠️ 近期市場波動劇烈，短期命中率偏低——'
                '極端震盪期隔夜訊號本就較難反映當日走勢，屬正常現象，'
                '模型通常於震盪回穩後回歸。此期間預估請保守看待。</div>')
    return ""


def _build_tabs(items):
    """首頁分頁：大盤 + 各類別 + ETF(內有子分頁)，各自完整卡片 + 各自歷史表。"""
    latest = items[0]
    regime = _regime_note(items)
    buttons, panels = [], []
    for i, (tab_id, label, cat_key) in enumerate(_TAB_DEFS):
        active = (i == 0)
        buttons.append(_tab_button(tab_id, label, active))

        if cat_key == "__etf__":
            inner = _build_etf_subtabs(items)
        elif cat_key is None:
            card_html = _full_card(f'{latest["date"]} 盤前預估{_gen_at(latest)}',
                                   latest, events=latest.get("events", []),
                                   regime_note=regime)
            extractor = lambda r: r
            history_html = (_history_table_html(items, extractor, tab_id)
                            if len(items) > 1 else "")
            perf = _perf_summary_html(items, is_market=True) if history_html else ""
            inner = card_html + (f'<div class="card"><h2>歷史紀錄</h2>{perf}{history_html}</div>'
                                 if history_html else "")
        else:
            inner = _category_panel(tab_id, label, cat_key, latest, items)

        panels.append(_tab_panel(tab_id, active, inner))

    return f'<div class="tabs">{"".join(buttons)}</div>{"".join(panels)}'


def _build_day_tabs(r):
    """單日封存頁的分頁：大盤 + 各類別 + ETF(內有子分頁)，各自完整卡片（不含歷史表）。
    與首頁用同一套分頁元件，讓「點大盤看大盤、點分類看分類」的體驗前後一致。"""
    buttons, panels = [], []
    for i, (tab_id, label, cat_key) in enumerate(_TAB_DEFS):
        active = (i == 0)
        buttons.append(_tab_button(tab_id, label, active))

        if cat_key == "__etf__":
            inner = _build_etf_day_subtabs(r)
        elif cat_key is None:
            inner = _full_card(f'{r["date"]} 盤前預估{_gen_at(r)}', r, events=r.get("events", []))
        else:
            inner = _category_panel(tab_id, label, cat_key, r)

        panels.append(_tab_panel(tab_id, active, inner))

    return f'<div class="tabs">{"".join(buttons)}</div>{"".join(panels)}'


_TAB_SCRIPT = """
document.querySelectorAll('.tab-btn').forEach(function(btn) {
  btn.addEventListener('click', function() {
    document.querySelectorAll('.tab-btn').forEach(function(b){ b.classList.remove('active'); });
    document.querySelectorAll('.tab-panel').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
  });
});
document.querySelectorAll('.subtab-btn').forEach(function(btn) {
  btn.addEventListener('click', function() {
    document.querySelectorAll('.subtab-btn').forEach(function(b){ b.classList.remove('active'); });
    document.querySelectorAll('.subtab-panel').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    document.getElementById('subtab-' + btn.dataset.subtab).classList.add('active');
  });
});
// 歷史表分頁：每個分頁的表格各自獨立分頁（首頁有 7 張表）
document.querySelectorAll('table.hist[data-paged]').forEach(function(tbl) {
  var size = parseInt(tbl.dataset.paged, 10);
  var rows = tbl.querySelectorAll('tr[data-i]');
  var pages = Math.ceil(rows.length / size);
  if (pages < 2) return;
  var bar = tbl.nextElementSibling;
  if (!bar || !bar.classList.contains('pgbar')) return;
  var prev = bar.querySelector('.pg-prev');
  var next = bar.querySelector('.pg-next');
  var label = bar.querySelector('.pg-label');
  var page = 1;
  function render() {
    rows.forEach(function(tr) {
      var i = parseInt(tr.dataset.i, 10);
      tr.hidden = !(i >= (page - 1) * size && i < page * size);
    });
    label.textContent = '第 ' + page + ' / ' + pages + ' 頁';
    prev.disabled = (page === 1);
    next.disabled = (page === pages);
  }
  prev.addEventListener('click', function() { if (page > 1) { page--; render(); } });
  next.addEventListener('click', function() { if (page < pages) { page++; render(); } });
  render();
});
(function() {
  var hash = location.hash.replace('#', '');
  if (!hash) return;
  if (hash.indexOf('etf-') === 0) {
    var etfBtn = document.querySelector('.tab-btn[data-tab="etf"]');
    if (etfBtn) etfBtn.click();
    var subBtn = document.querySelector('.subtab-btn[data-subtab="' + hash.slice(4) + '"]');
    if (subBtn) subBtn.click();
  } else {
    var btn = document.querySelector('.tab-btn[data-tab="' + hash + '"]');
    if (btn) btn.click();
  }
})();
"""


CSS = """
:root{--bull:#e23636;--bear:#1ca672;--flat:#c79100;--bg:#f4f5f7;--card:#fff;--ink:#222;--sub:#888}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,"PingFang TC","Microsoft JhengHei",sans-serif;line-height:1.6}
.wrap{max-width:600px;margin:0 auto;padding:16px}
.card{background:var(--card);border-radius:14px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
.date{color:var(--sub);font-size:14px}
.direction{font-size:34px;font-weight:800;margin:4px 0}
.today.bull .direction{color:var(--bull)} .today.bear .direction{color:var(--bear)} .today.flat .direction{color:var(--flat)}
.conf{font-size:16px;color:#555;margin-bottom:8px}.dots{letter-spacing:2px}
.predlabel{color:var(--sub);font-size:13px;margin-top:4px}
.intraday{font-size:18px;font-weight:700;margin:2px 0 4px}
.intraday .bull{color:var(--bull)}.intraday .bear{color:var(--bear)}.intraday .flat{color:var(--flat)}
.callnote{color:var(--sub);font-size:12px;margin-bottom:6px}
.actualmark{font-size:13px;font-weight:400;color:#555;background:#f2f3f5;border-radius:6px;padding:2px 8px;margin-left:8px;white-space:nowrap}
.event{background:#fff4e5;border-left:4px solid var(--flat);padding:8px 10px;border-radius:6px;margin:8px 0;font-size:14px}
.summary{background:#f0f4ff;padding:12px;border-radius:8px;font-size:15px}
h3{font-size:15px;margin:16px 0 8px} h3.up{color:var(--bull)} h3.down{color:var(--bear)}
.factor{border-bottom:1px solid #eee;padding:8px 0}
.frow{display:flex;align-items:center;gap:8px}
.fname{font-weight:600;flex:1}.fval{color:#555;font-variant-numeric:tabular-nums}.stars{color:#f0a500;font-size:13px}
.why{color:var(--sub);font-size:13px;margin-top:2px}
.analysis{color:#444;font-size:13px;margin-top:4px;padding:6px 8px;background:#f7f7f5;border-radius:6px}
.srclink{display:inline-block;margin-top:6px;font-size:12px;color:#185fa5;text-decoration:none}
.srclink:hover{text-decoration:underline}
.neutral,.none{color:var(--sub);font-size:13px}
details{margin-top:14px;border-top:1px dashed #ddd;padding-top:10px}
summary{cursor:pointer;color:#555;font-size:14px}
.force{font-size:13px;color:#555}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
th,td{padding:6px;border-bottom:1px solid #eee;text-align:center}th{color:var(--sub);font-weight:600}
.tech{font-size:12px;color:var(--sub);margin-top:8px}
table .bull{color:var(--bull)} table .bear{color:var(--bear)} table .flat{color:var(--flat)}
.hist td:first-child{text-align:left}
.hist tr:hover td{background:#fafbfc}
.hist a{color:#185fa5;text-decoration:none} .hist a:hover{text-decoration:underline}
.view{font-size:12px;white-space:nowrap}
.backlink{display:inline-block;margin:0 0 12px;color:#185fa5;text-decoration:none;font-size:14px}
.backlink:hover{text-decoration:underline}
.disclaimer{text-align:center;color:var(--sub);font-size:12px;padding:8px 0 24px}
.tabs{display:flex;gap:6px;margin-bottom:14px;overflow-x:auto;padding-bottom:2px}
.tab-btn{flex:0 0 auto;padding:8px 14px;border:none;background:#e7e8ec;border-radius:8px;
  font-size:14px;color:#555;cursor:pointer;white-space:nowrap;font-family:inherit}
.tab-btn.active{background:#222;color:#fff}
.tab-panel{display:none}
.tab-panel.active{display:block}
.subtabs{display:flex;gap:6px;margin:0 0 14px;overflow-x:auto;padding-bottom:2px}
.subtab-btn{flex:0 0 auto;padding:6px 12px;border:none;background:#eff0f2;border-radius:7px;
  font-size:13px;color:#666;cursor:pointer;white-space:nowrap;font-family:inherit}
.subtab-btn.active{background:#555;color:#fff}
.subtab-panel{display:none}
.subtab-panel.active{display:block}
.alias-note{font-size:12px;color:var(--sub);font-style:italic;margin:0 0 8px}
.perf{background:#f0f4ff;border-radius:8px;padding:10px 12px;margin-bottom:12px}
.perf-nums{font-size:15px;color:#333}.perf-nums b{color:#185fa5}
.perf-note{font-size:12px;color:var(--sub);margin-top:4px}
.legend{font-size:12px;color:var(--sub);text-align:center;padding:4px 0;line-height:1.8}
.legend b{color:#555}
/* 因子影響力發散長條圖（主視覺，取代星等的粗略分級）*/
.dchart{margin:14px 0 4px}
.drow{display:flex;align-items:center;gap:8px;margin:4px 0}
.dn{flex:0 0 92px;font-size:13px;text-align:right;color:#333;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dt{flex:1;display:flex;align-items:center;height:16px}
.dh{flex:1;display:flex;height:100%}
.dh.l{justify-content:flex-end}.dh.r{justify-content:flex-start}
.dx{width:1px;flex:0 0 1px;background:#ccc;height:100%}
.db{display:block;height:11px;border-radius:2px;align-self:center}
.db.pos{background:var(--bull)}.db.neg{background:var(--bear)}
.dv{flex:0 0 48px;font-size:13px;text-align:right;font-variant-numeric:tabular-nums}
.dv.pos{color:var(--bull)}.dv.neg{color:var(--bear)}
.dleg{font-size:11.5px;color:var(--sub);text-align:center;margin:6px 0 0}
.det-btn{margin:10px 0 2px;min-height:44px;background:#e7e8ec;border:none;
  border-radius:8px;padding:8px 16px;font-size:13px;color:#555;cursor:pointer;
  font-family:inherit}
/* 歷史分頁 */
.pgbar{display:flex;gap:10px;align-items:center;justify-content:center;
  margin-top:12px;font-size:13px;color:var(--sub)}
.pgbar button{min-height:44px;min-width:64px;border:1px solid #dfe3ea;background:#fff;
  border-radius:8px;color:#185fa5;cursor:pointer;font-family:inherit;font-size:13px}
.pgbar button:disabled{color:#bbb;cursor:default}
"""


def _page(title, body, script=""):
    """共用頁面外殼。script：選填的頁尾 <script> 內容（分頁切換用）。"""
    updated = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    script_html = f'<script>{script}</script>' if script else ""
    return f'''<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <h1 style="font-size:20px;margin:8px 0">📊 台股盤前趨勢預估</h1>
{body}
  <div class="legend">
    <b>★</b> 影響強度（★★★ 強 / ★★☆ 中 / ★☆☆ 弱）
    <b>●</b> 信心程度（●●●●● 很高 → ●●○○○ 偏低）<br>
    紅＝偏多/上漲、綠＝偏空/下跌（台股慣例）
  </div>
  <div class="disclaimer">更新時間 {updated}　｜　本頁為機率性方向預估，僅供參考，非投資建議</div>
</div>
{script_html}
</body>
</html>'''


def _write(filename, content):
    path = os.path.join(DOCS_DIR, filename)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(content)
    return path


def build_site():
    items = _load_all()
    if not items:
        print("（data/ 無資料，先跑過 main.py 再產生網頁）")
        return None
    os.makedirs(DOCS_DIR, exist_ok=True)

    # 每日獨立頁面（可永久連結、單獨分享）：與首頁同一套分頁元件
    for r in items:
        body = f'  <a class="backlink" href="index.html">← 回首頁</a>\n{_build_day_tabs(r)}'
        _write(f'{r["date"]}.html', _page(f'台股盤前預估 {r["date"]}', body, script=_TAB_SCRIPT))

    # 首頁：分頁呈現，大盤 + 各類別各自完整卡片與歷史（預設顯示大盤）
    body = _build_tabs(items)
    path = _write("index.html", _page("台股盤前趨勢預估", body, script=_TAB_SCRIPT))
    print(f"網頁已產生：{path}（含 {len(items)} 個每日頁面）")
    return path


if __name__ == "__main__":
    build_site()
