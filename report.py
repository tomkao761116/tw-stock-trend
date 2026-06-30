"""呈現層：把預測結果印到終端機，並存成 Markdown 報告供日後回測。"""
import os
import datetime as dt

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")


def _table_lines(result):
    lines = []
    lines.append(f'{"因子":<12}{"數值":<18}{"權重":>5}{"貢獻":>8}')
    lines.append("-" * 48)
    for f in result["factors"]:
        lines.append(f'{f["name"]:<12}{str(f["value"]):<18}'
                     f'{f["weight"]:>5}{f["contribution"]:>8.2f}'
                     + (f'  ({f["note"]})' if f["note"] else ""))
    return lines


def _bar(contribution, unit=0.5, char="█"):
    """以長條長度表示貢獻強度，每 unit 分一格。"""
    return char * max(1, round(abs(contribution) / unit))


def _attribution_lines(result):
    """歸因分析：多空力道對比 + 排序長條。"""
    attr = result.get("attribution")
    if not attr:
        return []
    lines = ["", "── 歸因分析 ──────────────────────────────────",
             f'  偏多力道 {attr["bull_force"]:+.2f}　｜　'
             f'偏空力道 {attr["bear_force"]:+.2f}　｜　'
             f'淨 {result["total_score"]:+.2f}']
    if attr["push"]:
        lines.append("  ▲ 推升（偏多）：")
        for f in attr["push"]:
            lines.append(f'      {f["name"]:<14}{f["contribution"]:>6.2f}  '
                         f'{_bar(f["contribution"])}')
    if attr["drag"]:
        lines.append("  ▼ 拖累（偏空）：")
        for f in attr["drag"]:
            lines.append(f'      {f["name"]:<14}{f["contribution"]:>6.2f}  '
                         f'{_bar(f["contribution"])}')
    if attr["neutral"]:
        names = "、".join(f["name"] for f in attr["neutral"])
        lines.append(f'  ・ 中性（影響微小）：{names}')
    return lines


def print_report(result):
    print("\n" + "=" * 48)
    print(f'  台股盤前趨勢預估　{dt.date.today().isoformat()}')
    print("=" * 48)
    for line in _table_lines(result):
        print(line)
    print("-" * 48)
    bull, bear = result.get("thresholds", (4.0, -4.0))
    print(f'  總分：{result["total_score"]:+.2f}'
          f'　（多≥{bull:+.1f} / 空≤{bear:+.1f} / 其餘震盪）')
    for ev in result.get("events", []):
        print(f'  ⚠️ 事件日：{ev["type"]} — {ev["note"]}')
    if result.get("events"):
        print(f'  （門檻已放大 {result["threshold_scale"]}×，預估趨保守）')
    for line in _attribution_lines(result):
        print(line)
    print("-" * 48)
    print(f'  ➜ 今日方向預估：{result["direction"]}')
    if result.get("reasoning"):
        print(f'  理由：{result["reasoning"]}')
    print("=" * 48 + "\n")


def save_report(result):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    today = dt.date.today().isoformat()
    path = os.path.join(REPORTS_DIR, f"{today}.md")
    bull, bear = result.get("thresholds", (4.0, -4.0))
    lines = [f"# 台股盤前趨勢預估　{today}", "",
             f"**今日方向預估：{result['direction']}**　"
             f"（總分 {result['total_score']:+.2f}，門檻 多≥{bull:+.1f}/空≤{bear:+.1f}）", ""]
    for ev in result.get("events", []):
        lines.append(f"> ⚠️ 事件日：**{ev['type']}** — {ev['note']}（門檻已放大）")
    if result.get("events"):
        lines.append("")
    lines += ["| 因子 | 數值 | 權重 | 貢獻 |", "|---|---|---|---|"]
    for f in result["factors"]:
        note = f"（{f['note']}）" if f["note"] else ""
        lines.append(f"| {f['name']} | {f['value']}{note} | "
                     f"{f['weight']} | {f['contribution']:+.2f} |")
    attr = result.get("attribution")
    if attr:
        lines += ["", "## 歸因分析", "",
                  f"偏多力道 **{attr['bull_force']:+.2f}**｜"
                  f"偏空力道 **{attr['bear_force']:+.2f}**｜"
                  f"淨 **{result['total_score']:+.2f}**", ""]
        if attr["push"]:
            lines.append("**▲ 推升（偏多）**："
                         + "、".join(f"{f['name']} {f['contribution']:+.2f}"
                                    for f in attr["push"]))
        if attr["drag"]:
            lines.append("**▼ 拖累（偏空）**："
                         + "、".join(f"{f['name']} {f['contribution']:+.2f}"
                                    for f in attr["drag"]))
        if attr["neutral"]:
            lines.append("**・中性**："
                         + "、".join(f["name"] for f in attr["neutral"]))
    if result.get("reasoning"):
        lines += ["", f"**結論理由**：{result['reasoning']}"]
    lines += ["", "---",
              "_實際結果（隔日填寫）：加權指數收盤 ____ 點，漲跌 ____%　"
              "命中：☐ 是 ☐ 否_", ""]
    with open(path, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines))
    print(f"報告已存檔：{path}")
    return path
