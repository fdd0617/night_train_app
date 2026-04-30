# 🌙 夜行列车推荐系统（Night Train Recommender）

基于 12306 实时数据，智能推荐适合夜间乘坐的列车方案，帮助旅行者在睡眠中完成旅途、节省住宿开支。

---

## 项目名称说明

| 名称 | 含义 |
|------|------|
| `night_train_app` | 项目包目录名，Python 可导入包 |
| 夜行列车推荐系统 | 中文名，强调核心功能：推荐适合"睡着到终点"的夜间列车 |
| Night Train Recommender | 英文名，对外展示 / 文档使用 |

---

## 功能特性

- **实时查询**：对接 12306 公开接口，获取真实车次与票务信息
- **智能评分**：综合夜间乘车占比、早晨到达、总耗时、换乘次数、卧铺有无等多维度打分
- **中转推荐**：自动枚举全国 28 个主要枢纽，并行查询一次中转方案
- **条件筛选**：支持"仅卧铺"、"仅直达"等快速过滤
- **站名补全**：前端输入框实时调用搜索接口，自动补全站名

---

## 环境要求

- Python **3.11+**
- pip

---

## 快速开始

### 1. 克隆 / 进入项目目录

```bash
cd Python实战项目/night_train_app
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量（可选）

复制示例配置并按需修改：

```bash
cp .env.example .env
# 编辑 .env，填入你的 OPENAI_API_KEY 等
```

> 🔐 **安全提示**：`.env` 已在 [.gitignore](.gitignore) 中被排除，绝不会被推送到 GitHub。
> 仓库里只提交占位用的 [.env.example](.env.example)，请确保**真实 key 只写在本地 `.env` 中**。
> 启动时会自动通过 `python-dotenv` 加载该文件（无需手动 `source`）。

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `PORT` | `5000` | 服务监听端口 |
| `RAIL_TIMEOUT` | `10` | 12306 请求超时（秒） |
| `STATION_CACHE_PATH` | `station_names.json` | 站点名称缓存文件路径，留空则每次内存加载 |
| `NIGHT_START_HOUR` | `21` | 夜间时段开始时刻（24h） |
| `NIGHT_END_HOUR` | `8` | 夜间时段结束时刻（次日，24h） |
| `OPENAI_API_KEY` | _无_ | 目的地攻略生成所需的 API Key，**未配置则不显示攻略卡片**（不影响行程查询） |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容服务地址，可改为 DeepSeek / OpenRouter / 通义 等 |
| `OPENAI_MODEL` | `gpt-4o-mini` | 用于生成攻略的模型名 |
| `DEST_CACHE_TTL` | `604800`（7 天） | 攻略内存缓存秒数 |
| `DEST_TIMEOUT` | `30` | LLM 单次请求超时（秒） |

#### 目的地攻略：接入其他兼容服务

只需修改 `OPENAI_BASE_URL` 与 `OPENAI_MODEL` 两个环境变量，即可接入任意 OpenAI 兼容服务：

```bash
# DeepSeek
export OPENAI_API_KEY=sk-xxx
export OPENAI_BASE_URL=https://api.deepseek.com/v1
export OPENAI_MODEL=deepseek-chat

# 通义千问 DashScope（OpenAI 兼容模式）
export OPENAI_API_KEY=sk-xxx
export OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
export OPENAI_MODEL=qwen-plus

# OpenRouter
export OPENAI_API_KEY=sk-or-xxx
export OPENAI_BASE_URL=https://openrouter.ai/api/v1
export OPENAI_MODEL=openai/gpt-4o-mini
```

### 4. 启动服务

**方式一：直接运行启动脚本（推荐开发用）**

```bash
# 在 Python实战项目/ 的上级目录执行
python -m night_train_app.run
# 或进入 Python实战项目/ 目录后
python night_train_app/run.py
```

服务启动后访问：<http://127.0.0.1:5000>

**方式二：通过 Flask CLI**

```bash
export FLASK_APP=night_train_app.app
flask run --port 5000
```

**方式三：生产部署（gunicorn）**

```bash
# 在 Python实战项目/ 的上级目录执行
gunicorn 'night_train_app.app:app' \
  --bind 0.0.0.0:5000 \
  --workers 4 \
  --timeout 60 \
  --access-logfile -
```

**方式四：Docker**

```bash
docker build -t night-train-app .
docker run --rm -p 5000:5000 \
  --env-file .env \
  --name night-train-app \
  night-train-app
