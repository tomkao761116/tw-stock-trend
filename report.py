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
    print(f'  ➜ 今日方向預估：{result["direction"]}')
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
    lines += ["", "---",
              "_實際結果（隔日填寫）：加權指數收盤 ____ 點，漲跌 ____%　"
              "命中：☐ 是 ☐ 否_", ""]
    with open(path, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines))
    print(f"報告已存檔：{path}")
    return path
