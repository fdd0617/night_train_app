"""Flask 应用入口"""
import logging
from datetime import date, timedelta

from flask import Flask, jsonify, render_template, request

from .config import Config  # 必须最先导入：触发 .env 加载与配置初始化
from .adapters.rail12306_client import search_stations
from .services.destination import get_guide
from .services.recommendation import build_recommendations

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024  # 1MB


# ─────────────────────────────────────────────
# 限流（flask-limiter）：
#   未安装库 / RATE_LIMIT_ENABLED=false 时退化为空装饰器，不影响功能
# ─────────────────────────────────────────────
def _noop_decorator(*_a, **_k):
    def deco(fn):
        return fn
    return deco


limiter = None
try:
    if Config.RATE_LIMIT_ENABLED:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address

        limiter = Limiter(
            app=app,
            key_func=get_remote_address,
            default_limits=[Config.RATE_LIMIT_DEFAULT],
            storage_uri="memory://",
            headers_enabled=True,
        )
        logger.info("已启用限流：default=%s recommend=%s stations=%s destination=%s",
                    Config.RATE_LIMIT_DEFAULT, Config.RATE_LIMIT_RECOMMEND,
                    Config.RATE_LIMIT_STATIONS, Config.RATE_LIMIT_DESTINATION)
except ImportError:
    logger.warning("未安装 flask-limiter，限流功能未启用")


def _limit(rule: str):
    """统一的限流装饰器入口；未启用 limiter 时返回 no-op。"""
    if limiter is None:
        return _noop_decorator()
    return limiter.limit(rule)


@app.errorhandler(429)
def _on_rate_limit_exceeded(e):  # noqa: D401, ANN001
    return jsonify({
        "error": "请求过于频繁，请稍后再试",
        "detail": getattr(e, "description", "rate limit exceeded"),
    }), 429


def _today() -> str:
    return date.today().isoformat()


def _tomorrow() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


@app.get("/")
def index():
    return render_template("index.html", today=_today(), tomorrow=_tomorrow())


@app.get("/sw.js")
def service_worker():
    """把 service worker 暴露在根路径，让 scope = /，可控制全站。"""
    from flask import send_from_directory, current_app
    response = send_from_directory(
        current_app.static_folder, "sw.js", mimetype="application/javascript"
    )
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/health")
def api_health():
    """健康检查端点。返回服务运行状态与关键依赖可用性。"""
    from datetime import datetime, timezone

    # 站点列表是 12306 数据是否可用的弱信号
    try:
        from .adapters.rail12306_client import load_stations
        station_count = len(load_stations()) // 2  # name + code 双键
        stations_ok = station_count > 0
    except Exception:  # noqa: BLE001
        station_count = 0
        stations_ok = False

    payload = {
        "status": "ok" if stations_ok else "degraded",
        "time": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "checks": {
            "stations_loaded": stations_ok,
            "station_count": station_count,
            "llm_configured": bool(Config.OPENAI_API_KEY),
        },
    }
    code = 200 if stations_ok else 503
    return jsonify(payload), code


@app.get("/api/stations/search")
@_limit(Config.RATE_LIMIT_STATIONS)
def api_station_search():
    """站点搜索接口，供前端自动补全使用。"""
    keyword = request.args.get("q", "").strip()
    if not keyword:
        return jsonify([])
    if len(keyword) > 30:
        return jsonify({"error": "搜索关键词过长"}), 400
    try:
        results = search_stations(keyword)
    except RuntimeError as exc:
        logger.warning("站点搜索失败：%s", exc)
        return jsonify({"error": f"站点数据加载失败：{exc}"}), 502
    return jsonify([{"name": s.name, "code": s.code} for s in results])


@app.post("/api/recommend")
@_limit(Config.RATE_LIMIT_RECOMMEND)
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
    if len(from_city) > 50 or len(to_city) > 50:
        return jsonify({"error": "站名过长"}), 400
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

    serialized = [plan.as_dict() for plan in plans]
    return jsonify({
        "plans": serialized,
        "warnings": warnings,
        "total": len(serialized),
    })


