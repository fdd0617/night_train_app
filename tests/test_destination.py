"""destination.py 单元测试：JSON 解析容错、缓存、城市归一化"""
import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from night_train_app.services import destination as dest


class TestNormalizeCity(unittest.TestCase):
    def test_strip_zhan_suffix(self):
        self.assertEqual(dest.normalize_city("北京站"), "北京")

    def test_strip_direction_suffix(self):
        self.assertEqual(dest.normalize_city("北京西"), "北京")
        self.assertEqual(dest.normalize_city("杭州东"), "杭州")
        self.assertEqual(dest.normalize_city("上海南"), "上海")

    def test_strip_compound_suffix(self):
        self.assertEqual(dest.normalize_city("杭州东站"), "杭州")
        self.assertEqual(dest.normalize_city("北京西站"), "北京")

    def test_keep_pure_city(self):
        self.assertEqual(dest.normalize_city("成都"), "成都")
        self.assertEqual(dest.normalize_city("拉萨"), "拉萨")

    def test_empty(self):
        self.assertEqual(dest.normalize_city(""), "")
        self.assertEqual(dest.normalize_city("   "), "")


class TestParseJsonContent(unittest.TestCase):
    def test_pure_json(self):
        text = '{"summary": "hi", "foods": [], "attractions": []}'
        self.assertEqual(dest._parse_json_content(text)["summary"], "hi")

    def test_markdown_wrapped(self):
        text = '```json\n{"summary": "hi"}\n```'
        self.assertEqual(dest._parse_json_content(text)["summary"], "hi")

    def test_markdown_wrapped_no_lang(self):
        text = '```\n{"summary": "hi"}\n```'
        self.assertEqual(dest._parse_json_content(text)["summary"], "hi")

    def test_extra_text_around_json(self):
        # LLM 偶尔会在 JSON 前后多说一句话，应该能截到 {...}
        text = '好的，这是 JSON：{"summary": "hi"}。'
        self.assertEqual(dest._parse_json_content(text)["summary"], "hi")

    def test_invalid_json_raises(self):
        with self.assertRaises(RuntimeError):
            dest._parse_json_content("这根本不是 JSON")

    def test_empty_raises(self):
        with self.assertRaises(RuntimeError):
            dest._parse_json_content("")


class TestCoerceItemList(unittest.TestCase):
    def test_dict_items(self):
        out = dest._coerce_item_list([
            {"name": "外滩", "desc": "黄浦江畔"},
            {"name": "豫园", "description": "古典园林"},  # 兼容 description 别名
        ])
        self.assertEqual(out[0]["name"], "外滩")
        self.assertEqual(out[1]["desc"], "古典园林")

    def test_string_items_become_name_only(self):
        out = dest._coerce_item_list(["小笼包", "生煎包"])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["name"], "小笼包")
        self.assertEqual(out[0]["desc"], "")

    def test_drop_empty_names(self):
        out = dest._coerce_item_list([{"name": "", "desc": "x"}, {"name": "ok"}])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name"], "ok")

    def test_non_list_returns_empty(self):
        self.assertEqual(dest._coerce_item_list(None), [])
        self.assertEqual(dest._coerce_item_list("hi"), [])
        self.assertEqual(dest._coerce_item_list({"x": 1}), [])

    def test_max_items_cap(self):
        many = [{"name": f"A{i}"} for i in range(20)]
        out = dest._coerce_item_list(many, max_items=5)
        self.assertEqual(len(out), 5)


class TestNormalizePayload(unittest.TestCase):
    def test_basic(self):
        out = dest._normalize_payload("上海", {
            "summary": "  上海是…  ",
            "foods": [{"name": "生煎包", "desc": "底脆"}],
            "attractions": [{"name": "外滩", "desc": "经典"}],
        })
        self.assertEqual(out["city"], "上海")
        self.assertEqual(out["summary"], "上海是…")
        self.assertEqual(len(out["foods"]), 1)

    def test_missing_fields_become_empty(self):
        out = dest._normalize_payload("成都", {})
        self.assertEqual(out["summary"], "")
        self.assertEqual(out["foods"], [])
        self.assertEqual(out["attractions"], [])


class TestCache(unittest.TestCase):
    def setUp(self):
        # 隔离测试用缓存
        with dest._cache_lock:
            dest._cache.clear()

    def test_cache_hit(self):
        with dest._cache_lock:
            dest._cache["上海"] = ({"city": "上海", "summary": "x"}, time.time() + 60)
        self.assertEqual(dest._cache_get("上海")["summary"], "x")

    def test_cache_expired(self):
        with dest._cache_lock:
            dest._cache["上海"] = ({"city": "上海"}, time.time() - 10)
        self.assertIsNone(dest._cache_get("上海"))

    def test_cache_miss(self):
        self.assertIsNone(dest._cache_get("不存在"))


class TestGetGuide(unittest.TestCase):
    def setUp(self):
        with dest._cache_lock:
            dest._cache.clear()

    def test_empty_city_raises(self):
        with self.assertRaises(RuntimeError):
            dest.get_guide("   ")

    @patch("night_train_app.services.destination._call_llm")
    def test_returns_normalized(self, mock_call):
        mock_call.return_value = {
            "summary": "概览",
            "foods": [{"name": "A", "desc": "a"}],
            "attractions": [{"name": "B", "desc": "b"}],
        }
        out = dest.get_guide("北京西")
        self.assertEqual(out["city"], "北京")  # 已归一化
        self.assertEqual(out["summary"], "概览")
        # 第二次直接命中缓存，不再调 LLM
        dest.get_guide("北京西")
        self.assertEqual(mock_call.call_count, 1)

    @patch("night_train_app.services.destination._call_llm")
    def test_empty_payload_raises(self, mock_call):
        mock_call.return_value = {}
        with self.assertRaises(RuntimeError):
            dest.get_guide("某地")


if __name__ == "__main__":
    unittest.main()
