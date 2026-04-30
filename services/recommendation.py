"""
行程构建与夜间推荐评分引擎

流程：
  1. 获取直达列车候选
  2. 枚举热门中转站，获取1次中转候选
  3. 对每条行程进行综合评分（夜间占比、到达时段、总耗时、换乘次数、卧铺）
  4. 排序后返回 Top N
"""
import logging
import threading
import time
import concurrent.futures
from collections import OrderedDict
from typing import Optional

from ..config import Config
from ..models import TrainSegment, TripPlan
from ..adapters.rail12306_client import query_trains, resolve_station, _make_session_with_cookies

logger = logging.getLogger(__name__)

# 模块级别名（保持向后兼容 + 测试可读性）
NIGHT_START_HOUR = Config.NIGHT_START_HOUR
NIGHT_END_HOUR = Config.NIGHT_END_HOUR
MORNING_START_HOUR = Config.MORNING_START_HOUR
MORNING_END_HOUR = Config.MORNING_END_HOUR
WEIGHT_NIGHT_RATIO = Config.WEIGHT_NIGHT_RATIO
WEIGHT_MORNING_ARRIVE = Config.WEIGHT_MORNING_ARRIVE
WEIGHT_DURATION = Config.WEIGHT_DURATION
WEIGHT_TRANSFER_PENALTY = Config.WEIGHT_TRANSFER_PENALTY
WEIGHT_SLEEPER_BONUS = Config.WEIGHT_SLEEPER_BONUS

# 中转候选站（覆盖全国主要枢纽，dict.fromkeys 保序去重以防手抖重复）
_TRANSFER_HUBS = list(dict.fromkeys([
    "郑州", "武汉", "成都", "重庆", "西安", "南京",
    "杭州", "济南", "沈阳", "哈尔滨", "长沙", "合肥",
    "南昌", "石家庄", "太原", "呼和浩特", "兰州", "乌鲁木齐",
    "南宁", "贵阳", "昆明", "福州", "厦门",
    "徐州", "株洲", "宝鸡", "湛江",
]))

# 中转约束（来自 Config）
MIN_TRANSFER_WAIT_MINUTES = Config.MIN_TRANSFER_WAIT_MINUTES
MAX_TRANSFER_WAIT_MINUTES = Config.MAX_TRANSFER_WAIT_MINUTES
MAX_RESULTS = Config.MAX_RESULTS


# ─────────────────────────────────────────────
# 查询结果 TTL 缓存（避免短时间内重复打 12306）
# ─────────────────────────────────────────────
_query_cache: OrderedDict[tuple, tuple[tuple[list[TripPlan], list[str]], float]] = (
    OrderedDict()
)
_query_cache_lock = threading.Lock()


def _cache_key(
    from_city: str, to_city: str, date: str,
    allow_transfer: bool, sleeper_only: bool, direct_only: bool,
) -> tuple:
    return (from_city, to_city, date, allow_transfer, sleeper_only, direct_only)


def _cache_get(key: tuple):
    with _query_cache_lock:
        item = _query_cache.get(key)
        if item is None:
            return None
        result, expire_ts = item
        if expire_ts < time.time():
            _query_cache.pop(key, None)
            return None
        # LRU 行为：被命中后挪到末尾
        _query_cache.move_to_end(key)
        return result


def _cache_put(key: tuple, value) -> None:
    with _query_cache_lock:
        _query_cache[key] = (value, time.time() + Config.QUERY_CACHE_TTL)
        _query_cache.move_to_end(key)
        while len(_query_cache) > Config.QUERY_CACHE_SIZE:
            _query_cache.popitem(last=False)


def clear_query_cache() -> None:
    """供测试 / 管理接口手动清空查询缓存。"""
    with _query_cache_lock:
        _query_cache.clear()


# ─────────────────────────────────────────────
# 时间工具
# ─────────────────────────────────────────────

