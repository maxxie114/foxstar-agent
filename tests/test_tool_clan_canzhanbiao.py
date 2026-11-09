"""Synthetic attendance workbook and date parser tests."""
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from foxstar_bot.tool_clan import _canzhan_sheet_dates, parse_canzhanbiao  # noqa: E402



def test_sheet_dates():
    today = date(2026, 11, 4)
    # regular season sheet
    assert _canzhan_sheet_dates("10.28-10.31", today) == (date(2026, 10, 28), date(2026, 10, 31))
    # early-season sheet from this year
    assert _canzhan_sheet_dates("9.16-9.19", today) == (date(2026, 9, 16), date(2026, 9, 19))
    # cross-year season: December battle rolls into January
    jan = date(2027, 1, 10)
    assert _canzhan_sheet_dates("12.28-1.2", jan) == (date(2026, 12, 28), date(2027, 1, 2))
    # a December sheet seen in January belongs to last year
    assert _canzhan_sheet_dates("12.28-1.2", date(2027, 2, 1)) == (date(2026, 12, 28), date(2027, 1, 2))
    # future-dated sheet is refused (pre-posted next week)
    assert _canzhan_sheet_dates("11.8-11.12", today) is None
    # non-weekly sheets are ignored
    for name in ("职业表", "领地", "Sheet1", "10.28", ""):
        assert _canzhan_sheet_dates(name, today) is None
    print("test_sheet_dates OK")


def _build_xlsx(path: Path):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "职业表"
    ws.append(["测试条目"])
    weekly = wb.create_sheet("10.28-10.31")
    # header dates deliberately stale (copy-paste leftover in real files)
    weekly.append(["", "帮会成员", "职业", "10月21日是否接龙", "10月24日是否参加帮会", "备注"])
    weekly.append(["1", "测试成员甲", "沧澜", "是", "是", ""])
    weekly.append(["2", "测试成员乙", "沧澜", "已接请假", "", ""])
    weekly.append(["3", "测试成员丙", "沧澜", "是", "", "排替补"])
    weekly.append(["4", "测试成员丁", "沧澜", "", "", ""])
    # future battle sheet: jielong happened, battle tonight
    future = wb.create_sheet("11.3-11.7")
    future.append(["", "帮会成员", "职业", "11月3日是否接龙", "11月7日是否参加帮会", "备注"])
    future.append(["1", "测试成员甲", "沧澜", "是", "是", ""])
    wb.save(path)


def test_synthetic_workbook():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "示例帮会参战表.xlsx"
        _build_xlsx(p)
        r = parse_canzhanbiao(p, today=date(2026, 11, 4))
        # roster from the LATEST sheet (11.3-11.7), dated at its battle day
        assert r["latest_sheet"] == "11.3-11.7"
        assert r["roster"] == [["测试成员甲", "沧澜", "11-07-2026", "帮众名单", "参与", ""]]
        recs = {(x[0], x[2], x[3]): x[4] for x in r["records"]}
        # jielong day: signed / leave / no-show-not-recorded
        assert recs[("测试成员甲", "10-28-2026", "接龙")] == "参与"
        assert recs[("测试成员乙", "10-28-2026", "接龙")] == "请假"
        assert ("测试成员丁", "10-28-2026", "接龙") not in recs
        # battle day: attend / leave / sub / absent
        assert recs[("测试成员甲", "10-31-2026", "帮战")] == "参与"
        assert recs[("测试成员乙", "10-31-2026", "帮战")] == "请假"
        assert recs[("测试成员丙", "10-31-2026", "帮战")] == "替补"
        assert recs[("测试成员丁", "10-31-2026", "帮战")] == "缺勤"
        # future battle (11-07 > today): jielong recorded, battle skipped
        assert recs[("测试成员甲", "11-03-2026", "接龙")] == "参与"
        assert ("测试成员甲", "11-07-2026", "帮战") not in recs
    print("test_synthetic_workbook OK")
