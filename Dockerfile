# syntax=docker/dockerfile:1.6
# 多阶段构建：第一阶段装依赖，第二阶段拷过去运行，最终镜像更小
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY requirements.txt .
RUN pip install --user -r requirements.txt

# ─────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/app/.local/bin:$PATH \
    PORT=5000 \
    GUNICORN_WORKERS=4 \
    GUNICORN_TIMEOUT=60

RUN useradd --create-home --shell /bin/bash app

WORKDIR /home/app
COPY --from=builder --chown=app:app /root/.local /home/app/.local

# 把项目作为 night_train_app 包放入容器
COPY --chown=app:app . /home/app/night_train_app/

USER app

EXPOSE 5000

# 健康检查（依赖 /api/health）
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; \
    sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{__import__(\"os\").environ.get(\"PORT\",\"5000\")}/api/health', timeout=3).status == 200 else 1)"

# gunicorn 启动 —— sh -c 让 ${...} 在容器中展开
CMD ["sh", "-c", "gunicorn 'night_train_app.app:app' \
     --bind 0.0.0.0:${PORT} \
     --workers ${GUNICORN_WORKERS} \
     --timeout ${GUNICORN_TIMEOUT} \
     --access-logfile - \
     --error-logfile -"]