def _time_to_minutes(t: str) -> int:
    """HH:MM → 当日分钟数，如 '23:30' → 1410。"""
    h, m = map(int, t.split(":"))
    return h * 60 + m


def _night_overlap_minutes(
    depart_time: str,
    duration_minutes: int,
) -> int:
    """
    计算一段列车行程中处于夜间时段（NIGHT_START_HOUR ~ 次日 NIGHT_END_HOUR）的分钟数。

    实现：从出发那一天 00:00 开始，按天枚举每一晚的夜间窗口
    [day_start + NIGHT_START_HOUR*60,  day_start + (NIGHT_END_HOUR + 24)*60]，
    与行程区间 [start, end] 求交集叠加，直到窗口起点超过 end。
    """
    if duration_minutes <= 0:
        return 0
    start = _time_to_minutes(depart_time)
    end = start + duration_minutes
    total = 0
    day_start = (start // 1440) * 1440
    while True:
        ns = day_start + NIGHT_START_HOUR * 60
        ne = day_start + (NIGHT_END_HOUR + 24) * 60
        if ns >= end:
            break
        overlap = max(0, min(end, ne) - max(start, ns))
        total += overlap
        day_start += 1440
    return min(total, duration_minutes)


def _night_ratio(depart_time: str, duration_minutes: int) -> float:
    """夜间乘车占比 0.0~1.0。"""
    if duration_minutes == 0:
        return 0.0
    overlap = _night_overlap_minutes(depart_time, duration_minutes)
    return min(overlap / duration_minutes, 1.0)


def _arrives_morning(arrive_time: str) -> bool:
    """判断是否在早晨（06:00-10:00）到达。"""
    am = _time_to_minutes(arrive_time)
    return MORNING_START_HOUR * 60 <= am < MORNING_END_HOUR * 60


# ─────────────────────────────────────────────
# 评分
# ─────────────────────────────────────────────

def _max_reasonable_duration(is_transfer: bool) -> int:
    """合理最大行程时长（分钟），用于归一化耗时。"""
    return 2400 if not is_transfer else 3000  # 40h / 50h


def score_trip(plan: TripPlan) -> float:
    """
    综合评分，越高越优先推荐（满分约 1.0）。
    各项分解：
      - 夜间占比    40%：越高越好
      - 早晨到达    25%：是=1 否=0
      - 总耗时      20%：越短越好（线性归一化到最大合理时长）
      - 中转惩罚    10%：直达=1 中转=0.5
      - 卧铺奖励     5%：有=1 无=0
    """
    max_dur = _max_reasonable_duration(not plan.is_direct)
    duration_score = max(0.0, 1.0 - plan.total_minutes / max_dur)
    transfer_score = 1.0 if plan.is_direct else 0.5
    sleeper_score = 1.0 if plan.has_sleeper else 0.0
    morning_score = 1.0 if plan.arrives_morning else 0.0

    return (
        WEIGHT_NIGHT_RATIO * plan.night_ratio
        + WEIGHT_MORNING_ARRIVE * morning_score
        + WEIGHT_DURATION * duration_score
        + WEIGHT_TRANSFER_PENALTY * transfer_score
        + WEIGHT_SLEEPER_BONUS * sleeper_score
    )


def _build_reasons(plan: TripPlan) -> list[str]:
    reasons = []
    pct = int(plan.night_ratio * 100)
    if pct >= 80:
        reasons.append(f"夜间乘车占比 {pct}%，几乎全程在夜里")
    elif pct >= 50:
        reasons.append(f"夜间乘车占比 {pct}%，有效节省住宿一晚")
    elif pct > 0:
        reasons.append(f"夜间乘车占比 {pct}%")

    if plan.arrives_morning:
        reasons.append(f"早晨 {plan.arrive_time} 到达，全天可安排游览")

    h, m = divmod(plan.total_minutes, 60)
    reasons.append(f"全程约 {h} 小时 {m} 分钟")

    if plan.is_direct:
        reasons.append("全程直达，无需换乘")
    else:
        wait = plan.total_minutes - sum(s.duration_minutes for s in plan.segments)
        reasons.append(f"经 {plan.transfer_station} 中转，等候约 {wait} 分钟")

    if plan.has_sleeper:
        reasons.append("有卧铺席别，夜间可平躺休息")

    return reasons


# ─────────────────────────────────────────────
# 行程构建
# ─────────────────────────────────────────────

def _make_direct_plan(seg: TrainSegment) -> TripPlan:
    ratio = _night_ratio(seg.depart_time, seg.duration_minutes)
    plan = TripPlan(
        segments=[seg],
        total_minutes=seg.duration_minutes,
        night_ratio=ratio,
        arrives_morning=_arrives_morning(seg.arrive_time),
        score=0.0,
    )
    plan.score = score_trip(plan)
    plan.reasons = _build_reasons(plan)
    return plan


def _make_transfer_plan(
    seg1: TrainSegment, seg2: TrainSegment
) -> Optional[TripPlan]:
    """从两段列车构建中转行程，校验换乘时间窗合法性。"""
    # 计算换乘等待时间（分钟）
    arr1_min = _time_to_minutes(seg1.arrive_time)
    dep2_min = _time_to_minutes(seg2.depart_time)

    # 跨日修正
    if seg2.depart_date > seg1.arrive_date:
        dep2_min += 1440 * (
            _date_diff(seg1.arrive_date, seg2.depart_date)
        )
    elif dep2_min < arr1_min:
        dep2_min += 1440

    wait_minutes = dep2_min - arr1_min
    if wait_minutes < MIN_TRANSFER_WAIT_MINUTES:
        return None
    if wait_minutes > MAX_TRANSFER_WAIT_MINUTES:
        return None

    total = seg1.duration_minutes + wait_minutes + seg2.duration_minutes
    # 夜间占比取两段加权平均
    night1 = _night_overlap_minutes(seg1.depart_time, seg1.duration_minutes)
    night2 = _night_overlap_minutes(seg2.depart_time, seg2.duration_minutes)
    ratio = (night1 + night2) / total if total > 0 else 0.0

    plan = TripPlan(
        segments=[seg1, seg2],
        total_minutes=total,
        night_ratio=min(ratio, 1.0),
        arrives_morning=_arrives_morning(seg2.arrive_time),
        score=0.0,
    )
    plan.score = score_trip(plan)
    plan.reasons = _build_reasons(plan)
    return plan


def _date_diff(d1: str, d2: str) -> int:
    """返回 d2 - d1 的天数差（均为 YYYY-MM-DD）。"""
    from datetime import date
    return (date.fromisoformat(d2) - date.fromisoformat(d1)).days


# ─────────────────────────────────────────────
# 对外入口
# ─────────────────────────────────────────────

def build_recommendations(
    from_city: str,
    to_city: str,
    date: str,
    allow_transfer: bool = True,
    sleeper_only: bool = False,
    direct_only: bool = False,
) -> tuple[list[TripPlan], list[str]]:
    """
    主查询入口。

    :param from_city:    出发站名，如"北京"
    :param to_city:      目的站名，如"上海"
    :param date:         出发日期 YYYY-MM-DD
    :param allow_transfer: 是否允许中转
    :param sleeper_only:   是否仅返回含卧铺的方案
    :param direct_only:    是否仅返回直达方案
    :return: (推荐行程列表, 警告信息列表)
    """
    # 命中缓存直接返回（避免短时间内重复打 12306）
    cache_key = _cache_key(
        from_city, to_city, date, allow_transfer, sleeper_only, direct_only
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info("查询命中缓存：%s → %s [%s]", from_city, to_city, date)
        return cached

    warnings: list[str] = []

    from_info = resolve_station(from_city)
    to_info = resolve_station(to_city)
    if from_info is None:
        raise ValueError(f"未找到出发站：{from_city}，请输入准确的中文站名")
    if to_info is None:
        raise ValueError(f"未找到目的站：{to_city}，请输入准确的中文站名")

    logger.info("查询 %s(%s) → %s(%s) [%s]", from_city, from_info.code, to_city, to_info.code, date)

    # 主线程使用独立 Session 完成直达查询
    main_session = _make_session_with_cookies()

    # 1. 直达
    direct_segs: list[TrainSegment] = []
    try:
        direct_segs = query_trains(
            from_info.code, to_info.code, date, session=main_session
        )
        logger.info("直达车次 %d 趟", len(direct_segs))
    except RuntimeError as exc:
        msg = str(exc)
        if "JSON" in msg or "限流" in msg or "风控" in msg or "空响应" in msg:
            warnings.append("12306 当前繁忙或触发限流，部分车次可能未查询到，请几秒后重试")
            logger.warning("直达查询失败（限流类）：%s", exc)
        else:
            warnings.append(f"直达查询失败：{exc}")

    plans: list[TripPlan] = [_make_direct_plan(s) for s in direct_segs]

    # 2. 中转：每个工作线程独立 Session，避免共享状态
    if allow_transfer and not direct_only:
        transfer_plans = _build_transfer_plans(
            from_info.code, to_info.code, date, warnings
        )
        plans.extend(transfer_plans)

    # 3. 筛选
    if sleeper_only:
        plans = [p for p in plans if p.has_sleeper]

    # 4. 排序：仅保留 night_ratio > 0 或评分靠前，确保推荐质量
    plans.sort(key=lambda p: p.score, reverse=True)
    night_plans = [p for p in plans if p.night_ratio > 0]
    other_plans = [p for p in plans if p.night_ratio == 0]

    result = night_plans[:MAX_RESULTS]
    # 若夜间方案不足5个，补充普通方案
    if len(result) < 5:
        result += other_plans[: max(0, 5 - len(result))]

    payload = (result, warnings)
    _cache_put(cache_key, payload)
    return payload


def _build_transfer_plans(
    from_code: str,
    to_code: str,
    date: str,
    warnings: list[str],
) -> list[TripPlan]:
    """
    并行查询各中转站方案。

    线程安全：requests.Session 不是线程安全的（cookies / 连接池等内部状态会被并发写
    入），因此每个工作线程通过 threading.local() 懒创建并复用一个独立 Session。
    同一线程内 leg1+leg2 可继续复用同一 Session 与 Cookie。
    """
    plans: list[TripPlan] = []
    thread_local = threading.local()

    def _get_session():
        sess = getattr(thread_local, "session", None)
        if sess is None:
            sess = _make_session_with_cookies()
            thread_local.session = sess
        return sess

    def _query_hub(hub_name: str) -> list[TripPlan]:
        hub = resolve_station(hub_name)
        if hub is None:
            return []
        sess = _get_session()
        hub_plans: list[TripPlan] = []
        try:
            leg1 = query_trains(from_code, hub.code, date, session=sess)
            if not leg1:
                return []
            leg2 = query_trains(hub.code, to_code, date, session=sess)
            if not leg2:
                return []
        except RuntimeError:
            return []

        for s1 in leg1:
            for s2 in leg2:
                plan = _make_transfer_plan(s1, s2)
                if plan is not None:
                    hub_plans.append(plan)
        return hub_plans

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=Config.TRANSFER_MAX_WORKERS
    ) as pool:
        futures = {pool.submit(_query_hub, hub): hub for hub in _TRANSFER_HUBS}
        for future in concurrent.futures.as_completed(futures, timeout=30):
            hub = futures[future]
            try:
                hub_plans = future.result()
                plans.extend(hub_plans)
                if hub_plans:
                    logger.debug("中转站 %s：%d 条方案", hub, len(hub_plans))
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"中转站 {hub} 查询失败：{exc}")

    return plans
