"""Flask API 集成测试（无真实网络，Mock 12306 数据）"""
import sys
import os
import json
import unittest
from unittest.mock import patch, MagicMock
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from night_train_app.app import app
from night_train_app.models import TrainSegment, StationInfo


def _fake_resolve(name: str):
    mapping = {
        "北京": StationInfo(name="北京", code="BJP", pinyin="beijing", city="北京"),
        "上海": StationInfo(name="上海", code="SHH", pinyin="shanghai", city="上海"),
    }
    return mapping.get(name)


def _fake_query(from_code, to_code, date_str, **_):
    return [
        TrainSegment(
            train_no="Z2",
            from_station="北京",
            to_station="上海",
            from_station_code="BJP",
            to_station_code="SHH",
            depart_time="22:05",
            arrive_time="06:55",
            duration_minutes=530,
            train_type="直特",
            has_sleeper=True,
            depart_date=date_str,
            arrive_date=(date.fromisoformat(date_str) + timedelta(days=1)).isoformat(),
        )
    ]


class TestAPIValidation(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_missing_from(self):
        res = self.client.post("/api/recommend",
                               json={"to": "上海", "date": "2026-05-01"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("出发地", res.get_json()["error"])

    def test_missing_date(self):
        res = self.client.post("/api/recommend",
                               json={"from": "北京", "to": "上海"})
        self.assertEqual(res.status_code, 400)

    def test_past_date(self):
        past = (date.today() - timedelta(days=1)).isoformat()
        res = self.client.post("/api/recommend",
                               json={"from": "北京", "to": "上海", "date": past})
        self.assertEqual(res.status_code, 400)
        self.assertIn("今天", res.get_json()["error"])

    def test_too_far_date(self):
        far = (date.today() + timedelta(days=35)).isoformat()
        res = self.client.post("/api/recommend",
                               json={"from": "北京", "to": "上海", "date": far})
        self.assertEqual(res.status_code, 400)

    def test_invalid_date_format(self):
        res = self.client.post("/api/recommend",
                               json={"from": "北京", "to": "上海", "date": "not-a-date"})
        self.assertEqual(res.status_code, 400)

    @patch("night_train_app.services.recommendation.resolve_station", side_effect=_fake_resolve)
    @patch("night_train_app.services.recommendation.query_trains", side_effect=_fake_query)
    def test_successful_query(self, _mock_query, _mock_resolve):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        res = self.client.post("/api/recommend",
                               json={"from": "北京", "to": "上海", "date": tomorrow,
                                     "direct_only": True})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("plans", data)
        self.assertGreaterEqual(data["total"], 1)
        plan = data["plans"][0]
        self.assertIn("segments", plan)
        self.assertIn("reasons", plan)
        self.assertIn("night_ratio", plan)
        self.assertTrue(plan["has_sleeper"])

    @patch("night_train_app.services.recommendation.resolve_station",
           return_value=None)
    def test_unknown_station(self, _):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        res = self.client.post("/api/recommend",
                               json={"from": "火星市", "to": "月球站", "date": tomorrow})
        self.assertEqual(res.status_code, 400)

    def test_station_search(self):
        res = self.client.get("/api/stations/search?q=北京")
        # 无论是否成功加载12306，接口本身不崩溃
        self.assertIn(res.status_code, (200, 502))

    def test_station_search_empty(self):
        res = self.client.get("/api/stations/search")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), [])

    @patch("night_train_app.services.recommendation.resolve_station", side_effect=_fake_resolve)
    @patch("night_train_app.services.recommendation.query_trains",
           side_effect=RuntimeError("网络超时"))
    def test_query_timeout_returns_502(self, _mock_q, _mock_r):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        res = self.client.post("/api/recommend",
                               json={"from": "北京", "to": "上海", "date": tomorrow,
                                     "direct_only": True})
        # 直达失败且无中转时，返回空列表而非崩溃
        data = res.get_json()
        # 要么成功返回空列表，要么以502返回错误；不应500崩溃
        self.assertIn(res.status_code, (200, 502))
        self.assertNotEqual(res.status_code, 500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
