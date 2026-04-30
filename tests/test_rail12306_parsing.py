"""rail12306_client 解析逻辑单元测试（不发出真实网络请求）"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from night_train_app.adapters.rail12306_client import (
    _parse_duration,
    _calc_arrive_date,
    _has_sleeper,
    _get_train_type,
)


class TestParseDuration(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_parse_duration("13:30"), 13 * 60 + 30)

    def test_zero_minutes(self):
        self.assertEqual(_parse_duration("00:00"), 0)

    def test_hours_only(self):
        self.assertEqual(_parse_duration("05:00"), 5 * 60)

    def test_with_one_day(self):
        self.assertEqual(_parse_duration("1天13:30"), 1440 + 13 * 60 + 30)

    def test_with_two_days(self):
        self.assertEqual(_parse_duration("2天06:15"), 2 * 1440 + 6 * 60 + 15)


class TestCalcArriveDate(unittest.TestCase):
    def test_same_day(self):
        # 09:00 出发 + 5 小时 → 当天到达
        self.assertEqual(
            _calc_arrive_date("2026-05-01", "09:00", "14:00", 5 * 60),
            "2026-05-01",
        )

    def test_next_day(self):
        # 22:00 出发 + 8 小时 → 次日到达
        self.assertEqual(
            _calc_arrive_date("2026-05-01", "22:00", "06:00", 8 * 60),
            "2026-05-02",
        )

    def test_two_days_later(self):
        # 22:00 + 30 小时 → 第三天
        self.assertEqual(
            _calc_arrive_date("2026-05-01", "22:00", "04:00", 30 * 60),
            "2026-05-03",
        )

    def test_month_boundary(self):
        # 跨月：4-30 出发 + 跨日 → 5-1
        self.assertEqual(
            _calc_arrive_date("2026-04-30", "23:00", "07:00", 8 * 60),
            "2026-05-01",
        )


class TestHasSleeper(unittest.TestCase):
    def _row(self, train_no: str, idx21="", idx23="", idx28="") -> list[str]:
        """构造一条最少 35 字段的伪 12306 行数据。"""
        row = [""] * 35
        row[3] = train_no
        row[21] = idx21
        row[23] = idx23
        row[28] = idx28
        return row

    def test_z_train_always_sleeper(self):
        self.assertTrue(_has_sleeper(self._row("Z2")))

    def test_t_train_always_sleeper(self):
        self.assertTrue(_has_sleeper(self._row("T123")))

    def test_k_train_always_sleeper(self):
        self.assertTrue(_has_sleeper(self._row("K1058")))

    def test_g_train_no_sleeper_field(self):
        # 高铁 + 卧铺余票字段全空 → 无卧铺
        self.assertFalse(_has_sleeper(self._row("G1", idx21="", idx23="", idx28="")))

    def test_g_train_with_sleeper_ticket(self):
        # 高铁 + 软卧（idx23）有余票 → 有卧铺（如夕发朝至动卧）
        self.assertTrue(_has_sleeper(self._row("G555", idx23="3")))

    def test_d_train_with_sleeper_ticket(self):
        # 动车 + 动卧（idx21）有余票 → 有卧铺
        self.assertTrue(_has_sleeper(self._row("D101", idx21="有")))

    def test_g_train_sleeper_no_ticket(self):
        # 卧铺字段是 "无"/"--"/"0" 视为无票
        for v in ("无", "--", "0", ""):
            self.assertFalse(
                _has_sleeper(self._row("G1", idx21=v, idx23=v, idx28=v)),
                msg=f"value={v!r}",
            )

    def test_short_row_does_not_crash(self):
        # 字段不足时不能抛异常
        self.assertFalse(_has_sleeper(["only", "two", "fields"]))


class TestGetTrainType(unittest.TestCase):
    def test_known_prefixes(self):
        self.assertEqual(_get_train_type("G1"), "高铁")
        self.assertEqual(_get_train_type("D101"), "动车")
        self.assertEqual(_get_train_type("Z2"), "直特")
        self.assertEqual(_get_train_type("T123"), "特快")
        self.assertEqual(_get_train_type("K1058"), "快速")
        self.assertEqual(_get_train_type("C2585"), "城际")

    def test_unknown_prefix_returns_default(self):
        self.assertEqual(_get_train_type("1234"), "普通")
        self.assertEqual(_get_train_type(""), "普通")


if __name__ == "__main__":
    unittest.main()