@app.post("/api/recommend/multi-day")
@_limit(Config.RATE_LIMIT_RECOMMEND)
def api_recommend_multi_day():
    """
    多日比价查询：连续 N 天每天的最佳夜行方案。

    Request JSON：
        {"from": "...", "to": "...", "date": "YYYY-MM-DD",  # 起始日
         "sleeper_only": false, "direct_only": false,
         "days": 7   # 可选，默认 Config.MULTI_DAY_MAX_DAYS}

    Response JSON：
        {"days": [{"date": "...", "plan": {...} | null}, ...],
         "best": {"date": "...", "plan": {...}} | null}
    """
    body = request.get_json(silent=True) or {}
    from_city = (body.get("from") or "").strip()
    to_city = (body.get("to") or "").strip()
    start_date = (body.get("date") or "").strip()
    sleeper_only = bool(body.get("sleeper_only", False))
    direct_only = bool(body.get("direct_only", False))
    try:
        raw_days = int(body.get("days") or Config.MULTI_DAY_MAX_DAYS)
    except (ValueError, TypeError):
        raw_days = Config.MULTI_DAY_MAX_DAYS
    days_n = min(max(raw_days, 1), Config.MULTI_DAY_MAX_DAYS)

    if not from_city or not to_city:
        return jsonify({"error": "出发地和目的地不能为空"}), 400
    if len(from_city) > 50 or len(to_city) > 50:
        return jsonify({"error": "站名过长"}), 400
    if not start_date:
        return jsonify({"error": "请选择起始日期"}), 400
    try:
        d0 = date.fromisoformat(start_date)
    except ValueError:
        return jsonify({"error": "日期格式无效，请使用 YYYY-MM-DD"}), 400
    if d0 < date.today():
        return jsonify({"error": "起始日期不能早于今天"}), 400
    if d0 + timedelta(days=days_n - 1) > date.today() + timedelta(days=30):
        return jsonify({"error": "目前仅支持查询 30 天内的票务信息"}), 400

    days_payload = []
    best = None
    for i in range(days_n):
        d = (d0 + timedelta(days=i)).isoformat()
        try:
            plans, _w = build_recommendations(
                from_city=from_city,
                to_city=to_city,
                date=d,
                allow_transfer=not direct_only,
                sleeper_only=sleeper_only,
                direct_only=direct_only,
            )
        except (ValueError, RuntimeError) as exc:
            logger.warning("多日查询某天失败 date=%s err=%s", d, exc)
            plans = []
        top = plans[0].as_dict() if plans else None
        days_payload.append({"date": d, "plan": top})
        if top and (best is None or top["score"] > best["plan"]["score"]):
            best = {"date": d, "plan": top}

    return jsonify({"days": days_payload, "best": best})


@app.get("/api/destination")
@_limit(Config.RATE_LIMIT_DESTINATION)
def api_destination():
    """目的地攻略接口。

    Query:
        city: 目的城市/站名，如"上海"或"北京西"

    Response 200:
        {
            "city": "上海",
            "summary": "...",
            "foods":       [{"name": "...", "desc": "..."}],
            "attractions": [{"name": "...", "desc": "..."}]
        }

    Response 502:
        {"error": "..."}
    """
    city = (request.args.get("city") or "").strip()
    if not city:
        return jsonify({"error": "缺少 city 参数"}), 400
    if len(city) > 50:
        return jsonify({"error": "城市名称过长"}), 400
    try:
        guide = get_guide(city)
    except RuntimeError as exc:
        logger.warning("目的地攻略生成失败 city=%s err=%s", city, exc)
        return jsonify({"error": str(exc)}), 502
    return jsonify(guide)


def run():
    app.run(host="0.0.0.0", port=Config.PORT, debug=Config.DEBUG)


if __name__ == "__main__":
    run()
