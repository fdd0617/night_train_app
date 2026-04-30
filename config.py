"""
统一配置中心。

所有环境变量与默认参数在这里集中读取一次，其他模块通过 ``from .config import Config``
访问，避免散落的 ``os.environ`` 调用与硬编码常量。

使用方式：
    from .config import Config
    timeout = Config.RAIL_TIMEOUT
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

# ─────────────────────────────────────────────
# .env 自动加载（最早执行，确保后续读取生效）
# ─────────────────────────────────────────────
try:
    from dotenv import load_dotenv  # type: ignore

    _PROJECT_ROOT = Path(__file__).resolve().parent
    load_dotenv(_PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass

logger = logging.getLogger(__name__)


def _env_str(key: str, default: str) -> str:
    val = os.environ.get(key)
    if val is None or val == "":
        return default
    return val


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("环境变量 %s=%r 不是合法整数，使用默认值 %d", key, raw, default)
        return default


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("环境变量 %s=%r 不是合法浮点数，使用默认值 %s", key, raw, default)
        return default


class Config:
    """全部配置项；类属性都是从 .env / 环境变量读取后的最终值。"""

    # ---------- 服务 ----------
    PORT: int = _env_int("PORT", 5000)
    DEBUG: bool = _env_str("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")

    # ---------- 12306 ----------
    RAIL_TIMEOUT: int = _env_int("RAIL_TIMEOUT", 15)
    RAIL_MAX_RETRIES: int = _env_int("RAIL_MAX_RETRIES", 3)
    RAIL_RETRY_DELAY: float = _env_float("RAIL_RETRY_DELAY", 1.5)
    STATION_CACHE_PATH: str = _env_str("STATION_CACHE_PATH", "station_names.json")

    # ---------- 时段定义（24h）----------
    NIGHT_START_HOUR: int = _env_int("NIGHT_START_HOUR", 21)
    NIGHT_END_HOUR: int = _env_int("NIGHT_END_HOUR", 8)
    MORNING_START_HOUR: int = _env_int("MORNING_START_HOUR", 6)
    MORNING_END_HOUR: int = _env_int("MORNING_END_HOUR", 10)

    # ---------- 评分权重（不暴露为 env，需调参直接改这里）----------
    WEIGHT_NIGHT_RATIO: float = 0.40
    WEIGHT_MORNING_ARRIVE: float = 0.25
    WEIGHT_DURATION: float = 0.20
    WEIGHT_TRANSFER_PENALTY: float = 0.10
    WEIGHT_SLEEPER_BONUS: float = 0.05

    # ---------- 中转约束 ----------
    MIN_TRANSFER_WAIT_MINUTES: int = _env_int("MIN_TRANSFER_WAIT_MINUTES", 60)
    MAX_TRANSFER_WAIT_MINUTES: int = _env_int("MAX_TRANSFER_WAIT_MINUTES", 480)
    MAX_RESULTS: int = _env_int("MAX_RESULTS", 15)
    TRANSFER_MAX_WORKERS: int = _env_int("TRANSFER_MAX_WORKERS", 6)

    # ---------- 查询缓存 ----------
    # 同一 (from, to, date, sleeper, direct) 在 TTL 内复用结果，避免重复打 12306
    QUERY_CACHE_TTL: int = _env_int("QUERY_CACHE_TTL", 30)
    QUERY_CACHE_SIZE: int = _env_int("QUERY_CACHE_SIZE", 256)

    # ---------- 多日查询 ----------
    MULTI_DAY_MAX_DAYS: int = _env_int("MULTI_DAY_MAX_DAYS", 7)

    # ---------- 限流 ----------
    RATE_LIMIT_ENABLED: bool = _env_str("RATE_LIMIT_ENABLED", "true").lower() in (
        "1", "true", "yes"
    )
    RATE_LIMIT_DEFAULT: str = _env_str("RATE_LIMIT_DEFAULT", "200 per hour")
    RATE_LIMIT_RECOMMEND: str = _env_str("RATE_LIMIT_RECOMMEND", "10 per minute")
    RATE_LIMIT_STATIONS: str = _env_str("RATE_LIMIT_STATIONS", "30 per minute")
    RATE_LIMIT_DESTINATION: str = _env_str("RATE_LIMIT_DESTINATION", "10 per minute")

    # ---------- LLM（OpenAI 兼容接口）----------
    OPENAI_API_KEY: str = _env_str("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = _env_str("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OPENAI_MODEL: str = _env_str("OPENAI_MODEL", "gpt-4o-mini")
    DEST_CACHE_TTL: int = _env_int("DEST_CACHE_TTL", 7 * 24 * 3600)
    DEST_TIMEOUT: int = _env_int("DEST_TIMEOUT", 30)
