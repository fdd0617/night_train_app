"""核心推荐引擎单元测试（无网络依赖）"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from night_train_app.models import TrainSegment, TripPlan
from night_train_app.services.recommendation import (
    _time_to_minutes,
    _night_ratio,
    _arrives_morning,
    _make_direct_plan,
    _make_transfer_plan,
    _date_diff,
    score_trip,
)


def _make_seg(
    train_no="Z1",
    from_station="北京",
    to_station="上海",
    depart_time="22:00",
    arrive_time="06:00",
    duration_minutes=480,
    has_sleeper=True,
    depart_date="2026-05-01",
    arrive_date="2026-05-02",
) -> TrainSegment:
    return TrainSegment(
        train_no=train_no,
        from_station=from_station,
        to_station=to_station,
        from_station_code="BJP",
        to_station_code="SHH",
        depart_time=depart_time,
        arrive_time=arrive_time,
        duration_minutes=duration_minutes,
        train_type="直特",
        has_sleeper=has_sleeper,
        depart_date=depart_date,
        arrive_date=arrive_date,
    )


class TestTimeUtils(unittest.TestCase):
    def test_time_to_minutes(self):
        self.assertEqual(_time_to_minutes("00:00"), 0)
        self.assertEqual(_time_to_minutes("01:30"), 90)
        self.assertEqual(_time_to_minutes("23:59"), 23 * 60 + 59)

    def test_night_ratio_full_night(self):
        # 22:00 出发，8h → 06:00 到达：全程处于夜间
        ratio = _night_ratio("22:00", 480)
        self.assertGreater(ratio, 0.95)

    def test_night_ratio_zero(self):
        # 10:00 出发，4h → 14:00：完全不在夜间
        ratio = _night_ratio("10:00", 240)
        self.assertAlmostEqual(ratio, 0.0, places=2)

    def test_night_ratio_partial(self):
        # 20:00 出发，4h → 00:00：约一半在夜间
        ratio = _night_ratio("20:00", 240)
        self.assertGreater(ratio, 0.0)
        self.assertLessEqual(ratio, 1.0)

    def test_arrives_morning_yes(self):
        self.assertTrue(_arrives_morning("07:30"))

    def test_arrives_morning_no(self):
        self.assertFalse(_arrives_morning("11:00"))
        self.assertFalse(_arrives_morning("05:00"))


class TestDateDiff(unittest.TestCase):
    def test_same_day(self):
        self.assertEqual(_date_diff("2026-05-01", "2026-05-01"), 0)

    def test_one_day(self):
        self.assertEqual(_date_diff("2026-05-01", "2026-05-02"), 1)

    def test_multi_day(self):
        self.assertEqual(_date_diff("2026-05-01", "2026-05-05"), 4)


class TestDirectPlan(unittest.TestCase):
    def test_basic_night_train(self):
        seg = _make_seg(depart_time="22:00", arrive_time="06:00", duration_minutes=480)
        plan = _make_direct_plan(seg)
        self.assertTrue(plan.is_direct)
        self.assertEqual(plan.total_minutes, 480)
        self.assertGreater(plan.night_ratio, 0.5)
        self.assertTrue(plan.arrives_morning)
        self.assertTrue(plan.has_sleeper)
        self.assertGreater(plan.score, 0)
        self.assertGreater(len(plan.reasons), 0)

    def test_daytime_train(self):
        seg = _make_seg(depart_time="09:00", arrive_time="13:00", duration_minutes=240,
                        has_sleeper=False, arrive_date="2026-05-01")
        plan = _make_direct_plan(seg)
        self.assertAlmostEqual(plan.night_ratio, 0.0, places=2)
        self.assertFalse(plan.arrives_morning)


class TestTransferPlan(unittest.TestCase):
    def test_valid_transfer(self):
        seg1 = _make_seg(
            train_no="Z1", from_station="北京", to_station="郑州",
            depart_time="22:00", arrive_time="03:00", duration_minutes=300,
            arrive_date="2026-05-02",
        )
        seg2 = _make_seg(
            train_no="K1", from_station="郑州", to_station="武汉",
            depart_time="06:30", arrive_time="10:00", duration_minutes=210,
            depart_date="2026-05-02", arrive_date="2026-05-02",
        )
        plan = _make_transfer_plan(seg1, seg2)
        self.assertIsNotNone(plan)
        self.assertFalse(plan.is_direct)
        self.assertEqual(plan.transfer_station, "郑州")

    def test_too_short_wait(self):
        # 仅10分钟换乘，不合法
        seg1 = _make_seg(
            train_no="Z1", arrive_time="10:00", duration_minutes=120,
            arrive_date="2026-05-01",
        )
        seg2 = _make_seg(
            train_no="Z2", depart_time="10:10", duration_minutes=120,
            depart_date="2026-05-01",
        )
        plan = _make_transfer_plan(seg1, seg2)
        self.assertIsNone(plan)

    def test_too_long_wait(self):
        # 超过8小时等候，不合法
        seg1 = _make_seg(
            train_no="Z1", arrive_time="06:00", duration_minutes=300,
            arrive_date="2026-05-02",
        )
        seg2 = _make_seg(
            train_no="Z2", depart_time="18:00", duration_minutes=300,
            depart_date="2026-05-02",
        )
        plan = _make_transfer_plan(seg1, seg2)
        self.assertIsNone(plan)


class TestScoreOrdering(unittest.TestCase):
    def test_night_sleeper_beats_day(self):
        night_seg = _make_seg(depart_time="22:00", arrive_time="06:00", duration_minutes=480)
        day_seg   = _make_seg(depart_time="09:00", arrive_time="13:00", duration_minutes=240,
                               has_sleeper=False, arrive_date="2026-05-01")
        night_plan = _make_direct_plan(night_seg)
        day_plan   = _make_direct_plan(day_seg)
        self.assertGreater(night_plan.score, day_plan.score)


if __name__ == "__main__":
    unittest.main(verbosity=2)
