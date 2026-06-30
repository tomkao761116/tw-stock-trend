"""財經行事曆事件層：判斷某交易日是否撞到重大事件。

事件日不改各因子分數，而是讓 main.py 放大分類門檻（要求更強訊號才喊方向），
並在報告示警。理由：重大數據/會議公布前，市場常觀望，美股強弱未必反映到當日。

維護方式：把已知日期填進 MANUAL_EVENTS（date 用該事件「影響的台股交易日」）。
台指期結算日（每月第三個週三）會自動計算，不需手填。
"""
import datetime as dt

# ── 手動維護清單 ───────────────────────────────────────────────
# date 格式 "YYYY-MM-DD"。請自行查證並更新（範例僅示意，日期未必正確）。
MANUAL_EVENTS = [
    # {"date": "2026-07-29", "type": "FOMC", "note": "Fed 利率決議（隔日凌晨公布）"},
    # {"date": "2026-07-15", "type": "CPI",  "note": "美國 6 月 CPI"},
    # {"date": "2026-07-17", "type": "法說",  "note": "台積電法說會"},
    # {"date": "2026-07-04", "type": "非農",  "note": "美國非農就業"},
]


def _third_wednesday(year, month):
    """台指期/選擇權每月結算日 = 第三個週三。"""
    d = dt.date(year, month, 1)
    # 找到當月第一個週三（weekday 2 = Wed）
    first_wed = d + dt.timedelta(days=(2 - d.weekday()) % 7)
    return first_wed + dt.timedelta(days=14)


def _auto_events(date):
    """規則型事件（可由日期直接算出）。"""
    events = []
    if date == _third_wednesday(date.year, date.month):
        events.append({"date": date.isoformat(), "type": "結算日",
                       "note": "台指期/選擇權結算，籌碼易異常"})
    return events


def events_on(date=None):
    """回傳該日所有事件 list（手動 + 自動）。date 為 datetime.date，預設今天。"""
    if date is None:
        date = dt.date.today()
    iso = date.isoformat()
    manual = [e for e in MANUAL_EVENTS if e["date"] == iso]
    return manual + _auto_events(date)
