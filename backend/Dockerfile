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

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
