"""呈現層：白話結論優先，數據明細降到進階區。不熟股市也能看懂。"""
import os
import json
import datetime as dt

import config

BASE = os.path.dirname(__file__)
REPORTS_DIR = os.path.join(BASE, "reports")
DATA_DIR = os.path.join(BASE, "data")
W = 50  # 版面寬度


def _info(key, field):
    return config.FACTOR_INFO.get(key, {}).get(field, "")


def _stars(contribution):
    """以星數表示影響強度。"""
    a = abs(contribution)
    if a >= 2:
        return "★★★"
    if a >= 1:
        return "★★☆"
    if a > 0.05:
        return "★☆☆"
    return "－"


# ─────────────────────────── 終端機輸出 ───────────────────────────
def print_report(result):
    today = dt.date.today().isoformat()
    print("\n" + "═" * W)
    print(f"  台股盤前趨勢預估　{today}")
    print("═" * W)

    # 【今天的預估】白話優先
    print("\n【今天的預估】")
    print(f"  方向：{result['direction']}")
    conf = result.get("confidence", {})
    note = f"（{conf['note']}）" if conf.get("note") else ""
    print(f"  信心程度：{conf.get('dots', '')} {conf.get('label', '')}{note}")
    for ev in result.get("events", []):
        print(f"  ⚠️ 今天是{ev['type']}：{ev['note']}（預估趨保守）")
    print(f"\n  白話解釋：")
    for line in _wrap(result.get("plain_summary", ""), W - 6):
        print(f"    {line}")

    # 【影響今天的因素】帶白話
    attr = result.get("attribution", {})
    print("\n" + "─" * W)
    print("【影響今天的因素】")
    if attr.get("push"):
        print("\n  ▲ 偏向上漲的因素")
        for f in attr["push"]:
            _print_factor(f, "利多")
    if attr.get("drag"):
        print("\n  ▼ 偏向下跌的因素")
        for f in attr["drag"]:
            _print_factor(f, "利空")
    if attr.get("neutral"):
        print("\n  ・ 影響不大")
        for f in attr["neutral"]:
            print(f"    {_info(f['key'], 'nick') or f['name']}：{f['value']}")

    # 【數據明細】進階
    print("\n" + "─" * W)
    print("【數據明細（進階）】")
    bull, bear = result.get("thresholds", (4.0, -4.0))
    print(f'  偏多力道 {attr.get("bull_force", 0):+.2f}　｜　'
          f'偏空力道 {attr.get("bear_force", 0):+.2f}')
    print(f'  總分 {result["total_score"]:+.2f}　'
          f'（多≥{bull:+.1f} / 空≤{bear:+.1f} / 其餘震盪）')
    print(f'  技術理由：{result.get("reasoning", "")}')

    # 【細分類別】科技股/金融股/傳產，精簡呈現（完整因子明細在網頁看）
    for key, r in result.get("categories", {}).items():
        print("\n" + "─" * W)
        print(f'【{r.get("label", key)}】')
        conf = r.get("confidence", {})
        print(f'  方向：{r["direction"]}　信心：{conf.get("dots","")} {conf.get("label","")}')
        print(f'  {r.get("plain_summary","")}')
        attr = r.get("attribution", {})
        if attr.get("push"):
            print(f'  ▲ 偏多：{_names_str(attr["push"])}')
        if attr.get("drag"):
            print(f'  ▼ 偏空：{_names_str(attr["drag"])}')

    print("\n" + "═" * W + "\n")


def _names_str(items):
    return "、".join(_info(f["key"], "nick") or f["name"] for f in items)


def _print_factor(f, tag):
    nick = _info(f["key"], "nick") or f["name"]
    print(f'    {nick}　{f["value"]}　→ {tag} {_stars(f["contribution"])}')
    why = _info(f["key"], "why")
    if why:
        print(f'       └ {why}')
    if f.get("analysis"):
        print(f'       └ 解讀：{f["analysis"]}')


def _wrap(text, width):
    """簡單中文換行（每 width 字斷行）。"""
    return [text[i:i + width] for i in range(0, len(text), width)] or [""]


