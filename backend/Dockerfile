# SECURITY: pin python base image to a specific patch release (reproducible
# builds, no surprise upstream drift); run as non-root.
FROM python:3.12.10-slim

WORKDIR /app
# 精确锁定依赖（可复现构建）：requirements.txt 为精确版本。
# 大陆服务器连不上 pypi.org 时构建加：
#   docker compose build --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ api
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt .
RUN pip install --no-cache-dir -i "$PIP_INDEX_URL" -r requirements.txt
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

ENV PYTHONPATH=/app
EXPOSE 8000

# SECURITY: run as an unprivileged user; a container escape then lands as
# 'app' instead of root.
RUN useradd --create-home --shell /usr/sbin/nologin app \
    && chown -R app:app /app
USER app

# --timeout-graceful-shutdown：给"停机"一个确定的边界。
#
# 为什么必须显式设（2026-09-26 实测）：这个服务有一批**长连接**（SSE：/events、
# /agent/stream）。docker 发 SIGTERM 后，uvicorn 默认会一直等这些连接自己结束，
# 而它们本来就不会结束——于是停机只能靠 docker 的 SIGKILL 收场（默认 10 秒），
# 中途被硬杀的请求没有机会收尾（正在写的保存可能只落一半）。
# 设 5 秒（< docker 默认的 10 秒 stop_grace_period）后：先让在飞请求收尾，
# 到点主动退出，日志里能留下"是主动停的"而不是被杀。
# 另外两条实测读数：新容器启动到能服务只要 4 秒左右（14:42:03 起 → 14:42:07 第一个请求），
# 所以换容器那 10 来秒的不可用主要花在停机与重建上，不在启动上。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--timeout-graceful-shutdown", "5"]
