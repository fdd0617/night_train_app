"""核心数据模型"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TrainSegment:
    """单段列车行程"""
    train_no: str            # 车次编号，如 Z2, K1058
    from_station: str        # 出发站名
    to_station: str          # 到达站名
    from_station_code: str   # 出发站编码
    to_station_code: str     # 到达站编码
    depart_time: str         # 出发时间 HH:MM
    arrive_time: str         # 到达时间 HH:MM
    duration_minutes: int    # 行程分钟数（含跨日）
    train_type: str          # 车型: Z特快/K快/T直特/G高铁/D动车/...
    has_sleeper: bool        # 是否有卧铺票（硬卧/软卧）
    depart_date: str         # 出发日期 YYYY-MM-DD
    arrive_date: str         # 到达日期 YYYY-MM-DD


@dataclass
class TripPlan:
    """完整行程方案（直达或一次中转）"""
    segments: list[TrainSegment]     # 行程段列表，1段=直达，2段=中转
    total_minutes: int               # 总耗时（含候车）
    night_ratio: float               # 夜间乘车时间占比 0.0~1.0
    arrives_morning: bool            # 是否早晨到达（06:00-10:00）
    score: float                     # 综合推荐分
    reasons: list[str] = field(default_factory=list)  # 推荐理由列表

    @property
    def is_direct(self) -> bool:
        return len(self.segments) == 1

    @property
    def depart_time(self) -> str:
        return self.segments[0].depart_time

    @property
    def arrive_time(self) -> str:
        return self.segments[-1].arrive_time

    @property
    def arrive_date(self) -> str:
        return self.segments[-1].arrive_date

    @property
    def has_sleeper(self) -> bool:
        return any(s.has_sleeper for s in self.segments)

    @property
    def transfer_station(self) -> Optional[str]:
        if len(self.segments) == 2:
            return self.segments[0].to_station
        return None


@dataclass
class StationInfo:
    """车站信息"""
    name: str    # 站名
    code: str    # 12306 站点编码（3字母大写）
    pinyin: str  # 拼音（用于模糊搜索）
    city: str    # 所属城市