# ─────────────────────────── Markdown 報告 ───────────────────────────
def save_report(result):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    today = dt.date.today().isoformat()
    path = os.path.join(REPORTS_DIR, f"{today}.md")
    attr = result.get("attribution", {})
    conf = result.get("confidence", {})
    bull, bear = result.get("thresholds", (4.0, -4.0))

    L = [f"# 台股盤前趨勢預估　{today}", ""]
    L += ["## 今天的預估", "",
          f"### {result['direction']}", "",
          f"**信心程度：{conf.get('dots','')} {conf.get('label','')}**"
          + (f"（{conf['note']}）" if conf.get("note") else ""), ""]
    for ev in result.get("events", []):
        L.append(f"> ⚠️ 今天是 **{ev['type']}**：{ev['note']}（預估趨保守）")
    L += ["", f"> {result.get('plain_summary','')}", ""]

    L += ["## 影響今天的因素", ""]
    if attr.get("push"):
        L += ["**▲ 偏向上漲的因素**", ""]
        L += [_md_factor(f, "利多") for f in attr["push"]]
        L.append("")
    if attr.get("drag"):
        L += ["**▼ 偏向下跌的因素**", ""]
        L += [_md_factor(f, "利空") for f in attr["drag"]]
        L.append("")
    if attr.get("neutral"):
        names = "、".join(f"{_info(f['key'],'nick') or f['name']}（{f['value']}）"
                         for f in attr["neutral"])
        L += [f"**・影響不大**：{names}", ""]

    L += ["## 數據明細（進階）", "",
          f"偏多力道 **{attr.get('bull_force',0):+.2f}**｜"
          f"偏空力道 **{attr.get('bear_force',0):+.2f}**｜"
          f"總分 **{result['total_score']:+.2f}**"
          f"（門檻 多≥{bull:+.1f} / 空≤{bear:+.1f}）", "",
          "| 因子 | 數值 | 權重 | 貢獻 |", "|---|---|---|---|"]
    for f in result["factors"]:
        n = f"（{f['note']}）" if f["note"] else ""
        L.append(f"| {f['name']} | {f['value']}{n} | "
                 f"{f['weight']} | {f['contribution']:+.2f} |")
    L += ["", f"技術理由：{result.get('reasoning','')}", ""]

    for key, r in result.get("categories", {}).items():
        r_attr = r.get("attribution", {})
        r_conf = r.get("confidence", {})
        L += [f"## {r.get('label', key)}", "",
              f"**{r['direction']}**（總分 {r['total_score']:+.2f}，"
              f"信心 {r_conf.get('dots','')} {r_conf.get('label','')}）", "",
              f"> {r.get('plain_summary','')}", ""]
        if r_attr.get("push"):
            L += ["**▲ 偏多**", ""] + [_md_factor(f, "利多") for f in r_attr["push"]] + [""]
        if r_attr.get("drag"):
            L += ["**▼ 偏空**", ""] + [_md_factor(f, "利空") for f in r_attr["drag"]] + [""]
        if r_attr.get("neutral"):
            names = "、".join(f"{_info(f['key'],'nick') or f['name']}（{f['value']}）"
                             for f in r_attr["neutral"])
            L += [f"**・影響不大**：{names}", ""]

    L += ["---",
          "_實際結果（隔日填寫）：加權指數收盤 ____ 點，漲跌 ____%　"
          "命中：☐ 是 ☐ 否_", ""]

    with open(path, "w", encoding="utf-8") as fp:
        fp.write("\n".join(L))
    print(f"報告已存檔：{path}")
    return path


def _md_factor(f, tag):
    nick = _info(f["key"], "nick") or f["name"]
    why = _info(f["key"], "why")
    url = _info(f["key"], "source_url")
    line = f"- **{nick}**　{f['value']}　→ {tag} {_stars(f['contribution'])}"
    if url:
        line += f"　[查看原始資料 ↗]({url})"
    if why:
        line += f"\n  - {why}"
    if f.get("analysis"):
        line += f"\n  - 解讀：{f['analysis']}"
    return line


# ─────────────────────────── 結構化資料（供網頁/回測）───────────────────────────
def save_data(result, date_str=None):
    """把當日結果存成 JSON，作為歷史與回測的資料來源。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    date_str = date_str or dt.date.today().isoformat()
    path = os.path.join(DATA_DIR, f"{date_str}.json")
    payload = dict(result)
    payload["date"] = date_str
    payload["generated_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    payload.setdefault("actual", None)  # 隔日實際漲跌，供回測填寫
    # 保留 backtest 已填的實際結果，避免重跑 main.py 覆蓋
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fp:
            old = json.load(fp)
        for k in ("actual", "actual_pct", "hit"):
            if old.get(k) is not None:
                payload[k] = old[k]
        # 各類別（科技股/金融股/傳產）也要同步保留已回測的實際結果
        old_cats = old.get("categories", {})
        for ck, cr in payload.get("categories", {}).items():
            old_cr = old_cats.get(ck, {})
            for k in ("actual", "actual_pct", "hit"):
                if old_cr.get(k) is not None:
                    cr[k] = old_cr[k]
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    return path
