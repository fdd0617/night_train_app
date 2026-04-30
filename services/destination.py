"""
目的地攻略服务

功能：
  - 通过 OpenAI 兼容接口（/chat/completions）让 LLM 生成城市攻略 JSON
  - 进程内 TTL 缓存，避免重复调用产生费用
  - 输出固定结构：{summary, foods: [{name, desc}], attractions: [{name, desc}]}
  - 调用失败统一抛 RuntimeError，由路由层降级处理

环境变量：
  - OPENAI_API_KEY    必填，OpenAI 兼容服务的 API Key
  - OPENAI_BASE_URL   选填，默认 https://api.openai.com/v1
  - OPENAI_MODEL      选填，默认 gpt-4o-mini
  - DEST_CACHE_TTL    选填，缓存秒数，默认 7 天
  - DEST_TIMEOUT      选填，单次请求超时秒数，默认 30
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TTL_SECONDS = 7 * 24 * 3600
DEFAULT_TIMEOUT = 30

_SYSTEM_PROMPT = (
    "你是一名熟悉中国各地文化与旅游资源的专业导游。"
    "用户会给你一个中国城市名，请你只返回一个 JSON 对象，描述该城市的概况、当地特色美食与必游景点。"
    "禁止输出任何 Markdown、解释或注释，只输出严格合法的 JSON。"
)

_USER_PROMPT_TEMPLATE = (
    "城市：{city}\n"
    "请严格按下列结构输出 JSON：\n"
    "{{\n"
    '  "summary": "150 字以内的城市概览，介绍地理、人文、气候、出行小贴士",\n'
    '  "foods": [\n'
    '    {{"name": "美食名", "desc": "30 字以内简介"}}\n'
    "    // 共 5 ~ 6 项\n"
    "  ],\n"
    '  "attractions": [\n'
    '    {{"name": "景点名", "desc": "30 字以内简介"}}\n'
    "    // 共 5 ~ 6 项\n"
    "  ]\n"
    "}}\n"
    "要求：\n"
    "1) summary 必须是单段连续文本，不含换行；\n"
    "2) foods、attractions 各 5-6 项，避免重复；\n"
    "3) 全部使用简体中文；\n"
    "4) 不要输出 JSON 以外的任何字符。"
)


# ─────────────────────────────────────────────
# 缓存
# ─────────────────────────────────────────────

_cache: dict[str, tuple[dict[str, Any], float]] = {}
_cache_lock = threading.Lock()


def _ttl_seconds() -> int:
    try:
        return int(os.environ.get("DEST_CACHE_TTL", DEFAULT_TTL_SECONDS))
    except ValueError:
        return DEFAULT_TTL_SECONDS


def _cache_get(key: str) -> dict[str, Any] | None:
    with _cache_lock:
        item = _cache.get(key)
        if item is None:
            return None
        payload, expire_ts = item
        if expire_ts < time.time():
            _cache.pop(key, None)
            return None
        return payload


def _cache_set(key: str, payload: dict[str, Any]) -> None:
    with _cache_lock:
        _cache[key] = (payload, time.time() + _ttl_seconds())


# ─────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────

_CITY_SUFFIX_RE = re.compile(r"(站|东|西|南|北|东站|西站|南站|北站)$")


def normalize_city(name: str) -> str:
    """把"上海虹桥""北京西""杭州东"这类站名归一化到城市名。"""
    name = (name or "").strip()
    if not name:
        return name
    # 去掉常见的方位/站后缀
    cleaned = _CITY_SUFFIX_RE.sub("", name)
    return cleaned or name


def _coerce_item_list(raw: Any, max_items: int = 8) -> list[dict[str, str]]:
    """把模型返回的 foods/attractions 字段统一成 [{name, desc}] 列表。"""
    if not isinstance(raw, list):
        return []
    result: list[dict[str, str]] = []
    for item in raw[:max_items]:
        if isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            desc = str(item.get("desc", "") or item.get("description", "")).strip()
            if name:
                result.append({"name": name, "desc": desc})
        elif isinstance(item, str):
            text = item.strip()
            if text:
                result.append({"name": text, "desc": ""})
    return result


def _normalize_payload(city: str, raw: dict[str, Any]) -> dict[str, Any]:
    summary = str(raw.get("summary", "")).strip()
    foods = _coerce_item_list(raw.get("foods"))
    attractions = _coerce_item_list(raw.get("attractions"))
    return {
        "city": city,
        "summary": summary,
        "foods": foods,
        "attractions": attractions,
    }


# ─────────────────────────────────────────────
# LLM 调用
# ─────────────────────────────────────────────

def _call_llm(city: str) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY，无法生成目的地攻略")

    base_url = os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
    model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    try:
        timeout = int(os.environ.get("DEST_TIMEOUT", DEFAULT_TIMEOUT))
    except ValueError:
        timeout = DEFAULT_TIMEOUT

    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _USER_PROMPT_TEMPLATE.format(city=city)},
        ],
        "temperature": 0.6,
        "response_format": {"type": "json_object"},
    }

    logger.info("生成目的地攻略：city=%s model=%s base=%s", city, model, base_url)
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise RuntimeError(f"LLM 网络请求失败：{exc}") from exc

    if resp.status_code != 200:
        # 兼容部分服务不支持 response_format，返回 400 时回退一次
        if resp.status_code == 400 and "response_format" in resp.text:
            logger.warning("当前模型不支持 response_format，回退到纯文本模式")
            payload.pop("response_format", None)
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            except requests.RequestException as exc:
                raise RuntimeError(f"LLM 网络请求失败：{exc}") from exc

    if resp.status_code != 200:
        snippet = resp.text[:200].replace("\n", " ")
        raise RuntimeError(f"LLM 返回 {resp.status_code}：{snippet}")

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"LLM 响应结构异常：{exc}") from exc

    return _parse_json_content(content)


def _parse_json_content(content: str) -> dict[str, Any]:
    """从 LLM 文本回答里提取 JSON 对象，兼容 ```json ... ``` 包裹。"""
    text = (content or "").strip()
    if not text:
        raise RuntimeError("LLM 返回为空")
    # 去掉可能的 markdown 代码块包裹
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 退而求其次：抓出第一个 {...} 段
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise RuntimeError("LLM 返回内容不是合法 JSON")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM 返回 JSON 解析失败：{exc}") from exc


# ─────────────────────────────────────────────
# 对外入口
# ─────────────────────────────────────────────

def get_guide(city_raw: str) -> dict[str, Any]:
    """
    获取城市攻略。命中缓存直接返回；否则调用 LLM 并写入缓存。

    :param city_raw: 用户输入的城市/站名
    :return: {city, summary, foods, attractions}
    :raises RuntimeError: API Key 缺失、网络异常、JSON 解析失败等
    """
    city = normalize_city(city_raw)
    if not city:
        raise RuntimeError("城市名称不能为空")

    cached = _cache_get(city)
    if cached is not None:
        logger.debug("目的地攻略命中缓存：%s", city)
        return cached

    raw = _call_llm(city)
    payload = _normalize_payload(city, raw)
    if not payload["summary"] and not payload["foods"] and not payload["attractions"]:
        raise RuntimeError("LLM 未返回有效内容")
    _cache_set(city, payload)
    return payload
