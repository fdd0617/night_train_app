"""Flask 应用入口"""
import logging
import os
from datetime import date, timedelta

from flask import Flask, jsonify, render_template, request

from .adapters.rail12306_client import search_stations
from .services.recommendation import build_recommendations

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)


def _today() -> str:
    return date.today().isoformat()


def _tomorrow() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


@app.get("/")
def index():
    return render_template("index.html", today=_today(), tomorrow=_tomorrow())


@app.get("/api/stations/search")
def api_station_search():
    """站点搜索接口，供前端自动补全使用。"""
    keyword = request.args.get("q", "").strip()
    if not keyword:
        return jsonify([])
    try:
        results = search_stations(keyword)
    except RuntimeError as exc:
        logger.warning("站点搜索失败：%s", exc)
        return jsonify({"error": f"站点数据加载失败：{exc}"}), 502
    return jsonify([{"name": s.name, "code": s.code} for s in results])


@app.post("/api/recommend")
def api_recommend():
    """推荐查询接口。

    Request JSON:
        {
            "from": "北京",
            "to": "上海",
            "date": "2026-05-01",
            "sleeper_only": false,
            "direct_only": false
        }

    Response JSON:
        {
            "plans": [...],
            "warnings": [...],
            "total": 12
        }
    """
    body = request.get_json(silent=True) or {}
    from_city = (body.get("from") or "").strip()
    to_city = (body.get("to") or "").strip()
    travel_date = (body.get("date") or "").strip()
    sleeper_only = bool(body.get("sleeper_only", False))
    direct_only = bool(body.get("direct_only", False))

    if not from_city or not to_city:
        return jsonify({"error": "出发地和目的地不能为空"}), 400
    if not travel_date:
        return jsonify({"error": "请选择出发日期"}), 400

    # 日期合法性
    try:
        d = date.fromisoformat(travel_date)
        if d < date.today():
            return jsonify({"error": "出发日期不能早于今天"}), 400
        if d > date.today() + timedelta(days=30):
            return jsonify({"error": "目前仅支持查询 30 天内的票务信息"}), 400
    except ValueError:
        return jsonify({"error": "日期格式无效，请使用 YYYY-MM-DD"}), 400

    try:
        plans, warnings = build_recommendations(
            from_city=from_city,
            to_city=to_city,
            date=travel_date,
            allow_transfer=not direct_only,
            sleeper_only=sleeper_only,
            direct_only=direct_only,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except RuntimeError as exc:
        logger.exception("推荐查询内部错误")
        return jsonify({"error": f"查询失败：{exc}"}), 502

    serialized = []
    for plan in plans:
        segs = []
        for seg in plan.segments:
            segs.append({
                "train_no": seg.train_no,
                "train_type": seg.train_type,
                "from_station": seg.from_station,
                "to_station": seg.to_station,
                "depart_time": seg.depart_time,
                "arrive_time": seg.arrive_time,
                "depart_date": seg.depart_date,
                "arrive_date": seg.arrive_date,
                "duration_minutes": seg.duration_minutes,
                "has_sleeper": seg.has_sleeper,
            })
        serialized.append({
            "is_direct": plan.is_direct,
            "total_minutes": plan.total_minutes,
            "night_ratio": round(plan.night_ratio, 3),
            "arrives_morning": plan.arrives_morning,
            "has_sleeper": plan.has_sleeper,
            "score": round(plan.score, 4),
            "reasons": plan.reasons,
            "segments": segs,
            "transfer_station": plan.transfer_station,
            "depart_time": plan.depart_time,
            "arrive_time": plan.arrive_time,
            "arrive_date": plan.arrive_date,
        })

    return jsonify({
        "plans": serialized,
        "warnings": warnings,
        "total": len(serialized),
    })


def run():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    run()
