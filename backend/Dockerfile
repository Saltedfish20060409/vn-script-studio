FROM python:3.12-slim

WORKDIR /app
# 固定版本构建（可复现）：requirements-lock.txt 是 pip freeze 全量锁定。
# requirements.txt（>= 浮动）仅供 CI/dev 解析顶层依赖。
COPY requirements-lock.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
