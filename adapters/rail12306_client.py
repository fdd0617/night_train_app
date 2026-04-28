"""12306 官方渠道适配层

通过 12306 公开接口获取站点列表与余票时刻数据。
主要接口：
  站点列表：https://kyfw.12306.cn/otn/resources/js/framework/station_name.js
  余票查询：https://kyfw.12306.cn/otn/leftTicket/queryZ

注意事项：
  - 余票查询需先访问 init 页面获取 Cookie，否则响应为空
  - 每行数据是 URL 编码的，必须先 unquote 再按 | 分割
  - 响应状态字段为 httpstatus（整数200），而非 status（布尔）
"""
import json
import time
import logging
import urllib.parse
from typing import Optional
from functools import lru_cache

import requests

from ..models import TrainSegment, StationInfo

logger = logging.getLogger(__name__)

# 12306 公开接口地址
_STATION_NAME_URL = (
    "https://kyfw.12306.cn/otn/resources/js/framework/station_name.js"
)
_TICKET_INIT_URL = "https://kyfw.12306.cn/otn/leftTicket/init"
_TICKET_QUERY_URL = "https://kyfw.12306.cn/otn/leftTicket/queryZ"

_BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}
_QUERY_HEADERS = {
    **_BASE_HEADERS,
    "Referer": "https://kyfw.12306.cn/otn/leftTicket/init",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

_DEFAULT_TIMEOUT = 15
_MAX_RETRIES = 3
_RETRY_DELAY = 1.5

_TRAIN_TYPE_MAP = {
    "G": "高铁",
    "D": "动车",
    "C": "城际",
    "Z": "直特",
    "T": "特快",
    "K": "快速",
    "L": "临时客车",
    "Y": "旅游列车",
}


def _get_train_type(train_no: str) -> str:
    prefix = train_no[0].upper() if train_no else ""
    return _TRAIN_TYPE_MAP.get(prefix, "普通")


def _make_session_with_cookies() -> requests.Session:
    """创建带 12306 Cookie 的 Session（先访问 init 页）。"""
    session = requests.Session()
    session.headers.update(_QUERY_HEADERS)
    try:
        session.get(_TICKET_INIT_URL, timeout=_DEFAULT_TIMEOUT)
        logger.debug("Cookie 获取成功：%s", dict(session.cookies))
    except requests.RequestException as exc:
        logger.warning("获取 12306 Cookie 失败，继续尝试查询：%s", exc)
    return session


def _get_with_retry(
    session: requests.Session,
    url: str,
    params: Optional[dict] = None,
    timeout: int = _DEFAULT_TIMEOUT,
    max_retries: int = _MAX_RETRIES,
) -> requests.Response:
    """在已有 Session 上带重试发 GET，失败时抛出 RuntimeError。"""
    last_exc: Exception = RuntimeError("未知错误")
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < max_retries:
                logger.warning(
                    "请求失败（第%d次），%.1fs 后重试：%s", attempt, _RETRY_DELAY, exc
                )
                time.sleep(_RETRY_DELAY)
    raise RuntimeError(f"12306 请求失败（已重试{max_retries}次）：{last_exc}") from last_exc


# ─────────────────────────────────────────────
# 站点数据
# ─────────────────────────────────────────────

@lru_cache(maxsize=1)
def load_stations() -> dict[str, StationInfo]:
    """从 12306 加载全量站点列表，返回 {站名: StationInfo}。结果内存缓存。"""
    logger.info("正在从 12306 加载站点列表…")
    session = requests.Session()
    session.headers.update(_BASE_HEADERS)
    try:
        resp = _get_with_retry(session, _STATION_NAME_URL)
    except RuntimeError as exc:
        raise RuntimeError(f"加载站点列表失败：{exc}") from exc

    raw = resp.text
    # 实际格式：var station_names ='@拼音首|站名|三字码|拼音全|简拼|序号|区号|城市|||@...';
    # 用最简方式提取单引号之间的全部内容，避免字符集限制误杀
    try:
        start = raw.index("'") + 1
        end = raw.rindex("'")
        content = raw[start:end]
    except ValueError:
        raise RuntimeError("站点列表格式解析失败：未找到引号边界")

    if not content.startswith("@"):
        raise RuntimeError("站点列表格式解析失败：内容不以@开头")

    stations: dict[str, StationInfo] = {}
    # 每段格式：拼音首|站名|三字码|拼音全|简拼|序号|区号|城市|...|...|
    for seg in content.split("@"):
        parts = seg.split("|")
        if len(parts) < 4:
            continue
        _, name, code, pinyin = parts[0], parts[1], parts[2], parts[3]
        city = parts[7] if len(parts) > 7 else name
        if not name or not code:
            continue
        info = StationInfo(name=name, code=code, pinyin=pinyin, city=city)
        stations[name] = info
        # 同时以编码为键，便于反查
        stations[code] = info
    logger.info("已加载 %d 个站点（%d 条唯一记录）", len(stations), len(stations) // 2)
    return stations


def search_stations(keyword: str) -> list[StationInfo]:
    """模糊搜索站点，支持中文站名或拼音首字母。返回候选列表（去重）。"""
    stations = load_stations()
    keyword_lower = keyword.lower()
    seen_codes: set[str] = set()
    results: list[StationInfo] = []
    for key, info in stations.items():
        if info.code in seen_codes:
            continue
        if (
            keyword in key
            or keyword_lower in info.pinyin.lower()
        ):
            seen_codes.add(info.code)
            results.append(info)
    return results[:10]


def resolve_station(name: str) -> Optional[StationInfo]:
    """精确解析站名为 StationInfo，失败返回 None。"""
    stations = load_stations()
    # 精确站名匹配
    if name in stations:
        return stations[name]
    # 尝试「XX站」去掉「站」字后再查
    stripped = name.rstrip("站")
    if stripped in stations:
        return stations[stripped]
    return None


# ─────────────────────────────────────────────
# 余票/时刻查询
# ─────────────────────────────────────────────

def _parse_duration(duration_str: str) -> int:
    """将 '13:30' 格式的历时字符串转为分钟数，兼容 '1天13:30' 格式。"""
    total = 0
    if "天" in duration_str:
        parts = duration_str.split("天")
        total += int(parts[0]) * 1440
        duration_str = parts[1]
    h, m = duration_str.split(":")
    total += int(h) * 60 + int(m)
    return total


def _add_days(date_str: str, days: int) -> str:
    """日期字符串加若干天，返回 YYYY-MM-DD。"""
    from datetime import date, timedelta
    d = date.fromisoformat(date_str)
    return (d + timedelta(days=days)).isoformat()


def _calc_arrive_date(
    depart_date: str, depart_time: str, arrive_time: str, duration_minutes: int
) -> str:
    """根据出发日期+时间、到达时间、时长，推算到达日期。"""
    dh, dm = map(int, depart_time.split(":"))
    depart_total = dh * 60 + dm
    arrive_total = depart_total + duration_minutes
    extra_days = arrive_total // (24 * 60)
    return _add_days(depart_date, extra_days)


def _has_sleeper(row_parts: list[str]) -> bool:
    """
    判断列车是否配备卧铺车厢。

    策略：以车次类型为主判断（Z/T/K/L 型是卧铺型列车），
    再补充检查余票字段（硬卧[28]、软卧[23]、动卧[21]）是否有
    明确余票，以覆盖 G/D 型"夕发朝至"列车（动卧席别）。

    字段索引（URL解码后按|分割）：
      [3]  train_no  车次号（用于判断前缀）
      [21] 动卧余票
      [23] 软卧余票
      [28] 硬卧余票
    """
    try:
        train_no = row_parts[3].strip()
        prefix = train_no[0].upper() if train_no else ""
        # Z特快/T特快/K快速/L临时 — 标准卧铺型列车
        if prefix in ("Z", "T", "K", "L"):
            return True
        # 动车/高铁：检查余票字段（动卧[21]、软卧[23]、硬卧[28]）
        for idx in (21, 23, 28):
            val = row_parts[idx].strip()
            if val and val not in ("", "无", "0", "--"):
                return True
    except IndexError:
        pass
    return False


def query_trains(
    from_code: str,
    to_code: str,
    date: str,
    timeout: int = _DEFAULT_TIMEOUT,
    session: Optional[requests.Session] = None,
) -> list[TrainSegment]:
    """
    查询指定日期从 from_code 到 to_code 的全部列车，返回 TrainSegment 列表。

    数据格式说明（实测 2026-04）：
      - 每行数据是 URL 编码字符串，必须先 urllib.parse.unquote 再按 | 分割
      - 响应状态字段为 httpstatus（整数 200），而非旧版 status（布尔 True）
      - 字段索引：[3]=车次号  [6]=出发站码  [7]=到达站码
                  [8]=发车时间  [9]=到达时间  [10]=历时
                  [23]=软卧余票  [28]=硬卧余票

    :param from_code: 出发站 3 字母编码，如 'BJP'
    :param to_code:   到达站 3 字母编码，如 'SHH'
    :param date:      出发日期 'YYYY-MM-DD'
    :param timeout:   请求超时秒
    :param session:   可复用的 requests.Session（含 Cookie），None 则新建
    """
    if session is None:
        session = _make_session_with_cookies()

    params = {
        "leftTicketDTO.train_date": date,
        "leftTicketDTO.from_station": from_code,
        "leftTicketDTO.to_station": to_code,
        "purpose_codes": "ADULT",
    }
    try:
        resp = _get_with_retry(session, _TICKET_QUERY_URL, params=params, timeout=timeout)
    except RuntimeError as exc:
        raise RuntimeError(f"余票查询失败 [{from_code}->{to_code} {date}]：{exc}") from exc

    if not resp.text.strip():
        raise RuntimeError(
            f"12306 返回空响应 [{from_code}->{to_code}]，可能需要刷新 Cookie"
        )

    try:
        data = resp.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"12306 响应 JSON 解析失败：{exc}") from exc

    # 12306 当前返回 httpstatus（整数），而非旧版 status（布尔）
    http_status = data.get("httpstatus") or data.get("status")
    if http_status != 200 and http_status is not True:
        msg = data.get("messages") or data.get("c_url") or str(data)
        raise RuntimeError(f"12306 接口返回错误 [{http_status}]：{msg}")

    result_data = data.get("data", {})
    train_list = result_data.get("result", [])
    station_map: dict[str, str] = result_data.get("map", {})  # code -> 站名

    segments: list[TrainSegment] = []
    for row in train_list:
        # 关键：每行是 URL 编码字符串，必须先解码再按 | 分割
        decoded = urllib.parse.unquote(row)
        parts = decoded.split("|")
        if len(parts) < 35:
            continue
        try:
            train_no = parts[3]
            from_code_ = parts[6]
            to_code_ = parts[7]
            depart_time = parts[8]
            arrive_time = parts[9]
            duration_str = parts[10]
        except IndexError:
            continue

        if not train_no or not depart_time:
            continue

        from_name = station_map.get(from_code_, from_code_)
        to_name = station_map.get(to_code_, to_code_)
        duration_minutes = _parse_duration(duration_str)
        arrive_date = _calc_arrive_date(date, depart_time, arrive_time, duration_minutes)

        seg = TrainSegment(
            train_no=train_no,
            from_station=from_name,
            to_station=to_name,
            from_station_code=from_code_,
            to_station_code=to_code_,
            depart_time=depart_time,
            arrive_time=arrive_time,
            duration_minutes=duration_minutes,
            train_type=_get_train_type(train_no),
            has_sleeper=_has_sleeper(parts),
            depart_date=date,
            arrive_date=arrive_date,
        )
        segments.append(seg)

    return segments