# 健康检查：docker ps 会显示 (healthy)
```

---

## API 文档

### `GET /api/stations/search`

站名模糊搜索，供前端自动补全使用。

**参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `q` | string | 搜索关键词（中文站名或拼音） |

**响应示例**

```json
[
  { "name": "北京", "code": "BJP" },
  { "name": "北京西", "code": "BXP" }
]
```

---

### `POST /api/recommend`

查询并推荐夜行列车方案。

**请求体（JSON）**

```json
{
  "from": "北京",
  "to": "上海",
  "date": "2026-05-01",
  "sleeper_only": false,
  "direct_only": false
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `from` | string | ✅ | 出发站名 |
| `to` | string | ✅ | 目的站名 |
| `date` | string | ✅ | 出发日期，格式 `YYYY-MM-DD`，仅支持今日起 30 天内 |
| `sleeper_only` | bool | ❌ | 是否只返回含卧铺的方案，默认 `false` |
| `direct_only` | bool | ❌ | 是否只返回直达方案，默认 `false` |

**响应示例**

```json
{
  "total": 3,
  "warnings": [],
  "plans": [
    {
      "is_direct": true,
      "depart_time": "21:28",
      "arrive_time": "07:42",
      "arrive_date": "2026-05-02",
      "total_minutes": 614,
      "night_ratio": 0.921,
      "arrives_morning": true,
      "has_sleeper": true,
      "score": 0.8134,
      "reasons": [
        "夜间乘车占比 92%，几乎全程在夜里",
        "早晨 07:42 到达，全天可安排游览",
        "全程约 10 小时 14 分钟",
        "全程直达，无需换乘",
        "有卧铺席别，夜间可平躺休息"
      ],
      "transfer_station": null,
      "segments": [...]
    }
  ]
}
```

---

### `GET /api/health`

健康检查端点，用于负载均衡 / 容器编排的存活探针。

**响应示例（200）**

```json
{
  "status": "ok",
  "time": "2026-04-30T18:00:00+00:00",
  "version": "1.0.0",
  "checks": {
    "stations_loaded": true,
    "station_count": 3365,
    "llm_configured": true
  }
}
```

站点列表加载失败时返回 `503 degraded`。

---

### `GET /api/destination`

根据目的城市生成攻略（简介 / 当地美食 / 必游景点）。结果由 LLM 生成，进程内缓存 7 天。

**参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `city` | string | 目的城市名或站名（自动剥离「站」「东」「西」「南」「北」等后缀） |

**响应示例**

```json
{
  "city": "上海",
  "summary": "上海是中国最大的经济中心，融合江南水乡与国际都市风格…",
  "foods": [
    { "name": "生煎包",   "desc": "底脆汁多，本帮经典早餐。" },
    { "name": "小笼包",   "desc": "薄皮多汁，南翔老字号最负盛名。" }
  ],
  "attractions": [
    { "name": "外滩",     "desc": "黄浦江畔欣赏万国建筑群。" },
    { "name": "豫园",     "desc": "明代古典园林，邻近老城隍庙。" }
  ]
}
```

未配置 `OPENAI_API_KEY` 或 LLM 调用失败时返回 `502` + `{"error": "..."}`，前端会静默降级，不影响行程查询。

---

## 项目结构

```
night_train_app/
├── README.md                  # 本文档
├── requirements.txt           # Python 依赖
├── .env.example               # 环境变量示例
├── __init__.py
├── run.py                     # 独立启动脚本（开发用，端口 5500）
├── app.py                     # Flask 应用入口，路由定义
├── models.py                  # 核心数据模型（TrainSegment / TripPlan / StationInfo）
│
├── adapters/
│   ├── __init__.py
│   └── rail12306_client.py    # 12306 接口适配层（站点查询 / 车次查询）
│
├── services/
│   ├── __init__.py
│   ├── recommendation.py      # 推荐引擎（评分算法 / 中转枚举 / 结果排序）
│   └── destination.py         # 目的地攻略生成（OpenAI 兼容 LLM + 内存缓存）
│
├── static/
│   ├── app.css                # 前端样式
│   └── app.js                 # 前端交互逻辑（站名补全 / 结果渲染）
│
├── templates/
│   └── index.html             # 主页模板（Jinja2）
│
└── tests/
    ├── __init__.py
    ├── test_app_api.py        # Flask 路由接口测试
    └── test_recommendation.py # 推荐引擎单元测试
```

---

## 评分算法说明

推荐分由五项加权求和，满分约为 1.0：

| 维度 | 权重 | 说明 |
|------|------|------|
| 夜间乘车占比 | 40% | 行程中处于 21:00–08:00 的时间比例，越高越好 |
| 早晨到达奖励 | 25% | 06:00–10:00 到达得满分，否则为 0 |
| 总耗时 | 20% | 越短越好，线性归一化到最大合理时长（直达 40h / 中转 50h） |
| 中转惩罚 | 10% | 直达得满分，中转得 50% |
| 卧铺奖励 | 5% | 含卧铺席别（硬卧 / 软卧）得满分，否则为 0 |

---

## 运行测试

```bash
# 在项目根目录（Python实战项目/的上级）执行
python -m pytest night_train_app/tests/ -v
```

---

## 注意事项

- 本项目仅对接 12306 公开查询接口，不涉及登录、购票等操作
- 受 12306 频率限制，中转查询并发数已控制在 6 线程以内
- 仅支持查询今日起 **30 天内**的票务信息（与 12306 限制一致）
