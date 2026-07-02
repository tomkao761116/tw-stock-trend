"""盤前執行入口：python main.py

流程：擷取資料 → 規則引擎評分 → 印出並存檔報告。
"""
import sys

import config
import data_fetch
import events
import rules
import report
import webgen


def main():
    print("台股盤前趨勢預估　啟動中…\n")
    try:
        raw = data_fetch.fetch_all()
    except ImportError as e:
        print(f"\n缺少套件：{e}\n請先執行：pip install -r requirements.txt")
        sys.exit(1)

    valid = sum(1 for v in raw.values() if v is not None)
    if valid < config.MIN_VALID_FACTORS:
        print(f"\n❌ 只有 {valid} 個因子取得資料（門檻 {config.MIN_VALID_FACTORS}），"
              "研判是網路未連上或大規模擷取失敗。")
        print("為避免用殘缺資料覆蓋今天既有的正確預估，本次執行中止、不存檔、不更新網頁。")
        sys.exit(1)

    today_events = events.events_on()
    scale = config.THRESHOLD_EVENT_SCALE if today_events else 1.0
    result = rules.evaluate(raw, threshold_scale=scale)
    result["events"] = today_events
    report.print_report(result)
    report.save_report(result)
    report.save_data(result)
    webgen.build_site()

    skipped = [f["name"] for f in result["factors"] if f["note"]]
    if skipped:
        print(f"註：以下因子未計入（{'、'.join(skipped)}）。"
              "設定 FINMIND_TOKEN 可納入台股籌碼因子，提升準確度。")


if __name__ == "__main__":
    main()
