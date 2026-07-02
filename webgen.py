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


def _full_card(title, r, events=None):
    """完整卡片渲染：大盤與各類別分頁共用同一大小/結構，只差標題與資料來源。"""
    cls = _dir_class(r["direction"])
    conf = r.get("confidence", {})
    attr = r.get("attribution", {})
    ev_html = "".join(
        f'<div class="event">⚠️ 今天是{html.escape(e["type"])}：'
        f'{html.escape(e["note"])}（預估趨保守）</div>' for e in (events or []))

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
    <div class="direction">{html.escape(r["direction"])}</div>
    <div class="conf">信心 <span class="dots">{conf.get("dots","")}</span> {html.escape(conf.get("label",""))}</div>
    {ev_html}
    <p class="summary">{html.escape(r.get("plain_summary",""))}</p>

    <h3 class="up">▲ 偏向上漲的因素</h3>
    {_factor_rows(push, "利多") or '<p class="none">（無）</p>'}
    <h3 class="down">▼ 偏向下跌的因素</h3>
    {_factor_rows(drag, "利空") or '<p class="none">（無）</p>'}
    {neutral_html}

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


def _history_table_html(items, extractor, tab_id):
    """通用歷史表：extractor(r) 回傳該日「這個分頁」的結果 dict（無資料回 None，跳過該列）。
    tab_id：連結要帶去的分頁錨點，讓點「查看」直接開到同一個分頁（大盤不需要錨點）。"""
    anchor = "" if tab_id == "market" else f"#{tab_id}"
    rows = []
    for r in items:
        cr = extractor(r)
        if cr is None:
            continue
        cls = _dir_class(cr["direction"])
        actual = cr.get("actual")
        actual_txt = html.escape(str(actual)) if actual else "—"
        date = html.escape(r["date"])
        href = f"{date}.html{anchor}"
        rows.append(
            f'<tr><td><a href="{href}">{date}</a></td>'
            f'<td class="{cls}">{html.escape(cr["direction"])}</td>'
            f'<td>{cr.get("total_score",0):+.2f}</td>'
            f'<td>{actual_txt}</td>'
            f'<td><a class="view" href="{href}">查看 →</a></td></tr>')
    if not rows:
        return ""
    return f'''<table class="hist">
      <tr><th>日期</th><th>預估</th><th>總分</th><th>實際</th><th></th></tr>
      {"".join(rows)}
    </table>'''


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
    hist_block = f'<div class="card"><h2>歷史紀錄</h2>{history_html}</div>' if history_html else ""
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


def _build_tabs(items):
    """首頁分頁：大盤 + 各類別 + ETF(內有子分頁)，各自完整卡片 + 各自歷史表。"""
    latest = items[0]
    buttons, panels = [], []
    for i, (tab_id, label, cat_key) in enumerate(_TAB_DEFS):
        active = (i == 0)
        buttons.append(_tab_button(tab_id, label, active))

        if cat_key == "__etf__":
            inner = _build_etf_subtabs(items)
        elif cat_key is None:
            card_html = _full_card(f'{latest["date"]} 盤前預估{_gen_at(latest)}',
                                   latest, events=latest.get("events", []))
            extractor = lambda r: r
            history_html = (_history_table_html(items, extractor, tab_id)
                            if len(items) > 1 else "")
            inner = card_html + (f'<div class="card"><h2>歷史紀錄</h2>{history_html}</div>'
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
